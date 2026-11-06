"""Agent event stream lifecycle: stream creation, job activity heartbeats, interruption and cancellable producers."""
from __future__ import annotations

import asyncio
from openprogram.models.providers.utils.event_stream import EventStream
from openprogram.runtime.agent.loop.types import (
    AgentEvent,
    AgentMessage,
)
import logging

_log = logging.getLogger(__name__)


def _create_agent_stream() -> EventStream[AgentEvent, list[AgentMessage]]:
    return EventStream(
        is_done=lambda e: e.type == "agent_end",
        get_result=lambda e: e.messages if e.type == "agent_end" else [],
    )


def _record_job_activity(kind: str) -> None:
    try:
        from openprogram.runtime.agent.engine_link import record_job_activity
        record_job_activity(kind)
    except Exception:
        # Job activity is best-effort bookkeeping for the idle watchdog.
        _log.debug("job activity %r not recorded", kind, exc_info=True)


def _job_operation_timeout(declared: float | None) -> float | None:
    from openprogram.runtime.agent.engine_link import job_operation_timeout
    return job_operation_timeout(declared)


def _finish_interrupted_stream(stream, exc, messages, cancel_event) -> None:
    from openprogram.host.cancellation import CancelledError, check_cancelled
    from openprogram.models.providers.utils.errors import ExecInterrupt

    cancelled = isinstance(exc, (CancelledError, asyncio.CancelledError)) or bool(
        cancel_event is not None and cancel_event.is_set()
    )
    if isinstance(exc, ExecInterrupt) and not cancelled:
        from openprogram.runtime.agent.engine_link import worker_stopping
        if worker_stopping():
            if not stream._result_event.is_set():
                stream.fail(exc)
            return
        # A synchronous callback can observe the owner's cancellation before
        # this event loop has delivered its asynchronously bridged signal.
        try:
            check_cancelled()
        except CancelledError:
            cancelled = True
    if isinstance(exc, (CancelledError, asyncio.CancelledError, ExecInterrupt)) and cancelled:
        if not stream._result_event.is_set():
            stream.end(messages)
    elif isinstance(exc, ExecInterrupt):
        if not stream._result_event.is_set():
            stream.fail(exc)
    else:
        raise exc



def _attach_cancellable_producer(stream, coroutine, cancel_event):
    """Interrupt pending I/O even when a provider/tool emits no events."""
    producer = asyncio.ensure_future(coroutine)
    stream.attach_producer(producer)
    if cancel_event is None:
        return

    async def watch_cancel():
        # The signal is part of request option snapshots; do not attach an
        # asyncio Future to it (deep-copying a pending Event is invalid).
        while not cancel_event.is_set():
            await asyncio.sleep(0.05)
        if not producer.done():
            producer.cancel()
            done, _ = await asyncio.wait({producer}, timeout=1.0)
            if not done:
                producer.cancel()

    watcher = asyncio.create_task(watch_cancel())
    producer.add_done_callback(lambda _: watcher.cancel())
