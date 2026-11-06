"""
Unified streaming functions — mirrors packages/ai/src/stream.ts

Provides stream(), complete(), stream_simple(), complete_simple().
"""
from __future__ import annotations

from contextlib import contextmanager
import inspect
import time
from typing import AsyncGenerator, Awaitable, Callable

from ..catalog.api_registry import get_api_provider
from .budget import BudgetedRequest
from openprogram.models.usage.request import RequestReceipt
from ..settings.env_api_keys import resolve_provider_key
from ..types import (
    AssistantMessage,
    AssistantMessageEvent,
    Context,
    Model,
    SimpleStreamOptions,
    StreamOptions,
)
import logging

_log = logging.getLogger(__name__)


@contextmanager
def _job_operation_deadline():
    """Bind one provider request to the claimed job's remaining time."""
    from openprogram.state.execution_facts import (
        current_job_operation_timeout,
        record_current_job_activity,
    )
    from openprogram.models.providers.utils.deadline import (
        get_deadline,
        reset_deadline,
        set_deadline,
    )

    timeout = current_job_operation_timeout(None, preemptibility="async")
    deadline = None if timeout is None else time.monotonic() + timeout
    outer = get_deadline()
    if outer is not None and (deadline is None or outer < deadline):
        deadline = outer
    token = set_deadline(deadline) if deadline is not None else None
    record_current_job_activity("operation_start")
    try:
        yield record_current_job_activity
    finally:
        if token is not None:
            reset_deadline(token)


async def stream_simple(
    model: Model,
    context: Context,
    options: SimpleStreamOptions | None = None,
) -> AsyncGenerator[AssistantMessageEvent, None]:
    """
    Stream a response with unified reasoning options.
    Automatically resolves API key from environment if not provided.
    Mirrors streamSimple() from TypeScript.
    """
    from openprogram.models.auth.provider_policy import require_supported_provider
    require_supported_provider(model.provider)
    with _job_operation_deadline() as record_activity:
        provider = get_api_provider(model.api)
        async for event in stream_simple_with_provider(provider, model, context, options):
            record_activity("provider_data")
            yield event


async def stream_simple_with_provider(
    provider,
    model: Model,
    context: Context,
    options: SimpleStreamOptions | None = None,
    get_api_key: Callable[[str], str | None | Awaitable[str | None]] | None = None,
) -> AsyncGenerator[AssistantMessageEvent, None]:
    """Stream through an already-resolved request-scoped provider snapshot."""
    from openprogram.models.auth.provider_policy import require_supported_provider
    require_supported_provider(model.provider)
    opts = options or SimpleStreamOptions()

    if provider is None:
        raise ValueError(f"No stream function registered for API: {model.api!r}")

    # Reserve budget BEFORE credentials or network: a denied call must never
    # resolve a key or open a socket. Returns None for unbudgeted callers.
    budget = BudgetedRequest.begin(model, context, opts, provider)
    receipt = None
    try:
        receipt = RequestReceipt.begin(model, opts, provider_context=context, provider=provider, budget=budget)
        if budget is not None:
            opts = budget.clamp(opts, model)
        if receipt is not None:
            opts = receipt.clamp(opts, model)

        if get_api_key is not None:
            key_result = get_api_key(model.provider)
            if inspect.isawaitable(key_result):
                key_result = await key_result
            if key_result:
                opts = opts.model_copy(update={"api_key": key_result})

        # Auto-resolve API key if not set. resolve_provider_key reads the
        # AuthStore (the single key source — no env vars, no config.json).
        if not opts.api_key and getattr(provider, "requires_credentials", True):
            opts = opts.model_copy(
                update={"api_key": resolve_provider_key(model.provider)},
            )
    except BaseException:
        if budget is not None:
            budget.release()
        if receipt is not None:
            receipt.release()
        raise

    recorded = False
    async for event in _metered(provider.stream_simple, model, context, opts, budget, receipt):
        # Record AT the terminal event, not after the loop: the consumer
        # (agent_loop) returns the moment it sees the done/error event,
        # leaving this generator suspended at ``yield`` — a post-loop line
        # would never run. The terminal event carries the final message, so
        # we have everything we need to record before yielding it onward.
        if not recorded:
            final = _extract_final(event)
            if final is not None:
                recorded = True
                if receipt is not None:
                    receipt.settle(final)
                elif budget is not None:
                    budget.settle(model, final, opts)
                else:
                    _record_usage(model, final, opts)
            elif receipt is not None:
                _observe_usage(receipt, event)
        yield event


