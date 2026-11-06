"""One ``--print`` turn through the running worker.

The worker owns everything a turn may need that this short-lived process
does not have: the desktop App's built-in browser, the channel bridges, the
permission store, the memory writer and the sessions the Web UI shows. A
one-shot turn that ran here, in its own runtime, could not reach any of
them; the agent in a resumed Web session saw no browser at all.

So a one-shot turn is sent to the worker over its WebSocket, with the same
``chat`` command the Web UI sends, and this process only relays frames: it
collects the reply (or the structured output), answers the agent's
follow-up questions from the terminal, and cancels the execution on
Ctrl-C. The turn lands in the session store the way a Web turn does, so
the Web UI shows it live and on reload.

The turn outlives the socket. A worker restart (a refresh, a promote)
closes every connection while the execution checkpoints and resumes on
the worker that comes back; once the ack has named the execution, the
relay reconnects, reads where the execution stands and follows the same
session and message id to the end, reading the reply from the session
when the turn finished while no socket was open.

:func:`resolve_worker` says whether a worker is there to take the turn;
without one the caller runs the turn in-process as before.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

_log = logging.getLogger(__name__)

# Set to ``1`` to run a ``--print`` turn in this process even while a
# worker is up: for a turn that must not touch the worker's sessions, or
# to reproduce the fallback path.
IN_PROCESS_ENV = "OPENPROGRAM_PRINT_IN_PROCESS"

_CONNECT_TIMEOUT_S = 10.0
# After the worker closed the socket mid-turn (a restart), how long the relay
# keeps looking for a worker to follow the turn on, and how often it looks.
_REATTACH_WINDOW_S = 180.0
_REATTACH_INTERVAL_S = 2.0
# Reattached and hearing nothing, how often the execution's state is read
# again, so a turn that ended without a frame this socket saw still ends
# the relay.
_SNAPSHOT_INTERVAL_S = 15.0


class WorkerTurnError(RuntimeError):
    """The worker ended the turn with an error frame.

    ``code`` is the frame's error code when it carried one (an admission
    refusal, a structured-output failure); ``issues`` are the validation
    issues of a structured-output failure.
    """

    def __init__(self, message: str, *, code: str | None = None,
                 issues: list | None = None):
        super().__init__(message)
        self.code = code
        self.issues = list(issues or [])


class WorkerTurnCancelled(RuntimeError):
    """The execution was cancelled before it produced a reply."""


@dataclass(frozen=True)
class WorkerTurn:
    """What one worker-run turn came back with."""

    reply: str
    structured_output: Any = None
    session_id: str = ""
    msg_id: str = ""
    assistant_msg_id: str = ""


def resolve_worker():
    """The verified endpoint of the running worker, or ``None``.

    ``None`` means the turn runs in-process: no worker is up for this
    profile, its state files do not verify, or the environment asks for
    the in-process path.
    """
    if os.environ.get(IN_PROCESS_ENV, "").strip() == "1":
        return None
    from openprogram.host.security.backend_endpoint import (
        OwnerAuthError,
        resolve_backend_endpoint,
    )
    try:
        return resolve_backend_endpoint()
    except (OwnerAuthError, OSError, ValueError) as exc:
        _log.debug("no worker for the one-shot turn: %s", exc)
        return None


def _response_format_payload(response_format) -> Any:
    if response_format is None:
        return None
    if hasattr(response_format, "model_dump"):
        return response_format.model_dump(mode="json")
    if dataclasses.is_dataclass(response_format):
        return dataclasses.asdict(response_format)
    return response_format


def _terminal_ask(question: str, function: str) -> str | None:
    """Ask the agent's follow-up question on the terminal.

    Without a terminal to ask on (a pipeline, a cron job) the question
    goes unanswered: the turn continues as if the user had not replied,
    which is what the Web UI does when the page is gone.
    """
    if not sys.stdin.isatty():
        return None
    label = f" ({function})" if function else ""
    sys.stderr.write(f"\n? {question}{label}\n> ")
    sys.stderr.flush()
    try:
        line = sys.stdin.readline()
    except (OSError, ValueError):
        return None
    if not line:
        return None
    return line.rstrip("\n")


_LIVE_STATUSES = frozenset({"queued", "running", "pausing", "paused", "cancelling"})


def _open(endpoint):
    """Connect to the worker; a handshake failure of any kind is a
    :class:`WorkerTurnError`."""
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect as _connect

    try:
        return _connect(
            endpoint.websocket_url,
            additional_headers={
                "Authorization": endpoint.authorization_header,
                "Origin": endpoint.origin,
            },
            open_timeout=_CONNECT_TIMEOUT_S,
            max_size=None,
        )
    except (OSError, ConnectionClosed, TimeoutError) as exc:
        raise WorkerTurnError(f"cannot connect to the worker: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - handshake failures of every kind
        raise WorkerTurnError(f"cannot connect to the worker: {exc}") from exc


def _reply_text(content: Any) -> str:
    """The text of a stored assistant message, whichever shape it was saved in."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "") for part in content
            if isinstance(part, dict) and part.get("type") in (None, "text")
        )
    return "" if content is None else str(content)


