"""One provider response: stream the assistant message, steer preemption and provider failover."""
from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import replace
from typing import Any

from openprogram.models.providers.types import (
    AssistantMessage,
    Context,
    Tool,
    ToolCall,
)
from openprogram.models.providers.utils.event_stream import EventStream

from openprogram.runtime.events import emit_safe
from openprogram.runtime.agent.loop.types import (
    AgentContext,
    AgentEvent,
    AgentEventMessageEnd,
    AgentEventMessageStart,
    AgentEventMessageUpdate,
    AgentLoopConfig,
    AgentMessage,
    StreamFn,
)

from openprogram.runtime.agent.loop.guards import (
    RepetitiveOutputError,
    _RepeatedTextGuard,
    _SafePointStop,
    _SteeredResponse,
)
from openprogram.runtime.agent.loop.message_context import (
    _durable_message,
    _inject_memory_prefetch,
    _latest_user_text,
    memory_prefetch_enabled,
)
from openprogram.runtime.agent.loop.lifecycle import (
    _job_operation_timeout,
    _record_job_activity,
)
import logging

_log = logging.getLogger(__name__)


def _instant_steer_enabled() -> bool:
    """``execution.instant_steer`` (default on): a steer preempts the response
    being generated instead of waiting for it to finish (Codex's
    ``instant_interrupt``). Read once per provider response."""
    try:
        from openprogram.state.config import read_config

        execution = read_config().get("execution", {})
        return not (isinstance(execution, dict) and execution.get("instant_steer") is False)
    except Exception:
        return True


async def _cancel_response_stream(response_stream: Any, iterator: Any, *, cleanup_timeout: float | None = None) -> None:
    """Stop a discarded provider response before starting its recovery."""
    from openprogram.models.providers.utils.event_stream import close_stream
    await close_stream(response_stream, iterator, timeout=cleanup_timeout)