async def complete_simple(
    model: Model,
    context: Context,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessage:
    """
    Get a complete (non-streaming) response.
    Mirrors completeSimple() from TypeScript.
    """
    final_message: AssistantMessage | None = None

    async for event in stream_simple(model, context, options):
        final_message = _extract_final(event) or final_message

    if final_message is None:
        raise RuntimeError("Stream completed without a final message")

    return final_message


async def stream(
    model: Model,
    context: Context,
    options: StreamOptions | None = None,
) -> AsyncGenerator[AssistantMessageEvent, None]:
    """
    Stream with provider-specific options (no reasoning normalization).
    Mirrors stream() from TypeScript.
    """
    from openprogram.models.auth.provider_policy import require_supported_provider
    require_supported_provider(model.provider)
    with _job_operation_deadline() as record_activity:
        opts = options or StreamOptions()

        provider = get_api_provider(model.api)
        if provider is None:
            raise ValueError(f"No stream function registered for API: {model.api!r}")

        budget = BudgetedRequest.begin(model, context, opts, provider)
        receipt = None
        try:
            receipt = RequestReceipt.begin(model, opts, provider_context=context, provider=provider, budget=budget)
            if budget is not None:
                opts = budget.clamp(opts, model)
            if receipt is not None:
                opts = receipt.clamp(opts, model)

            # Auto-resolve API key from the AuthStore if not set (same as stream_simple)
            if not opts.api_key and getattr(provider, "requires_credentials", True):
                opts = opts.model_copy(
                    update={"api_key": resolve_provider_key(model.provider)},
                )
        except BaseException:
            if budget is not None:
                budget.release()
            if receipt is not None:
                receipt.release()
            raise

        recorded = False
        async for event in _metered(provider.stream, model, context, opts, budget, receipt):
            record_activity("provider_data")
            if not recorded:
                final = _extract_final(event)
                if final is not None:
                    recorded = True
                    if receipt is not None:
                        receipt.settle(final)
                    elif budget is not None:
                        budget.settle(model, final, opts)
                    else:
                        _record_usage(model, final, opts)
                elif receipt is not None:
                    _observe_usage(receipt, event)
            yield event


async def complete(
    model: Model,
    context: Context,
    options: StreamOptions | None = None,
) -> AssistantMessage:
    """
    Get a complete response with provider-specific options.
    Mirrors complete() from TypeScript.
    """
    final_message: AssistantMessage | None = None

    async for event in stream(model, context, options):
        final_message = _extract_final(event) or final_message

    if final_message is None:
        raise RuntimeError("Stream completed without a final message")

    return final_message


async def _metered(stream_fn, model: Model, context, opts, budget, receipt=None):
    """Drive the provider stream, marking the reservation started around I/O.

    Failures while constructing the provider iterator release a reservation.
    Once ``start`` succeeds, any failure or cancellation conservatively keeps
    exposure held because the request may already have reached the provider.
    """
    try:
        # An opaque provider may perform I/O while constructing its iterator.
        # Once invoked, absence of a receipt cannot prove the request was free.
        if receipt is not None:
            receipt.start()
        events = stream_fn(model, context, opts)
        if budget is not None and receipt is None:
            budget.start()
    except BaseException:
        if budget is not None:
            budget.release()
        if receipt is not None:
            receipt.release()
        raise

    try:
        async for event in events:
            yield event
    except BaseException:
        import asyncio
        from ..utils.event_stream import close_stream
        task = asyncio.current_task()
        stopping = bool(task and task.cancelling()) or bool(opts.signal and opts.signal.is_set())
        await close_stream(events, timeout=0.5 if stopping else None)
        raise


def _record_usage(model: Model, final, options) -> None:
    """Single metering chokepoint: every stream()/stream_simple() ends here,
    so every LLM call this module serves gets recorded. Best-effort — a
    metering failure must never surface to the caller. The call source
    (chat / compaction / memory / …) is read from the contextvar set by
    the caller's ``usage_scope(...)``; session_id comes off the options.
    """
    if final is None:
        return
    try:
        from openprogram.models.usage import record_message
        session_id = getattr(options, "session_id", None) if options else None
        record_message(model, final, session_id=session_id)
    except Exception:
        # Metering must never fail the turn, but the usage row is lost.
        _log.warning(
            "usage not recorded for %s (session %s)",
            getattr(model, "id", model),
            getattr(options, "session_id", None) if options else None,
            exc_info=True)


def _observe_usage(receipt, event):
    partial = event.get("partial") if isinstance(event, dict) else getattr(event, "partial", None)
    if isinstance(partial, dict):
        partial = AssistantMessage.model_validate(partial)
    if isinstance(partial, AssistantMessage):
        receipt.observe(partial)


def _extract_final(event) -> AssistantMessage | None:
    """
    Pull the AssistantMessage out of a terminal event.
    Provider implementations sometimes yield dicts rather than BaseModel
    instances — normalize both shapes.
    """
    etype = event["type"] if isinstance(event, dict) else getattr(event, "type", None)
    if etype == "done":
        payload = event["message"] if isinstance(event, dict) else event.message
    elif etype == "error":
        payload = event["error"] if isinstance(event, dict) else event.error
    else:
        return None

    if isinstance(payload, AssistantMessage):
        return payload
    if isinstance(payload, dict):
        return AssistantMessage.model_validate(payload)
    return payload
