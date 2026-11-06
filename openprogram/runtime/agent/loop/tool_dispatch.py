"""Tool dispatch: resolve, gate, execute and record the tool calls of one assistant message."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from openprogram.models.providers.types import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
)
from openprogram.models.providers.utils.event_stream import EventStream
from openprogram.models.providers.utils.validation import validate_tool_arguments

from openprogram.runtime.events import emit_safe, get_event_bus, make_event
from openprogram.runtime.events import ToolGateDenied, decide_tool_gate
from openprogram.runtime.agent.loop.types import (
    AgentEvent,
    AgentEventMessageEnd,
    AgentEventMessageStart,
    AgentEventToolEnd,
    AgentEventToolStart,
    AgentEventToolUpdate,
    AgentMessage,
)
from openprogram.models.providers.types import AgentTool, AgentToolResult

from openprogram.runtime.agent.loop.guards import _SafePointStop
from openprogram.runtime.agent.loop.message_context import _durable_message
from openprogram.runtime.agent.loop.lifecycle import (
    _job_operation_timeout,
    _record_job_activity,
)


# In-flight tool executions, keyed by tool_call_id. Read by the worker's
# GET /api/running so the Running panel can show what the agent is
# executing right now (bash commands, code runs, sub-agents, …).
import threading as _threading
import logging

_log = logging.getLogger(__name__)

RUNNING_TOOL_CALLS: dict[str, dict] = {}
RUNNING_TOOL_CALLS_LOCK = _threading.Lock()


def _attach_nested_agents_md(tool_call: Any, result: AgentToolResult) -> AgentToolResult:
    """Append the AGENTS.md files a file tool just reached — below the
    working directory or in another project — once per session."""
    if result.is_error:
        return result
    try:
        from openprogram.runtime.context import agents_md
        from openprogram.runtime.events.bus import _context_metadata
        text = agents_md.nested_for(
            tool_call.name, tool_call.arguments,
            str(_context_metadata().get("session") or ""))
    except Exception:
        return result
    if not text:
        return result
    return result.model_copy(update={
        "content": [*(result.content or []), TextContent(text="\n\n" + text)]})


def _rewrite_tool_result(tool_call: Any, result: AgentToolResult) -> AgentToolResult:
    """Let ``tool.result`` rewriters (plugins) change the text the model
    sees. Without a rewriter the result passes through untouched; a
    rewritten text replaces the text blocks and keeps images and audio."""
    from openprogram.programs._authoring import guides
    result = guides.attach(tool_call.name, tool_call.arguments, result)
    result = _attach_nested_agents_md(tool_call, result)
    bus = get_event_bus()
    if not bus.has_transforms("tool.result"):
        return result
    text = "".join(
        c.text for c in (result.content or [])
        if hasattr(c, "text") and isinstance(c.text, str)
    )
    event = make_event("tool.result", "tool", {
        "tool": tool_call.name, "tool_call_id": tool_call.id,
        "args": tool_call.arguments, "is_error": result.is_error,
    })
    rewritten = bus.emit_transform(event, text)
    if not isinstance(rewritten, str) or rewritten == text:
        return result
    others = [c for c in (result.content or []) if not isinstance(c, TextContent)]
    return result.model_copy(update={"content": [TextContent(text=rewritten), *others]})


def _tool_call_label(name: str, args: Any) -> str:
    """Human-readable one-liner for a tool call (UI display only)."""
    if isinstance(args, dict):
        for key in ("description", "command", "prompt", "query", "path"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:200]
    return name


class _SkipExecute(Exception):
    """Internal: repeat-fail trip already built a tool result."""


def _tool_repeat_key(name: str, args: Any) -> str:
    from openprogram.runtime.agent.loop.failure_policy import repeat_key
    return repeat_key(name, args)


_TOOL_NAME_ALIASES = {"Bash": "bash", "Read": "read", "ToolSearch": "tool_search"}


def _resolve_called_tool(tools: list[AgentTool] | None, call: ToolCall) -> tuple[AgentTool | None, dict]:
    """Resolve observed Claude spellings only within the turn's allowed tools."""
    available = {tool.name: tool for tool in (tools or [])}
    tool = available.get(call.name)
    if tool is None:
        tool = available.get(_TOOL_NAME_ALIASES.get(call.name, ""))
    args = dict(call.arguments)
    if tool is not None and tool.name == "tool_search":
        if call.name == "ToolSearch" and "query" in args and "select" not in args:
            args["select"] = args.pop("query")
        if args.get("max_results", object()) is None:
            args.pop("max_results")
    return tool, args