class _Relay:
    """The state of one turn's relay across the sockets it travels on.

    The first socket carries the ``chat`` command and its ack, which names
    the execution. Should the worker close that socket (a restart), the
    execution outlives it: the relay opens a socket to the worker that
    comes back, reads the execution's state and goes on following the same
    session and message id, so the reply still reaches the terminal.
    """

    def __init__(self, session_id: str, request_id: str, on_text, ask):
        self.session_id = session_id
        self.request_id = request_id
        self.on_text = on_text
        self.ask = ask
        self.execution_id: str | None = None
        self.status_version = None
        self.msg_id: str | None = None
        # Set once the relay follows the turn on a socket other than the one
        # that sent it: frames may have passed while no socket was open, so
        # the execution's state is read on connect and again whenever the
        # socket stays quiet.
        self.reattached = False
        self.awaiting_reply = False

    # -- helpers -----------------------------------------------------------

    def _answers_this_send(self, data: dict) -> bool:
        echoed = data.get("client_request_id")
        if echoed is not None:
            return echoed == self.request_id
        return data.get("session_id") == self.session_id

    def _other_turn(self, data: dict) -> bool:
        """A frame of another execution in this session.

        A sub-agent the turn spawns runs as a branch of the same session
        and streams, ends and fails under its own message id; only the
        frames carrying the acked message id (or none, before the ack)
        belong to this turn.
        """
        theirs = data.get("msg_id")
        return bool(self.msg_id) and bool(theirs) and theirs != self.msg_id

    def cancel(self, ws) -> None:
        if not self.execution_id:
            return
        try:
            ws.send(json.dumps({
                "action": "execution.cancel",
                "execution_id": self.execution_id,
                "expected_version": self.status_version,
            }))
        except Exception:
            _log.debug("cancel after Ctrl-C failed", exc_info=True)

    def query_state(self, ws) -> None:
        """Ask the worker where the execution stands; the answer is an
        ``execution.replay`` frame."""
        ws.send(json.dumps({
            "action": "execution.events",
            "execution_id": self.execution_id,
            "after_sequence": 0,
            "snapshot_only": True,
        }))

    @property
    def assistant_msg_id(self) -> str:
        return f"{self.msg_id}_reply" if self.msg_id else ""

    # -- the loop ----------------------------------------------------------

    def follow(self, ws) -> WorkerTurn:
        """Relay frames on ``ws`` until the turn ends.

        Raises ``ConnectionClosed`` when the worker closes the socket; the
        caller decides whether the turn can be followed elsewhere.
        """
        while True:
            try:
                raw = ws.recv(timeout=_SNAPSHOT_INTERVAL_S if self.reattached else None)
            except KeyboardInterrupt:
                self.cancel(ws)
                raise
            except TimeoutError:
                # Quiet socket after a reattach: the turn may have ended
                # with frames this socket never saw.
                self.query_state(ws)
                continue
            try:
                frame = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(frame, dict):
                continue
            kind = frame.get("type")
            data = frame.get("data")
            if not isinstance(data, dict):
                data = {}

            if kind == "chat_ack":
                if self._answers_this_send(data):
                    self.execution_id = data.get("execution_id")
                    self.status_version = data.get("status_version")
                    self.msg_id = data.get("msg_id")
                continue
            if kind == "action_error":
                raise WorkerTurnError(
                    str(frame.get("message") or data.get("message")
                        or "the worker refused the turn"),
                    code=frame.get("code") or data.get("code"),
                )
            if kind == "operation_error":
                if data.get("session_id") in (None, self.session_id):
                    raise WorkerTurnError(
                        str(data.get("message") or "the worker refused the turn"),
                        code=data.get("code"),
                    )
                continue
            if kind == "execution.replay":
                if (frame.get("execution_id") or data.get("execution_id")) != self.execution_id:
                    continue
                self._on_state(ws, frame)
                continue
            if kind == "session_loaded":
                if self.awaiting_reply and data.get("id") == self.session_id:
                    return self._reply_from_session(data)
                continue
            if kind != "chat_response" or data.get("session_id") != self.session_id:
                continue
            if self._other_turn(data):
                continue

            what = data.get("type")
            if what == "stream_event":
                event = data.get("event")
                if (self.on_text is not None and isinstance(event, dict)
                        and event.get("type") == "text"):
                    self.on_text(str(event.get("text") or ""))
            elif what == "result":
                return WorkerTurn(
                    reply=str(data.get("content") or ""),
                    structured_output=data.get("structured_output"),
                    session_id=self.session_id,
                    msg_id=str(data.get("msg_id") or self.msg_id or ""),
                    assistant_msg_id=str(data.get("assistant_msg_id") or ""),
                )
            elif what == "local_command":
                # A slash command the worker answered itself; no model turn
                # follows.
                return WorkerTurn(
                    reply=str(data.get("content") or ""),
                    session_id=self.session_id,
                )
            elif what == "error":
                if not self._answers_this_send(data):
                    continue
                raise WorkerTurnError(
                    str(data.get("content") or data.get("message") or "turn failed"),
                    code=data.get("code"),
                    issues=data.get("issues"),
                )
            elif what == "cancelled":
                raise WorkerTurnCancelled(str(data.get("content") or "cancelled"))
            elif what == "follow_up_question":
                answer = None
                if self.ask is not None:
                    try:
                        answer = self.ask(
                            str(data.get("question") or ""),
                            str(data.get("function") or ""),
                        )
                    except KeyboardInterrupt:
                        self.cancel(ws)
                        raise
                ws.send(json.dumps({
                    "action": "follow_up_answer",
                    "session_id": self.session_id,
                    "answer": answer if answer is not None else {"_cancelled": True},
                }, ensure_ascii=False))

    def _on_state(self, ws, frame: dict) -> None:
        """Act on the execution's state read after a reattach.

        A live execution is followed on; one that ended while no socket was
        open ends the relay the way its frames would have: the reply is read
        from the session, a failure or cancellation is raised.
        """
        error = frame.get("error")
        if error:
            raise WorkerTurnError(
                f"the worker no longer knows the turn's execution ({error}); "
                "the Web UI shows the session"
            )
        snapshot = frame.get("snapshot")
        if not isinstance(snapshot, dict):
            snapshot = {}
        status = str(snapshot.get("status") or "")
        reason = snapshot.get("reason_code")
        if status in _LIVE_STATUSES or not status:
            return
        if status == "completed":
            if not self.awaiting_reply:
                self.awaiting_reply = True
                ws.send(json.dumps({"action": "load_session", "session_id": self.session_id}))
            return
        if status == "cancelled":
            raise WorkerTurnCancelled("cancelled")
        if status == "interrupted" and reason == "restart_new_turn":
            raise WorkerTurnError(
                "the worker restarted and continues the turn as a new turn; "
                "the Web UI shows it", code=reason,
            )
        if status == "reconciliation_required":
            raise WorkerTurnError(
                "the turn stopped: an operation's outcome is unknown and needs "
                "checking in the Web UI", code=reason or status,
            )
        detail = f" ({reason})" if reason else ""
        raise WorkerTurnError(f"the turn {status} on the worker{detail}", code=reason or status)

    def _reply_from_session(self, data: dict) -> WorkerTurn:
        wanted = self.assistant_msg_id
        for row in data.get("messages") or ():
            if isinstance(row, dict) and row.get("id") == wanted:
                return WorkerTurn(
                    reply=_reply_text(row.get("content")),
                    session_id=self.session_id,
                    msg_id=self.msg_id or "",
                    assistant_msg_id=wanted,
                )
        raise WorkerTurnError(
            "the turn finished while the worker restarted, but its reply is not "
            "in the session; the Web UI shows what happened"
        )


