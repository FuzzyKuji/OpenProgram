"""A ``--print`` turn runs on the running worker.

The CLI connects to the worker's WebSocket with the owner token, sends the
same ``chat`` command the Web UI sends, and relays the frames: text deltas
stream, the result ends the turn, a follow-up question is answered from
the terminal, an error frame becomes an error with its code, and a
structured-output turn returns the parsed value the result frame carries.
Without a worker the turn runs in-process as before.
"""
from __future__ import annotations

import json
import threading
import types
from contextlib import contextmanager

import pytest

from openprogram.host.security.backend_endpoint import BackendEndpoint
from openprogram.interfaces.cli import worker_turn
from openprogram.interfaces.cli.worker_turn import (
    WorkerTurnCancelled,
    WorkerTurnError,
    resolve_worker,
    run_turn_via_worker,
    structured_output_error,
)

TOKEN = "t" * 43
SESSION = "local_test1234"


@contextmanager
def fake_worker(script):
    """A worker that runs ``script(connection, command)`` once a chat arrives.

    ``script`` sends frames with ``connection.send(dict)`` and may read
    further commands with ``connection.recv_json()``. The handshake frames
    the real worker sends first are sent here too. The request headers of
    every connection are kept for the test to inspect.
    """
    from websockets.sync.server import serve

    seen: dict = {"headers": [], "commands": []}

    def handler(connection):
        request_headers = connection.request.headers
        seen["headers"].append({
            "Authorization": request_headers.get("Authorization"),
            "Origin": request_headers.get("Origin"),
        })

        def send(frame: dict) -> None:
            connection.send(json.dumps(frame))

        def recv_json() -> dict:
            command = json.loads(connection.recv())
            seen["commands"].append(command)
            return command

        connection.send_frame = send
        connection.recv_json = recv_json
        for frame in (
            {"type": "functions_list", "data": []},
            {"type": "provider_info", "data": {}},
            {"type": "frontend_build", "data": {"id": "test"}},
        ):
            send(frame)
        command = recv_json()
        script(connection, command)

    server = serve(handler, "127.0.0.1", 0)
    port = server.socket.getsockname()[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield BackendEndpoint(origin=f"http://127.0.0.1:{port}", token=TOKEN), seen
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _ack(connection, command, **extra):
    connection.send_frame({"type": "chat_ack", "data": {
        "session_id": command["session_id"], "msg_id": "u1",
        "execution_id": "exec1", "status_version": 3,
        "client_request_id": command.get("client_request_id"), **extra,
    }})


def _response(connection, session_id, **data):
    connection.send_frame({"type": "chat_response",
                           "data": {"session_id": session_id, **data}})


def test_turn_streams_text_and_ends_with_the_result():
    def script(connection, command):
        assert command["action"] == "chat"
        assert command["text"] == "hello"
        assert command["session_id"] == SESSION
        assert "response_format" not in command
        _ack(connection, command)
        # Another session's frames share the socket and are skipped.
        _response(connection, "other", type="stream_event",
                  event={"type": "text", "text": "NOT MINE"})
        _response(connection, "other", type="result", content="NOT MINE")
        _response(connection, SESSION, type="status", content="thinking")
        _response(connection, SESSION, type="stream_event",
                  event={"type": "text", "text": "hel"})
        _response(connection, SESSION, type="stream_event",
                  event={"type": "thinking", "text": "hmm"})
        _response(connection, SESSION, type="stream_event",
                  event={"type": "text", "text": "lo"})
        _response(connection, SESSION, type="result", content="hello back",
                  msg_id="u1", assistant_msg_id="a1")

    deltas: list[str] = []
    with fake_worker(script) as (endpoint, seen):
        turn = run_turn_via_worker(endpoint, SESSION, "hello", on_text=deltas.append)

    assert turn.reply == "hello back"
    assert turn.structured_output is None
    assert (turn.msg_id, turn.assistant_msg_id) == ("u1", "a1")
    assert deltas == ["hel", "lo"]
    headers = seen["headers"][0]
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["Origin"] == endpoint.origin


def test_frames_of_a_sub_agent_branch_do_not_end_the_turn():
    """A sub-agent the turn spawns runs in the same session under its own
    message id: its text, its result and its error are not this turn's."""
    def script(connection, command):
        _ack(connection, command)
        sid = command["session_id"]
        _response(connection, sid, type="stream_event", msg_id="child1",
                  event={"type": "text", "text": "child text"})
        _response(connection, sid, type="error", msg_id="child1",
                  content="[denied] the child was refused a tool")
        _response(connection, sid, type="result", msg_id="child1",
                  content="the child's report", assistant_msg_id="child1_reply")
        _response(connection, sid, type="stream_event", msg_id="u1",
                  event={"type": "text", "text": "parent text"})
        _response(connection, sid, type="result", msg_id="u1",
                  content="the parent's reply", assistant_msg_id="u1_reply")

    deltas: list[str] = []
    with fake_worker(script) as (endpoint, _seen):
        turn = run_turn_via_worker(endpoint, SESSION, "do it", on_text=deltas.append)
    assert turn.reply == "the parent's reply"
    assert turn.assistant_msg_id == "u1_reply"
    assert deltas == ["parent text"]


def test_follow_up_question_is_answered_through_the_socket():
    def script(connection, command):
        _ack(connection, command)
        _response(connection, SESSION, type="follow_up_question",
                  question="Which one?", function="ask_user")
        answer = connection.recv_json()
        assert answer == {"action": "follow_up_answer", "session_id": SESSION,
                          "answer": "the second"}
        _response(connection, SESSION, type="follow_up_question",
                  question="Sure?", function="ask_user")
        unanswered = connection.recv_json()
        assert unanswered["answer"] == {"_cancelled": True}
        _response(connection, SESSION, type="result", content="done")

    answers = iter(["the second", None])
    asked: list[tuple[str, str]] = []

    def ask(question, function):
        asked.append((question, function))
        return next(answers)

    with fake_worker(script) as (endpoint, _seen):
        turn = run_turn_via_worker(endpoint, SESSION, "go", ask=ask)

    assert turn.reply == "done"
    assert asked == [("Which one?", "ask_user"), ("Sure?", "ask_user")]


def test_error_frame_carries_code_and_issues():
    def script(connection, command):
        _ack(connection, command)
        _response(connection, SESSION, type="error",
                  content="[error] StructuredOutputValidationError: nope",
                  code="validation_failed", issues=[{"path": "$.a", "message": "x"}])

    with fake_worker(script) as (endpoint, _seen):
        with pytest.raises(WorkerTurnError) as info:
            run_turn_via_worker(endpoint, SESSION, "go")
    assert info.value.code == "validation_failed"
    assert info.value.issues == [{"path": "$.a", "message": "x"}]
    assert str(info.value).startswith("[error] StructuredOutputValidationError")


def test_admission_refusal_before_the_ack_ends_the_turn():
    def script(connection, command):
        _response(connection, SESSION, type="error", code="session_busy",
                  content="a turn is already running",
                  client_request_id=command["client_request_id"])

    with fake_worker(script) as (endpoint, _seen):
        with pytest.raises(WorkerTurnError) as info:
            run_turn_via_worker(endpoint, SESSION, "go")
    assert info.value.code == "session_busy"


def test_cancelled_frame_raises_cancelled():
    def script(connection, command):
        _ack(connection, command)
        _response(connection, SESSION, type="cancelled", content="cancelled")

    with fake_worker(script) as (endpoint, _seen):
        with pytest.raises(WorkerTurnCancelled):
            run_turn_via_worker(endpoint, SESSION, "go")


def test_socket_closing_before_the_ack_is_an_error():
    def script(connection, command):
        connection.close()

    with fake_worker(script) as (endpoint, _seen):
        with pytest.raises(WorkerTurnError, match="before the turn started"):
            run_turn_via_worker(endpoint, SESSION, "go")


@pytest.fixture
def quick_reattach(monkeypatch):
    """A reattach window measured in tenths of a second."""
    monkeypatch.setattr(worker_turn, "_REATTACH_WINDOW_S", 0.5)
    monkeypatch.setattr(worker_turn, "_REATTACH_INTERVAL_S", 0.02)
    monkeypatch.setattr(worker_turn, "_SNAPSHOT_INTERVAL_S", 0.1)


def _replay(connection, status, **snapshot):
    connection.send_frame({"type": "execution.replay", "execution_id": "exec1",
                           "snapshot": {"execution_id": "exec1", "status": status, **snapshot}})


def test_no_worker_after_the_socket_closed_mid_turn_is_an_error(quick_reattach):
    """After the ack the turn outlives the socket; without a worker to
    follow it on, the relay says so and where to look."""
    def script(connection, command):
        _ack(connection, command)
        connection.close()

    with fake_worker(script) as (endpoint, _seen):
        with pytest.raises(WorkerTurnError, match="none came back.*Web UI shows it"):
            run_turn_via_worker(endpoint, SESSION, "go", reconnect=lambda: None)


def test_turn_is_followed_on_the_worker_that_comes_back(quick_reattach):
    """A worker restart closes the socket; the relay reconnects, reads the
    execution's state and relays the rest of the same turn."""
    def script(connection, command):
        if command["action"] == "chat":
            _ack(connection, command)
            connection.close()
            return
        assert command == {"action": "execution.events", "execution_id": "exec1",
                           "after_sequence": 0, "snapshot_only": True}
        _replay(connection, "running")
        _response(connection, SESSION, type="stream_event", msg_id="u1",
                  event={"type": "text", "text": "after the restart"})
        _response(connection, SESSION, type="result", content="after the restart",
                  msg_id="u1", assistant_msg_id="u1_reply")

    deltas: list[str] = []
    with fake_worker(script) as (endpoint, seen):
        turn = run_turn_via_worker(endpoint, SESSION, "go", on_text=deltas.append,
                                   reconnect=lambda: endpoint)
    assert turn.reply == "after the restart"
    assert (turn.msg_id, turn.assistant_msg_id) == ("u1", "u1_reply")
    assert deltas == ["after the restart"]
    assert [c["action"] for c in seen["commands"]] == ["chat", "execution.events"]
    assert len(seen["headers"]) == 2


def test_turn_that_ended_while_no_socket_was_open_reads_its_reply(quick_reattach):
    def script(connection, command):
        if command["action"] == "chat":
            _ack(connection, command)
            connection.close()
            return
        _replay(connection, "completed")
        load = connection.recv_json()
        assert load == {"action": "load_session", "session_id": SESSION}
        connection.send_frame({"type": "session_loaded", "data": {"id": SESSION, "messages": [
            {"id": "u1", "role": "user", "content": "go"},
            {"id": "u1_reply", "role": "assistant",
             "content": [{"type": "text", "text": "done "}, {"type": "text", "text": "while away"}]},
        ]}})

    with fake_worker(script) as (endpoint, _seen):
        turn = run_turn_via_worker(endpoint, SESSION, "go", reconnect=lambda: endpoint)
    assert turn.reply == "done while away"
    assert (turn.msg_id, turn.assistant_msg_id) == ("u1", "u1_reply")


def test_quiet_socket_after_a_reattach_reads_the_state_again(quick_reattach):
    """The turn ended between the state read and the frames: nothing arrives,
    so the relay asks again and finds it completed."""
    def script(connection, command):
        if command["action"] == "chat":
            _ack(connection, command)
            connection.close()
            return
        _replay(connection, "running")
        again = connection.recv_json()
        assert again["action"] == "execution.events"
        _replay(connection, "completed")
        assert connection.recv_json()["action"] == "load_session"
        connection.send_frame({"type": "session_loaded", "data": {"id": SESSION, "messages": [
            {"id": "u1_reply", "role": "assistant", "content": "late reply"}]}})

    with fake_worker(script) as (endpoint, _seen):
        turn = run_turn_via_worker(endpoint, SESSION, "go", reconnect=lambda: endpoint)
    assert turn.reply == "late reply"


@pytest.mark.parametrize("status, reason, raises, match", [
    ("failed", "provider_error", WorkerTurnError, "failed on the worker \\(provider_error\\)"),
    ("cancelled", None, WorkerTurnCancelled, "cancelled"),
    ("interrupted", "restart_new_turn", WorkerTurnError, "as a new turn"),
    ("reconciliation_required", "effect_reconciliation", WorkerTurnError, "outcome is unknown"),
])
def test_execution_that_ended_badly_while_away_is_reported(quick_reattach, status, reason, raises, match):
    def script(connection, command):
        if command["action"] == "chat":
            _ack(connection, command)
            connection.close()
            return
        _replay(connection, status, reason_code=reason)

    with fake_worker(script) as (endpoint, _seen):
        with pytest.raises(raises, match=match):
            run_turn_via_worker(endpoint, SESSION, "go", reconnect=lambda: endpoint)


def test_unknown_execution_after_a_reattach_is_an_error(quick_reattach):
    def script(connection, command):
        if command["action"] == "chat":
            _ack(connection, command)
            connection.close()
            return
        connection.send_frame({"type": "execution.replay", "execution_id": "exec1", "error": "not_found"})

    with fake_worker(script) as (endpoint, _seen):
        with pytest.raises(WorkerTurnError, match="no longer knows"):
            run_turn_via_worker(endpoint, SESSION, "go", reconnect=lambda: endpoint)


def test_structured_output_is_sent_and_read_from_the_result_frame():
    from openprogram.models.providers.structured_output import normalize_response_format

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    response_format = normalize_response_format(schema)

    def script(connection, command):
        sent = command["response_format"]
        assert sent["type"] == "json_schema"
        assert sent["schema"] == schema
        # The worker accepts exactly what was sent.
        assert normalize_response_format(sent).schema == schema
        _ack(connection, command)
        _response(connection, SESSION, type="result", content='{"ok": true}',
                  structured_output={"ok": True}, structured_output_mode="native")

    with fake_worker(script) as (endpoint, _seen):
        turn = run_turn_via_worker(endpoint, SESSION, "go", response_format=response_format)
    assert turn.structured_output == {"ok": True}
    assert turn.reply == '{"ok": true}'


def test_no_worker_without_a_reachable_endpoint(monkeypatch):
    from openprogram.host.security import backend_endpoint as be

    def refuse(state_dir=None):
        raise be.OwnerAuthError("no active Web access snapshot")

    monkeypatch.setattr(be, "resolve_backend_endpoint", refuse)
    monkeypatch.delenv(worker_turn.IN_PROCESS_ENV, raising=False)
    assert resolve_worker() is None


def test_in_process_env_skips_the_worker(monkeypatch):
    from openprogram.host.security import backend_endpoint as be

    monkeypatch.setattr(
        be, "resolve_backend_endpoint",
        lambda state_dir=None: BackendEndpoint(origin="http://127.0.0.1:1", token=TOKEN),
    )
    monkeypatch.setenv(worker_turn.IN_PROCESS_ENV, "1")
    assert resolve_worker() is None
    monkeypatch.delenv(worker_turn.IN_PROCESS_ENV)
    assert resolve_worker() is not None


def test_structured_output_error_maps_codes_to_exit_classes():
    from openprogram.models.providers.structured_output import (
        StructuredOutputError,
        StructuredOutputSchemaError,
        StructuredOutputUnsupportedError,
    )
    schema = structured_output_error(WorkerTurnError("bad", code="invalid_schema"))
    unsupported = structured_output_error(WorkerTurnError("no", code="unsupported"))
    failed = structured_output_error(
        WorkerTurnError("no", code="validation_failed", issues=[{"path": "$"}]))
    assert type(schema) is StructuredOutputSchemaError
    assert type(unsupported) is StructuredOutputUnsupportedError
    assert type(failed) is StructuredOutputError
    assert failed.code == "validation_failed" and failed.issues == [{"path": "$"}]


def test_result_frame_names_structured_output_only_for_a_structured_turn():
    from openprogram.runtime.conversation.turn_runtime import _structured_output_fields

    plain = types.SimpleNamespace(structured_output_mode=None, structured_output=None)
    structured = types.SimpleNamespace(structured_output_mode="tool",
                                       structured_output={"ok": True})
    assert _structured_output_fields(plain) == {}
    assert _structured_output_fields(structured) == {
        "structured_output": {"ok": True}, "structured_output_mode": "tool"}


# --- the CLI entry point prefers the worker and falls back in-process ---


def _no_runtime():
    raise AssertionError("the in-process runtime must not be initialised")


def test_print_turn_prefers_the_worker(monkeypatch, capsys):
    from openprogram.interfaces.cli import chat as chat_module

    endpoint = BackendEndpoint(origin="http://127.0.0.1:1", token=TOKEN)
    calls: list[tuple] = []

    def fake_run(ep, session_id, text, *, response_format=None, **_kw):
        calls.append((ep, session_id, text, response_format))
        return worker_turn.WorkerTurn(reply="from the worker", session_id=session_id)

    monkeypatch.setattr(worker_turn, "resolve_worker", lambda: endpoint)
    monkeypatch.setattr(worker_turn, "run_turn_via_worker", fake_run)
    monkeypatch.setattr(chat_module, "_get_chat_runtime", _no_runtime)

    chat_module.run_cli_chat(oneshot="ping", resume="local_abc", tui=False)

    assert capsys.readouterr().out == "from the worker\n"
    assert calls == [(endpoint, "local_abc", "ping", None)]


def test_print_turn_prints_structured_output_as_one_json_line(monkeypatch, capsys):
    from openprogram.interfaces.cli import chat as chat_module
    from openprogram.models.providers.structured_output import normalize_response_format

    endpoint = BackendEndpoint(origin="http://127.0.0.1:1", token=TOKEN)
    monkeypatch.setattr(worker_turn, "resolve_worker", lambda: endpoint)
    monkeypatch.setattr(
        worker_turn, "run_turn_via_worker",
        lambda *a, **k: worker_turn.WorkerTurn(
            reply='{"ok": true}', structured_output={"ok": True, "n": "é"}),
    )
    monkeypatch.setattr(chat_module, "_get_chat_runtime", _no_runtime)

    chat_module.run_cli_chat(
        oneshot="ping", tui=False,
        response_format=normalize_response_format({"type": "object"}),
    )
    assert capsys.readouterr().out == '{"ok":true,"n":"é"}\n'


def test_print_turn_worker_error_exits_nonzero(monkeypatch, capsys):
    from openprogram.interfaces.cli import chat as chat_module

    endpoint = BackendEndpoint(origin="http://127.0.0.1:1", token=TOKEN)
    monkeypatch.setattr(worker_turn, "resolve_worker", lambda: endpoint)

    def fail(*a, **k):
        raise WorkerTurnError("a turn is already running", code="session_busy")

    monkeypatch.setattr(worker_turn, "run_turn_via_worker", fail)
    monkeypatch.setattr(chat_module, "_get_chat_runtime", _no_runtime)

    with pytest.raises(SystemExit) as info:
        chat_module.run_cli_chat(oneshot="ping", tui=False)
    assert info.value.code == 1
    assert capsys.readouterr().err.strip() == "[error] a turn is already running"


def test_print_turn_structured_failure_raises_the_cli_error(monkeypatch):
    from openprogram.interfaces.cli import chat as chat_module
    from openprogram.models.providers.structured_output import (
        StructuredOutputSchemaError,
        normalize_response_format,
    )

    endpoint = BackendEndpoint(origin="http://127.0.0.1:1", token=TOKEN)
    monkeypatch.setattr(worker_turn, "resolve_worker", lambda: endpoint)

    def fail(*a, **k):
        raise WorkerTurnError("Structured output request is invalid", code="invalid_schema")

    monkeypatch.setattr(worker_turn, "run_turn_via_worker", fail)
    monkeypatch.setattr(chat_module, "_get_chat_runtime", _no_runtime)

    with pytest.raises(StructuredOutputSchemaError):
        chat_module.run_cli_chat(
            oneshot="ping", tui=False,
            response_format=normalize_response_format({"type": "object"}),
        )


def test_print_turn_falls_back_in_process_without_a_worker(monkeypatch, capsys):
    from openprogram.interfaces.cli import chat as chat_module
    from openprogram.runtime.agent_registry import manager as agents

    monkeypatch.setattr(worker_turn, "resolve_worker", lambda: None)
    agent = types.SimpleNamespace(id="main")
    monkeypatch.setattr(agents, "get_default", lambda: agent)
    runtime = types.SimpleNamespace(model="m")
    monkeypatch.setattr(chat_module, "_get_chat_runtime", lambda: ("prov", runtime))
    calls: list[tuple] = []

    def fake_turn(agent_arg, session_id, text, *, console=None, response_format=None):
        calls.append((agent_arg, session_id, text, response_format))
        return "in-process reply"

    monkeypatch.setattr(chat_module, "_run_turn_with_history", fake_turn)

    chat_module.run_cli_chat(oneshot="ping", resume="local_abc", tui=False)

    assert capsys.readouterr().out == "in-process reply\n"
    assert calls == [(agent, "local_abc", "ping", None)]