async def _stream_assistant_response(
    context: AgentContext,
    config: AgentLoopConfig,
    cancel_event: asyncio.Event | None,
    ev_stream: EventStream[AgentEvent, list[AgentMessage]],
    stream_fn: StreamFn | None,
    structured_plan: Any | None = None,
    provider_snapshot: Any | None = None,
    output_attempt: int | None = None,
) -> AssistantMessage | _SteeredResponse:
    """
    Stream an assistant response from the LLM.
    Mirrors streamAssistantResponse() in TypeScript.
    """
    messages = context.messages

    # Apply context transform if configured
    if config.transform_context:
        messages = await config.transform_context(messages, cancel_event)

    # Convert to LLM-compatible messages
    convert = config.convert_to_llm
    if inspect.iscoroutinefunction(convert):
        llm_messages = await convert(messages)
    else:
        result = convert(messages)
        if inspect.isawaitable(result):
            llm_messages = await result
        else:
            llm_messages = result
    from openprogram.programs._authoring import guides
    guides.observe_request(llm_messages)

    # Per-turn memory prefetch — extract the latest user message and ask the
    # memory subsystem for relevant snippets. The result is already fenced as
    # <memory-context>; it renders as a PREFIX BLOCK INSIDE the current user
    # message (dag/overview.md §7), never on the system prompt. Prefetch
    # changes with every new user input, so appending it to the system prompt
    # invalidated the provider's cached prefix for the ENTIRE history on every
    # turn — the single largest source of avoidable input cost. In the user
    # turn it only ever invalidates the tail it sits in.
    prefetch_block = context.memory_prefetch
    if prefetch_block is None and not memory_prefetch_enabled.get():
        prefetch_block = ""
    if prefetch_block is None:
        prefetch_block = ""
        latest_user_text = _latest_user_text(messages)
        if latest_user_text:
            try:
                from openprogram.state.memory import get_backend
                prefetch_block = get_backend().search(latest_user_text)
            except Exception as exc:
                from openprogram.state.memory.policy import require_or_empty
                require_or_empty(exc)
                prefetch_block = ""

    from openprogram.state.memory.policy import current as _memory_policy, allowed as _memory_allowed
    if _memory_policy() is not None and not _memory_allowed():
        prefetch_block = ""
    sys_prompt = context.system_prompt or None
    if structured_plan is not None and structured_plan.mode == "prompt":
        from openprogram.models.providers.structured_output import build_prompt_fallback

        instruction = build_prompt_fallback(config.response_format)
        sys_prompt = f"{sys_prompt}\n\n{instruction}" if sys_prompt else instruction
    if prefetch_block:
        _inject_memory_prefetch(llm_messages, prefetch_block)

    # Build LLM context
    # Use the resolved tools and the turn's membership set, including tools
    # explicitly promoted by tool_search since the previous provider call.
    from openprogram.programs import split_tools_for_dispatch
    _provider_tools, _ = split_tools_for_dispatch(
        [tool for tool in (context.tools or [])
         if not callable(getattr(tool, "_permission_visible", None)) or tool._permission_visible()]
    )
    try:
        from openprogram.runtime.context.session_db import default_db
        from openprogram.runtime.context.tool_snapshot_node import record_tool_snapshot

        record_tool_snapshot(default_db(), config.session_id, list(context.tools or []))
    except Exception:
        # The snapshot is a record for replay; the provider call proceeds without it.
        _log.warning("tool snapshot not recorded for session %s", config.session_id, exc_info=True)
    if structured_plan is not None and structured_plan.mode == "tool":
        _provider_tools = [
            *_provider_tools,
            Tool(
                name=structured_plan.submit_tool_name,
                description="Submit the final response matching the required schema.",
                parameters=structured_plan.provider_schema,
            ),
        ]
    llm_context = Context(
        system_prompt=sys_prompt,
        messages=llm_messages,
        tools=_provider_tools,
    )

    fn = stream_fn
    from openprogram.models.providers.catalog.api_registry import resolve_api_provider_snapshot

    if provider_snapshot is None:
        provider_snapshot = resolve_api_provider_snapshot(config.model)
    dispatch_snapshots = {id(config.model): provider_snapshot}
    dispatch_models = [config.model]

    # Provider/model failover — OFF by default. A user-picked model that
    # 429s must surface that error. OPENPROGRAM_FALLBACK_MODELS=same-provider
    # restores the old same-provider chain.
    if stream_fn is None:
        from openprogram.models.providers.streaming.stream import stream_simple_with_provider

        async def snapshot_stream(candidate, candidate_context, candidate_options):
            snapshot = dispatch_snapshots.get(id(candidate))
            update = {"max_tokens": config.max_tokens}
            # The provider search was resolved against the primary model. A
            # failover candidate without the capability gets no search
            # option (the local tool is not restored mid-turn).
            if (
                getattr(candidate_options, "web_search", None)
                and candidate is not config.model
                and not getattr(snapshot, "supports_web_search", False)
            ):
                update["web_search"] = None
            candidate_options = candidate_options.model_copy(update=update)
            provider = snapshot.provider if snapshot is not None else None
            # Failover can change the input window and output cap. Validate
            # each actual candidate, not only the initial model.
            candidate_context = await context._request_compactor.prepare(
                candidate_context, candidate, candidate_options, get_api_key=config.get_api_key)
            async for event in stream_simple_with_provider(
                provider,
                candidate,
                candidate_context,
                candidate_options,
                get_api_key=config.get_api_key,
            ):
                yield event

        fn = snapshot_stream
        try:
            from openprogram.models.providers.catalog.api_registry import resolve_api_provider_snapshot
            from openprogram.models.providers.utils.failover import (
                resolve_fallback_models,
                failover_stream_fn,
            )
            _fallbacks = resolve_fallback_models(config.model)
            if structured_plan is not None:
                from openprogram.models.providers.structured_output import negotiate_structured_output

                compatible = []
                for fallback in _fallbacks:
                    fallback_snapshot = resolve_api_provider_snapshot(fallback)
                    if fallback_snapshot.provider is None:
                        continue
                    try:
                        fallback_plan = negotiate_structured_output(
                            fallback,
                            fallback_snapshot.structured_output,
                            config.response_format,
                            list(context.tools or []),
                            tool_choice=config.tool_choice,
                            parallel_tool_calls=config.parallel_tool_calls,
                        )
                    except Exception:
                        continue
                    if (
                        fallback_plan.mode == structured_plan.mode
                        and fallback_plan.provider_schema == structured_plan.provider_schema
                    ):
                        compatible.append(fallback)
                        dispatch_snapshots[id(fallback)] = fallback_snapshot
                _fallbacks = compatible
            else:
                available = []
                for fallback in _fallbacks:
                    fallback_snapshot = resolve_api_provider_snapshot(fallback)
                    if fallback_snapshot.provider is None:
                        continue
                    available.append(fallback)
                    dispatch_snapshots[id(fallback)] = fallback_snapshot
                _fallbacks = available
            dispatch_models.extend(_fallbacks)
            if _fallbacks:
                fn = failover_stream_fn(fn, _fallbacks)
                import os as _os

                if _os.environ.get("OPENPROGRAM_DEBUG_PROVIDER", "").strip().lower() \
                        in ("1", "true", "yes"):
                    _log.info(
                        "provider failover candidates=%s",
                        ",".join(
                            f"{getattr(item, 'provider', '?')}/{getattr(item, 'id', '?')}"
                            for item in _fallbacks
                        ),
                    )
        except Exception as exc:
            import os as _os

            if _os.environ.get("OPENPROGRAM_DEBUG_PROVIDER", "").strip().lower() \
                    in ("1", "true", "yes"):
                _log.info("provider failover setup failed: %s: %s", type(exc).__name__, exc)

    # The effect contract is established before the first provider dispatch.
    # A stable key is safe only when every candidate that can actually receive
    # this request advertises support for it. This remains conservative for an
    # explicit cross-provider chain with mixed capabilities: no candidate gets
    # a key, and the effect is recorded as nonrepeatable.
    provider_supports_idempotency_key = bool(
        dispatch_models
        and all(
            snapshot is not None and snapshot.supports_idempotency_key
            for snapshot in (
                dispatch_snapshots.get(id(candidate)) for candidate in dispatch_models
            )
        )
    )

    assert fn is not None

    # Request redaction — OFF by default. Outermost, so one vault covers
    # every failover candidate and the reply is restored once.
    from openprogram.models.providers.utils.redaction import redacting_stream_fn, redaction_enabled

    if redaction_enabled():
        fn = redacting_stream_fn(fn)

    # Resolve API key
    resolved_api_key = config.api_key
    if stream_fn is not None and config.get_api_key:
        key_result = config.get_api_key(config.model.provider)
        if inspect.isawaitable(key_result):
            key_result = await key_result
        resolved_api_key = key_result or resolved_api_key

    provider_response_format = None
    if structured_plan is not None and structured_plan.mode == "native":
        provider_response_format = replace(
            config.response_format,
            schema=structured_plan.provider_schema,
        )

    from openprogram.models.providers import SimpleStreamOptions
    from openprogram.runtime.context.request_compaction import RequestCompactor
    # ``thinking_levels`` is the model's request-body capability contract.
    # A stale session/agent preference can outlive a model switch, so never
    # forward it to a model whose list is empty: OpenAI-compatible upstreams
    # commonly reject an unsupported ``reasoning_effort`` with HTTP 400.
    from openprogram.models.providers.settings.thinking_spec import normalize_reasoning_level

    reasoning = normalize_reasoning_level(config.model, config.reasoning)
    stream_opts = SimpleStreamOptions(
        reasoning=reasoning,
        thinking_budgets=config.thinking_budgets,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        signal=cancel_event,
        api_key=resolved_api_key,
        transport=config.transport,
        cache_retention=config.cache_retention,
        session_id=config.session_id,
        on_payload=config.on_payload,
        headers=config.headers,
        max_retry_delay_ms=config.max_retry_delay_ms,
        metadata=config.metadata,
        service_tier=config.service_tier,
        tool_choice=config.tool_choice,
        parallel_tool_calls=(
            False
            if structured_plan is not None and structured_plan.mode == "tool"
            else config.parallel_tool_calls
        ),
        web_search=config.web_search,
        response_format=provider_response_format,
        supports_idempotency_key=provider_supports_idempotency_key,
    )

    # Shared by outer chat and Runtime.exec()/llm()/agent() tool continuations.
    # Prepare after dynamic memory, tools, and response-format instructions.
    if context._request_compactor is None:
        context._request_compactor = RequestCompactor()
    llm_context = await context._request_compactor.prepare(llm_context, config.model, stream_opts, get_api_key=config.get_api_key)

    # Estimate the dispatched request, before its in-flight assistant/tool
    # messages are coalesced into the persisted conversation graph.
    from openprogram.runtime.context.budget import default_allocator
    from openprogram.runtime.context.tokens import real_context_window
    request_input_estimate = default_allocator.allocate(
        context_window=real_context_window(config.model),
        system_prompt=llm_context.system_prompt or "",
        history=llm_context.messages,
        tools=llm_context.tools or [],
    ).input_used

    partial_message: AssistantMessage | None = None
    added_partial = False
    repetition_guard = _RepeatedTextGuard() if context.tools else None

    if config.safe_point_hook is not None:
        from openprogram.runtime.agent.engine_link import runtime_contract_snapshot

        resolved_snapshot = context.runtime_contract
        if resolved_snapshot is None:
            # Direct agent_loop callers do not have a TurnRequest.  Keep this
            # fallback only for non-durable callers; production continuation
            # always supplies the resolved request contract from the driver.
            resolved_snapshot = runtime_contract_snapshot(
                model=config.model,
                system_prompt=context.system_prompt,
                tools=context.tools,
                request=None,
                structured_output=config.response_format,
            )
        provider_payload = {
            "resolved_snapshot": resolved_snapshot,
            "supports_idempotency_key": provider_supports_idempotency_key,
            "dispatch_candidates": [
                {
                    "api": getattr(candidate, "api", None),
                    "provider": getattr(candidate, "provider", None),
                    "model": getattr(candidate, "id", None),
                    "supports_idempotency_key": bool(
                        snapshot is not None and snapshot.supports_idempotency_key
                    ),
                }
                for candidate in dispatch_models
                for snapshot in (dispatch_snapshots.get(id(candidate)),)
            ],
            "context": {
                "system_prompt": llm_context.system_prompt,
                "messages": [_durable_message(message) for message in llm_context.messages],
                "tools": [_durable_message(tool) for tool in (llm_context.tools or [])],
            },
        }
        if await config.safe_point_hook("provider.before", provider_payload):
            raise _SafePointStop()
        if provider_payload.get("supports_idempotency_key") is True:
            stream_opts.idempotency_key = provider_payload.get("idempotency_key")
        else:
            stream_opts.idempotency_key = None
    _record_job_activity("operation_start")
    from openprogram.runtime.agent.loop.provider_lifecycle import provider_response

    from openprogram.models.providers.utils.recovery import current_recovery
    recovery = current_recovery.get()
    receipt = recovery.started(
        provider=config.model.provider, model=config.model.id,
        max_tokens=stream_opts.max_tokens,
        output_limit_source="explicit" if config.max_tokens is not None else "model_capacity",
        reasoning=stream_opts.reasoning,
    ) if recovery is not None else None
    with provider_response(emit_safe) as response:
        response_stream = fn(config.model, llm_context, stream_opts)

        iterator = response_stream.__aiter__()
        next_steer_check = 0.0
        instant_steer = _instant_steer_enabled()
        while True:
            if structured_plan is not None and cancel_event and cancel_event.is_set():
                from openprogram.models.providers.utils.errors import ExecInterrupt

                raise ExecInterrupt("cancelled")
            timeout = _job_operation_timeout(None)
            try:
                # A separate read-only probe observes durable steer commands.
                # Only a closed provider response enters the existing safe point.
                # Tool calls still being written are preemptible too: their
                # durable effect is only planned at tool.before, after the
                # response closes, so an unfinished call is simply dropped.
                can_steer = (
                    instant_steer and config.safe_point_hook is not None
                    and structured_plan is None
                )
                if not can_steer:
                    event = (
                        await iterator.__anext__() if timeout is None
                        else await asyncio.wait_for(iterator.__anext__(), timeout=timeout)
                    )
                else:
                    next_event = asyncio.ensure_future(iterator.__anext__())
                    deadline = time.monotonic() + timeout if timeout is not None else None
                    interrupt = False
                    try:
                        while True:
                            now = time.monotonic()
                            if now >= next_steer_check:
                                probe = {}
                                await config.safe_point_hook("provider.poll", probe)
                                next_steer_check = time.monotonic() + 0.1
                                if probe.get("steer_pending"):
                                    interrupt = True
                                    break
                            if deadline is not None and now >= deadline:
                                raise asyncio.TimeoutError()
                            wait = max(0, next_steer_check - now)
                            if deadline is not None:
                                wait = min(wait, max(0, deadline - now))
                            ready, _ = await asyncio.wait({next_event}, timeout=wait)
                            if ready:
                                event = next_event.result()
                                break
                    finally:
                        if not next_event.done():
                            next_event.cancel()
                            ready, _ = await asyncio.wait({next_event}, timeout=0.5)
                            if not ready:
                                # Do not overlap a new request with an unclosed reader.
                                next_event.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
                                raise RuntimeError("Provider did not stop after stream interruption")
                        if next_event.done() and not next_event.cancelled():
                            next_event.exception()
                    if interrupt:
                        cleanup = asyncio.create_task(_cancel_response_stream(response_stream, iterator))
                        try:
                            closed, _ = await asyncio.wait({cleanup}, timeout=0.5)
                            if not closed:
                                raise RuntimeError("Provider cleanup did not finish after steering")
                            cleanup.result()
                        finally:
                            if not cleanup.done():
                                cleanup.cancel()
                            cleanup.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
                        message = (partial_message.model_copy(deep=True) if partial_message is not None else AssistantMessage(
                            content=[], api=config.model.api, provider=config.model.provider, model=config.model.id,
                        ))
                        # Calls the steer cut off were never dispatched; keep
                        # only the text and thinking the user already saw.
                        message.content = [
                            item for item in message.content if not isinstance(item, ToolCall)
                        ]
                        # Preserve the real response outcome so request projection
                        # drops incomplete reasoning signatures on continuation.
                        message.stop_reason = "aborted"
                        if added_partial:
                            context.messages[-1] = message
                        else:
                            context.messages.append(message)
                            ev_stream.push(AgentEventMessageStart(message=message))
                        ev_stream.push(AgentEventMessageEnd(message=message))
                        response.status = "completed"
                        return _SteeredResponse(message)
            except StopAsyncIteration:
                break
            except BaseException:
                await _cancel_response_stream(
                    response_stream, iterator,
                    cleanup_timeout=0.5 if cancel_event and cancel_event.is_set() else None,
                )
                raise
            _record_job_activity("provider_data")
            if structured_plan is not None and cancel_event and cancel_event.is_set():
                from openprogram.models.providers.utils.errors import ExecInterrupt

                raise ExecInterrupt("cancelled")
            if repetition_guard is not None and event.type in {
                "text_start",
                "thinking_start",
                "thinking_delta",
                "thinking_end",
                "toolcall_start",
                "toolcall_delta",
                "toolcall_end",
                "servertool_start",
                "servertool_end",
            }:
                # Text from separate blocks or across a thinking/tool-call
                # boundary is not one continuous response segment.
                repetition_guard.reset()
            if (
                repetition_guard is not None
                and event.type == "text_delta"
                and repetition_guard.observe(getattr(event, "delta", ""))
            ):
                await _cancel_response_stream(response_stream, iterator)
                if (
                    added_partial
                    and context.messages
                    and context.messages[-1] is partial_message
                ):
                    context.messages.pop()
                raise RepetitiveOutputError()
            if event.type == "start":
                partial_message = event.partial
                if structured_plan is None:
                    context.messages.append(partial_message)
                    added_partial = True
                ev_stream.push(AgentEventMessageStart(message=partial_message))

            elif event.type in (
                "text_start", "text_delta", "text_end",
                "thinking_start", "thinking_delta", "thinking_end",
                "toolcall_start", "toolcall_delta", "toolcall_end",
                # A provider-executed search (serverToolUse block). The
                # provider already ran it; it is forwarded, never executed.
                "servertool_start", "servertool_end",
            ):
                if partial_message is not None:
                    if output_attempt is not None and event.type in (
                        "text_start", "text_delta", "text_end",
                    ):
                        event = event.model_copy(update={"output_attempt": output_attempt})
                    partial_message = event.partial
                    if added_partial:
                        context.messages[-1] = partial_message
                    ev_stream.push(AgentEventMessageUpdate(
                        message=partial_message,
                        assistant_message_event=event,
                    ))

            elif event.type == "retry" and partial_message is not None:
                ev_stream.push(AgentEventMessageUpdate(
                    message=partial_message,
                    assistant_message_event=event,
                ))

            elif event.type in ("done", "error"):
                response.status = "completed" if event.type == "done" else (
                    "cancelled" if event.error.stop_reason == "aborted" else "failed"
                )
                final_message = event.message if event.type == "done" else event.error
                if final_message.usage.tokens_reported:
                    final_message.usage.request_input_estimate = request_input_estimate
                    if (final_message.model == config.model.id
                            and final_message.provider == config.model.provider):
                        context._request_compactor.note_usage(
                            config.model,
                            measured_input=(final_message.usage.input
                                            + final_message.usage.cache_read),
                            request_estimate=request_input_estimate,
                        )
                if receipt is not None:
                    receipt.update(stop_reason=final_message.stop_reason,
                                   usage=_durable_message(final_message.usage))
                if structured_plan is not None:
                    if partial_message is None:
                        ev_stream.push(AgentEventMessageStart(message=final_message))
                    return final_message
                if added_partial:
                    context.messages[-1] = final_message
                else:
                    context.messages.append(final_message)
                if not added_partial:
                    ev_stream.push(AgentEventMessageStart(message=final_message))
                ev_stream.push(AgentEventMessageEnd(message=final_message))
                return final_message

        response.exhausted = True
        if structured_plan is not None:
            from openprogram.models.providers.structured_output import (
                StructuredOutputGenerationError,
            )

            raise StructuredOutputGenerationError(
                "Structured output stream ended without a terminal event",
                code="incomplete",
                issues=[{"code": "incomplete", "message": "Stream ended without a terminal event", "path": ""}],
            )

        # Ordinary text mode preserves the legacy partial-message fallback.
        if partial_message:
            if cancel_event and cancel_event.is_set():
                response.status = "cancelled"
                raise RuntimeError("Request was aborted")
            return partial_message

        raise RuntimeError("Stream ended without a final message")