def _reattach(relay: _Relay, resolve: Callable[[], Any], closed: Exception):
    """Reach a worker again after one closed the socket mid-turn.

    Returns an open socket on which the execution's state has been asked
    for, or raises :class:`WorkerTurnError` once the window passes.
    """
    deadline = time.monotonic() + _REATTACH_WINDOW_S
    while time.monotonic() < deadline:
        time.sleep(_REATTACH_INTERVAL_S)
        try:
            endpoint = resolve()
        except Exception:  # noqa: BLE001 - the worker's state files mid-write
            endpoint = None
        if endpoint is None:
            continue
        try:
            ws = _open(endpoint)
        except WorkerTurnError:
            continue
        relay.reattached = True
        try:
            relay.query_state(ws)
        except Exception:  # noqa: BLE001 - closed again at once; try the next
            ws.close()
            continue
        return ws
    raise WorkerTurnError(
        "the worker closed the connection before the turn finished "
        f"({closed}) and none came back within {int(_REATTACH_WINDOW_S)} s; "
        "the turn continues on the worker and the Web UI shows it"
    ) from closed


def run_turn_via_worker(
    endpoint,
    session_id: str,
    text: str,
    *,
    response_format=None,
    agent_id: str | None = None,
    on_text: Callable[[str], None] | None = None,
    ask: Callable[[str, str], str | None] | None = _terminal_ask,
    reconnect: Callable[[], Any] | None = None,
) -> WorkerTurn:
    """Send one chat turn to the worker and wait for its result.

    Frames of other sessions share the socket (the worker broadcasts every
    ``chat_response``) and are skipped. ``on_text`` receives the streamed
    text deltas as they arrive; ``ask`` answers a ``follow_up_question``
    frame, ``None`` meaning no answer.

    A worker restart (a refresh, a promote) closes the socket while the
    execution goes on, or resumes, on the worker that comes back. Once the
    ack has named the execution, the relay reconnects (``reconnect`` finds
    the worker again, :func:`resolve_worker` by default), reads where the
    execution stands and follows it to its end; a turn that finished in the
    meantime has its reply read from the session.

    Raises :class:`WorkerTurnError` for an error frame, an ``action_error``
    or ``operation_error`` that answers the send, a socket that closes
    before the ack, a worker that does not come back in time, or an
    execution that failed or was interrupted while no socket was open;
    :class:`WorkerTurnCancelled` when the execution was cancelled;
    ``KeyboardInterrupt`` after cancelling the execution on Ctrl-C.
    """
    from websockets.exceptions import ConnectionClosed

    request_id = uuid.uuid4().hex
    command: dict[str, Any] = {
        "action": "chat",
        "text": text,
        "session_id": session_id,
        "client_request_id": request_id,
    }
    if agent_id:
        command["agent_id"] = agent_id
    payload = _response_format_payload(response_format)
    if payload is not None:
        command["response_format"] = payload

    relay = _Relay(session_id, request_id, on_text, ask)
    ws = _open(endpoint)
    try:
        ws.send(json.dumps(command, ensure_ascii=False))
        while True:
            try:
                return relay.follow(ws)
            except ConnectionClosed as exc:
                ws.close()
                ws = None
                if not relay.execution_id:
                    raise WorkerTurnError(
                        "the worker closed the connection before the turn "
                        f"started ({exc})"
                    ) from exc
                ws = _reattach(relay, reconnect or resolve_worker, exc)
    finally:
        if ws is not None:
            ws.close()


def structured_output_error(error: WorkerTurnError):
    """The :class:`StructuredOutputError` a worker-side structured-output
    failure stands for, so the CLI exits with the same code either way."""
    from openprogram.models.providers.structured_output import (
        StructuredOutputError,
        StructuredOutputSchemaError,
        StructuredOutputUnsupportedError,
    )
    code = error.code or "generation_failed"
    if code == "invalid_schema":
        cls = StructuredOutputSchemaError
    elif code == "unsupported":
        cls = StructuredOutputUnsupportedError
    else:
        cls = StructuredOutputError
    return cls(str(error), code=code, issues=error.issues)


__all__ = [
    "IN_PROCESS_ENV",
    "WorkerTurn",
    "WorkerTurnCancelled",
    "WorkerTurnError",
    "resolve_worker",
    "run_turn_via_worker",
    "structured_output_error",
]