async def _execute_tool_calls(
    tools: list[AgentTool] | None,
    assistant_message: AssistantMessage,
    cancel_event: asyncio.Event | None,
    ev_stream: EventStream[AgentEvent, list[AgentMessage]],
    get_steering_messages: Any | None = None,
    repeat_failures: dict[str, int] | None = None,
    safe_point_hook: Any | None = None,
    *,
    start_index: int = 0,
    round_id: str | None = None,
) -> dict[str, Any]:
    """
    Execute tool calls from an assistant message.
    Mirrors executeToolCalls() in TypeScript.
    """
    from openprogram.runtime.agent.durable_steps import FunctionSuspended

    tool_calls = [c for c in assistant_message.content if isinstance(c, ToolCall)]
    results: list[ToolResultMessage] = []
    steering_messages: list[AgentMessage] | None = None
    stop_at_safe_point = False
    if repeat_failures is None:
        repeat_failures = {}

    # This dispatcher executes the list serially. It deliberately emits no
    # parallel group; a future concurrent dispatcher must provide an explicit
    # group id instead of making the UI infer concurrency from adjacency.
    import hashlib
    if round_id is None:
        round_id = "msg_" + hashlib.sha256(
            json.dumps(
                _durable_message(assistant_message),
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:16]

    def _occurrence_id(index: int, call: ToolCall) -> str:
        payload = {
            "round": round_id,
            "index": index,
            "tool_call_id": str(call.id),
            "tool_name": call.name,
            "arguments": call.arguments,
        }
        return "occ_" + hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()[:24]

    from openprogram.runtime.context.cache_aware_microcompact import increment_tool_calls
    increment_tool_calls(len(tool_calls))

    for index, tool_call in enumerate(tool_calls[start_index:], start=start_index):
        tool, call_args = _resolve_called_tool(tools, tool_call)
        occurrence_id = _occurrence_id(index, tool_call)
        dag_expose = getattr(tool, "_dag_expose", None) or "full"
        from openprogram.models.providers.types import Tool as AiTool
        validated_args = call_args
        validation_error = None
        if tool is not None:
            try:
                validated_args = validate_tool_arguments(AiTool(
                    name=tool.name, description=tool.description, parameters=tool.parameters,
                ), tool_call.model_copy(update={"arguments": call_args}))
            except Exception as exc:
                validation_error = exc
        fail_key = _tool_repeat_key(tool_call.name, validated_args)
        streak = repeat_failures.get(fail_key, 0)

        ev_stream.push(AgentEventToolStart(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            args=tool_call.arguments,
            occurrence_id=occurrence_id,
            expose=dag_expose,
        ))
        preflight = getattr(tool, "_permission_preflight", None)
        if callable(preflight) and streak < 2 and validation_error is None:
            import hashlib
            operation_id = hashlib.sha256(json.dumps(
                _durable_message(assistant_message), sort_keys=True, ensure_ascii=False,
            ).encode("utf-8")).hexdigest()
            await preflight(tool_call.id, validated_args, operation_id=operation_id)
        if safe_point_hook is not None:
            interaction_manifest = getattr(tool, "_interaction_manifest", None)
            pre_wait = (
                interaction_manifest(tool_call.id, validated_args)
                if callable(interaction_manifest) and validation_error is None else None
            )
            safe_payload = {
                "tool_call_id": str(tool_call.id), "tool_name": tool_call.name,
                "arguments": validated_args, "next_tool_index": index,
                "pre_wait": pre_wait,
            }
            stop_at_safe_point = bool(await safe_point_hook("tool.before", safe_payload))
            if stop_at_safe_point:
                break
            if tool is not None:
                object.__setattr__(
                    tool, "_preapproved_wait_id",
                    safe_payload.get("preapproved_wait_id"),
                )

        # 事件层：tool.before 一份事件，观察（异步总线）+ 问询（同步 gate）共用。
        # plugin 的 tool.before handler 就是 gate 订阅者（plugins/hooks.py）。
        before_ev = make_event("tool.before", "agent",
                               {"tool": tool_call.name,
                                "tool_call_id": tool_call.id,
                                "args": tool_call.arguments})
        get_event_bus().emit(before_ev)  # never raises: handlers are isolated
        gate_denial = decide_tool_gate(before_ev)

        # session/execution 由执行控制面的 contextvar 提供：session_id 让
        # /api/running 能按会话分组和跳转，execution_id 区分前台轮次和后台分支。
        from openprogram.runtime.execution.run_control import (
            get_current_execution_id, get_current_session_id,
        )
        with RUNNING_TOOL_CALLS_LOCK:
            RUNNING_TOOL_CALLS[tool_call.id] = {
                "tool_name": tool_call.name,
                "label": _tool_call_label(tool_call.name, tool_call.arguments),
                "started_at": time.time(),
                "session_id": get_current_session_id(),
                "execution_id": get_current_execution_id(),
            }

        result: AgentToolResult
        skipped_repeat = streak >= 2
        from openprogram.runtime.permissions.execution import ToolExecution, current_execution, mark_started

        async def notify_started():
            if safe_point_hook is not None:
                if await safe_point_hook("tool.started", {"tool_call_id": str(tool_call.id)}):
                    raise _SafePointStop()

        execution = ToolExecution(notify_started)
        if skipped_repeat:
            n = streak + 1
            from openprogram.runtime.agent.loop.failure_policy import record_failure
            record_failure(repeat_failures, fail_key, n)
            result = AgentToolResult(
                content=[TextContent(
                    type="text",
                    text=(
                        f"你已连续 {n} 次重复同一失败调用，"
                        "请改变方法或向用户说明阻碍"
                    ),
                )],
                details={},
                is_error=True,
            )
        execution_token = current_execution.set(execution)
        occurrence_token = None
        identity_consumed_token = None
        try:
            if skipped_repeat:
                raise _SkipExecute()
            if gate_denial is not None:
                raise ToolGateDenied(f"Tool call blocked: {gate_denial}")
            if not tool:
                raise ValueError(f"Tool {tool_call.name} not found")

            if validation_error is not None:
                raise validation_error

            def on_update(partial_result: AgentToolResult) -> None:
                _record_job_activity("tool_progress")
                ev_stream.push(AgentEventToolUpdate(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    args=tool_call.arguments,
                    partial_result=partial_result,
                ))

            if not getattr(tool, "_permission_managed", False):
                await mark_started()
            _record_job_activity("operation_start")
            timeout = _job_operation_timeout(None)
            preapproved_wait_id = getattr(tool, "_preapproved_wait_id", None)
            try:
                from openprogram.programs._host.runtime import (
                    _current_tool_call_occurrence_id,
                    _tool_call_identity_consumed,
                )

                occurrence_token = _current_tool_call_occurrence_id.set(occurrence_id)
                identity_consumed_token = _tool_call_identity_consumed.set(False)
            except Exception:
                occurrence_token = None
            if preapproved_wait_id:
                from openprogram.runtime.agent.engine_link import preapproved_wait
                with preapproved_wait(preapproved_wait_id):
                    operation = tool.execute(
                        tool_call.id, validated_args, cancel_event, on_update,
                    )
                    result = (
                        await operation
                        if timeout is None
                        else await asyncio.wait_for(operation, timeout=timeout)
                    )
            else:
                operation = tool.execute(
                    tool_call.id, validated_args, cancel_event, on_update,
                )
                result = (
                    await operation
                    if timeout is None
                    else await asyncio.wait_for(operation, timeout=timeout)
                )
        except _SafePointStop:
            stop_at_safe_point = True
            break
        except FunctionSuspended:
            if safe_point_hook is None:
                raise
            stop_at_safe_point = bool(await safe_point_hook("tool.suspended", {
                "tool_call_id": str(tool_call.id), "tool_name": tool_call.name,
                "next_tool_index": index, "repeat_failures": dict(repeat_failures),
                "tool_call_ids": [str(call.id) for call in tool_calls],
            }))
            if not stop_at_safe_point:
                raise
            break
        except _SkipExecute:
            pass
        except Exception as e:
            result = AgentToolResult(
                content=[TextContent(type="text", text=str(e))],
                details={},
                is_error=True,
            )
        except BaseException as e:
            # User-triggered cancel (openprogram.runtime.agent.call_state.CancelledError
            # is a BaseException so user-written `except Exception` inside tool bodies
            # cannot swallow it). Push a tool_end event so the UI sees the call
            # closed, then re-raise to abort the agent loop. The outer _run handler
            # ends the event stream gracefully so the chat dispatcher unblocks and
            # `running_task` is cleared — without this the stop button keeps showing
            # because the asyncio Task is killed by an "unretrieved" BaseException
            # and the stream never terminates.
            result = AgentToolResult(
                content=[TextContent(type="text", text=f"Cancelled: {e}")],
                details={},
                is_error=True,
            )
            ev_stream.push(AgentEventToolEnd(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                result=result,
                is_error=True,
                outcome="cancelled",
                occurrence_id=occurrence_id,
                expose=dag_expose,
            ))
            raise
        finally:
            if occurrence_token is not None:
                try:
                    from openprogram.programs._host.runtime import _current_tool_call_occurrence_id

                    _current_tool_call_occurrence_id.reset(occurrence_token)
                except (ValueError, RuntimeError):
                    # ContextVar.reset raises ValueError for a token from another
                    # context and RuntimeError for one already spent.
                    _log.debug("occurrence id token already spent or foreign", exc_info=True)
            if identity_consumed_token is not None:
                try:
                    from openprogram.programs._host.runtime import _tool_call_identity_consumed

                    _tool_call_identity_consumed.reset(identity_consumed_token)
                except (ValueError, RuntimeError):
                    # ContextVar.reset raises ValueError for a token from another
                    # context and RuntimeError for one already spent.
                    _log.debug("identity-consumed token already spent or foreign", exc_info=True)
            current_execution.reset(execution_token)
            with RUNNING_TOOL_CALLS_LOCK:
                RUNNING_TOOL_CALLS.pop(tool_call.id, None)

        outcome = "not_started" if not execution.started else ("failed" if result.is_error else "completed")
        result = _rewrite_tool_result(tool_call, result)
        if not skipped_repeat:
            if result.is_error and not execution.automatic_refusal:
                from openprogram.runtime.agent.loop.failure_policy import record_failure
                record_failure(repeat_failures, fail_key, streak + 1)
            else:
                repeat_failures.pop(fail_key, None)

        ev_stream.push(AgentEventToolEnd(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            result=result,
            is_error=result.is_error,
            outcome=outcome,
            occurrence_id=occurrence_id,
            expose=dag_expose,
        ))
        emit_safe("tool.after", "tool", {
            "tool": tool_call.name,
            "tool_call_id": tool_call.id,
            "is_error": result.is_error,
            # Only the text channel of the result — binary attachments
            # can be huge and rarely useful for subscribers.
            "result_text": "".join(
                c.text for c in (result.content or [])
                if hasattr(c, "text") and isinstance(c.text, str)
            ),
        })

        tool_result_msg = ToolResultMessage(
            role="toolResult",
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            content=result.content,
            details=result.details,
            is_error=result.is_error,
            timestamp=int(time.time() * 1000),
        )
        if safe_point_hook is not None:
            stop_at_safe_point = bool(await safe_point_hook("tool.after", {
                "tool_call_id": str(tool_call.id), "tool_name": tool_call.name,
                "result": _durable_message(tool_result_msg),
                "is_error": bool(result.is_error),
                "outcome": outcome, "execution_started": execution.started,
                "next_tool_index": index + 1,
                "repeat_failures": dict(repeat_failures),
                "tool_call_ids": [str(call.id) for call in tool_calls],
            }))
        results.append(tool_result_msg)
        ev_stream.push(AgentEventMessageStart(message=tool_result_msg))
        ev_stream.push(AgentEventMessageEnd(message=tool_result_msg))

        if stop_at_safe_point:
            break

    # Finish the already-issued tool batch before adding input to the next
    # model decision. Steering does not cancel or fabricate skipped tool results.
    # A pause owns its checkpoint; leave its pending input for continuation.
    if not stop_at_safe_point and get_steering_messages:
        steering_messages = await get_steering_messages() or None

    return {
        "tool_results": results, "steering_messages": steering_messages,
        "stop_at_safe_point": stop_at_safe_point,
    }
