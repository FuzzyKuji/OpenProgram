"""Agent-loop run stage — pipeline step 4 (dispatcher-split).

``run_loop_blocking`` builds the AgentContext (profile → tools → system
prompt → model), routes history through the context engine (snip +
auto-compact), kicks off ``agent_loop`` and drains its EventStream to
completion inside a fresh asyncio loop.

Re-exported by ``__init__.py`` as ``_run_loop_blocking`` — the seam
tests patch on the dispatcher package. The profile / model helpers are
also patched on the package (``dispatcher._load_agent_profile`` /
``dispatcher._resolve_model``), so this module reads them through the
package attribute at call time instead of freezing them with a
module-level from-import.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
from copy import deepcopy
from dataclasses import dataclass, field
import inspect
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Mapping, Optional, TYPE_CHECKING

from openprogram.runtime.conversation import plan_mode as _plan_mode
from openprogram.runtime.conversation.session_config import reasoning_from_config, SessionRunConfig
from openprogram.runtime.permissions.approval import (
    wrap_with_approval as _wrap_with_approval,
)
from openprogram.runtime.conversation.event_parsing import (
    agent_event_to_envelope as _agent_event_to_envelope,
    aiter_event_stream as _aiter_event_stream,
    extract_text as _extract_text,
    extract_usage as _extract_usage,
    shorten as _shorten,
)
from openprogram.runtime.conversation.model_tools import (
    log_resolved_tools as _log_resolved_tools,
    resolve_tools as _resolve_tools,
)
from openprogram.runtime.conversation.turn_runtime.runtime_attach import _wrap_agentic_runtime_block
from openprogram.runtime.conversation.checkpoint import runtime_contract_snapshot
from openprogram.models.providers.utils.http_client import shutdown_loop_clients as _shutdown_loop_clients
from openprogram.runtime.execution.agent_checkpoint import validate_runtime_contract
from openprogram.runtime.conversation.checkpoint import provider_context_from_effect

if TYPE_CHECKING:
    from openprogram.runtime.conversation.turn_runtime.types import EventCallback
    from openprogram.runtime.agent.turn_request import TurnRequest


def _undeferred(tool):
    from openprogram.programs._host.runtime import as_resident

    return as_resident(tool)

def _ordered_block_from_content(block: object) -> dict | None:
    """Map one provider content block onto the persisted ordered-card shape."""
    btype = getattr(block, "type", None)
    if btype == "text":
        text = getattr(block, "text", "") or ""
        if not text:
            return None
        ordered = {"type": "text", "text": text}
        from openprogram.runtime.agent.provider_search import text_citations
        citations = text_citations(block)
        if citations:
            ordered["citations"] = citations
        return ordered
    if btype == "serverToolUse":
        # A search the provider ran: shown and persisted like a tool card,
        # never executed here.
        from openprogram.runtime.agent.provider_search import server_tool_card
        card = server_tool_card(block)
        return card if card.get("tool_call_id") else None
    if btype == "thinking":
        text = getattr(block, "thinking", "") or ""
        return {"type": "thinking", "text": text} if text else None
    if btype == "toolCall":
        tool_id = getattr(block, "id", None)
        name = getattr(block, "name", None)
        args = getattr(block, "arguments", None)
        try:
            payload = json.dumps(args, default=str) if args is not None else None
        except (TypeError, ValueError):
            payload = None
        return {
            "type": "tool",
            "tool": name,
            "tool_call_id": tool_id,
            "input": payload,
        }
    return None


def _cards_are_suffix(haystack: list[dict], needle: list[dict]) -> bool:
    if not needle:
        return True
    if len(haystack) < len(needle):
        return False
    tail = haystack[-len(needle):]
    for left, right in zip(tail, needle):
        if left.get("type") != right.get("type"):
            return False
        if left.get("type") == "tool":
            if str(left.get("tool_call_id") or "") != str(right.get("tool_call_id") or ""):
                return False
        elif str(left.get("text") or "") != str(right.get("text") or ""):
            return False
    return True


def _seed_continuation_cards(
    continuation,
    *,
    ordered_blocks_out: list[dict] | None,
    tool_calls: list[dict],
    final_text_parts: list[str],
) -> set[str]:
    """Restore the full pre-pause trace, then current-decision fallback."""
    seen_tool_ids: set[str] = set()

    def _note_tool(tool_id: object, *, tool: object = None, result=None,
                   is_error=None, input_value=None) -> None:
        if not tool_id:
            return
        key = str(tool_id)
        existing = next(
            (row for row in tool_calls if row.get("tool_call_id") == key),
            None,
        )
        if existing is None:
            tool_calls.append({
                "id": key,
                "tool_call_id": key,
                "tool": tool,
                "result": result,
                "is_error": is_error,
                "input": input_value,
            })
        else:
            if tool is not None and not existing.get("tool"):
                existing["tool"] = tool
            if result is not None and existing.get("result") is None:
                existing["result"] = result
            if is_error is not None and existing.get("is_error") is None:
                existing["is_error"] = is_error
            if input_value is not None and existing.get("input") is None:
                existing["input"] = input_value
        seen_tool_ids.add(key)

    decision_cards: list[dict] = []
    for block in continuation.assistant_message.content:
        ordered = _ordered_block_from_content(block)
        if ordered is None:
            continue
        decision_cards.append(ordered)
        if ordered.get("type") == "text" and ordered.get("text"):
            final_text_parts.append(ordered["text"])
        if ordered.get("type") == "tool" and not ordered.get("provider_executed"):
            _note_tool(
                ordered.get("tool_call_id"),
                tool=ordered.get("tool"),
                input_value=ordered.get("input"),
            )

    display = tuple(getattr(continuation, "display", ()) or ())
    if display:
        for card in display:
            if not isinstance(card, Mapping):
                continue
            item = dict(card)
            kind = item.get("type")
            if ordered_blocks_out is not None:
                ordered_blocks_out.append(item)
            if kind == "tool" and not item.get("provider_executed"):
                _note_tool(
                    item.get("tool_call_id"),
                    tool=item.get("tool"),
                    result=item.get("result"),
                    is_error=item.get("is_error"),
                    input_value=item.get("input"),
                )
        if ordered_blocks_out is not None:
            overlap = 0
            for n in range(len(decision_cards), 0, -1):
                if _cards_are_suffix(ordered_blocks_out, decision_cards[:n]):
                    overlap = n
                    break
            present = {
                str(block.get("tool_call_id"))
                for block in ordered_blocks_out
                if block.get("type") == "tool" and block.get("tool_call_id")
            }
            for ordered in decision_cards[overlap:]:
                if (
                    ordered.get("type") == "tool"
                    and ordered.get("tool_call_id")
                    and str(ordered["tool_call_id"]) in present
                ):
                    continue
                ordered_blocks_out.append(dict(ordered))
        for result in continuation.tool_results:
            _note_tool(
                result.tool_call_id,
                tool=result.tool_name,
                result=_shorten(result),
                is_error=result.is_error,
            )
        return seen_tool_ids

    for ordered in decision_cards:
        if ordered_blocks_out is not None:
            ordered_blocks_out.append(ordered)
    for result in continuation.tool_results:
        _note_tool(
            result.tool_call_id,
            tool=result.tool_name,
            result=_shorten(result),
            is_error=result.is_error,
        )
        tool_id = str(result.tool_call_id or "")
        if (
            ordered_blocks_out is not None
            and tool_id
            and not any(
                block.get("type") == "tool" and block.get("tool_call_id") == tool_id
                for block in (ordered_blocks_out or [])
            )
        ):
            ordered_blocks_out.append({
                "type": "tool",
                "tool": result.tool_name,
                "tool_call_id": tool_id,
                "input": None,
            })
    return seen_tool_ids


_log = logging.getLogger(__name__)

def _configure_web_use_tools(tools, surface_context, *, enabled: bool | None = None,
                             tools_override=None):
    """Built-in browser Pages are a computer_use_agent target; while they exist the turn gets it.

    Without the browser application there are no Pages to operate. A turn whose
    tool list is given by name (an always-on check-in, a skill's allowed tools)
    gets it only when that list names it: a check-in is read-only, and the
    screen tool would wait on a system-access prompt nobody is there to answer.
    """
    from openprogram.runtime.conversation.surface_context import tool_enabled, web_use_available
    from openprogram.programs._host import services as _services

    current = [tool for tool in tools or [] if tool.name != "web_use"]
    if isinstance(tools_override, list) and "computer_use_agent" not in tools_override:
        return [tool for tool in current if tool.name != "computer_use_agent"], False
    if _services.lookup("browser") is None:
        return current, False
    if enabled is None:
        enabled = tool_enabled(surface_context) or (bool(current) and web_use_available(surface_context))
    if not enabled:
        return current, False

    from openprogram.programs import get_agent_tool

    screen_tool = next((tool for tool in current if tool.name == "computer_use_agent"), None)
    if screen_tool is None:
        screen_tool = get_agent_tool("computer_use_agent")
    current = [tool for tool in current if tool.name != "computer_use_agent"]
    if screen_tool is not None:
        current.append(screen_tool)
    return current, screen_tool is not None


def _saved_web_use(saved_runtime_contract: Mapping | None) -> bool | None:
    """Whether the checkpoint's turn could operate browser Pages, read from its tools."""
    if saved_runtime_contract is None:
        return None
    names = {tool.get("name") for tool in saved_runtime_contract.get("tools") or []
             if isinstance(tool, Mapping)}
    return bool(names & {"web_use", "computer_use_agent"})


def _retain_saved_contract_tools(tools, saved_runtime_contract: Mapping | None):
    """Keep the checkpoint's tool set. Extra live tools do not block resume."""
    if saved_runtime_contract is None:
        return tools
    saved = saved_runtime_contract.get("tools")
    if not isinstance(saved, list):
        return tools
    names = [
        item.get("name") for item in saved
        if isinstance(item, Mapping) and isinstance(item.get("name"), str) and item["name"]
    ]
    live = {tool.name: tool for tool in tools or []}
    return [live[name] for name in names if name in live]


def resolve_agent_runtime(
    req: "TurnRequest", *, assistant_msg_id: Optional[str] = None,
    on_event: Optional["EventCallback"] = None,
    saved_runtime_contract: Mapping | None = None,
):
    """Resolve the exact model, prompt, tools, and durable runtime contract."""
    from openprogram.runtime.conversation import turn_runtime as _dispatcher

    event_sink = on_event or (lambda _event: None)
    agent_profile = (
        deepcopy(req.profile_snapshot) if req.profile_snapshot is not None
        else _dispatcher._load_agent_profile(req.agent_id)
    )
    tools = _resolve_tools(agent_profile, req.tools_override, source=req.source)
    from openprogram.state.memory.policy import allowed as _memory_allowed
    from openprogram.programs.tools.knowledge.memory import MEMORY_TOOL_NAMES
    tools = [tool for tool in tools or [] if tool.name not in MEMORY_TOOL_NAMES or _memory_allowed(write=tool.name == "memory_update")]
    # Reports and handoffs belong to conversations whose Agent is always-on;
    # a sub-agent's turn there does not hand work over.
    always_on_only = {"always_on_report", "handoff"}
    if any(tool.name in always_on_only for tool in tools):
        from openprogram.runtime.conversation.always_on import agent_for_session
        if agent_for_session(req.session_id) is None:
            tools = [tool for tool in tools if tool.name not in always_on_only]
        elif not req.advance_head or req.spawned_from_session:
            tools = [tool for tool in tools if tool.name != "handoff"]
    # chat_send posts into the chat a channel turn came from; no other
    # source has one.
    from openprogram.programs.tools.interaction.chat_send import CHANNEL_SOURCES
    if req.source not in CHANNEL_SOURCES:
        tools = [tool for tool in tools or [] if tool.name != "chat_send"]
    # The goal Program is the Programs form's entry; agents use create_goal.
    tools = [tool for tool in tools or [] if tool.name != "goal"]
    # Page inventory is transient. Keep this turn's browser-tool selection
    # through reconnects; each actual browser action still validates access.
    saved_web_use = _saved_web_use(saved_runtime_contract)
    tools, web_use_enabled = _configure_web_use_tools(tools, req.surface_context, enabled=saved_web_use,
                                                      tools_override=req.tools_override)
    if req.source in {"self_update_verify", "self_update_diagnose", "self_update_repair"}:
        from openprogram.programs import apply_tool_policy

        tools = apply_tool_policy(tools or [], source=req.source)
        web_use_enabled = False
    tools = _retain_saved_contract_tools(tools, saved_runtime_contract)
    if req.goal_verification:
        from openprogram.programs.tools.planning.goal import verification
        from openprogram.runtime.execution.run_control import get_current_execution_id
        from openprogram.programs import _is_verifier_read_tool
        verification.require_candidate(req.session_id, vars(req), execution_id=get_current_execution_id())
        tools = [tool for tool in tools or [] if _is_verifier_read_tool(tool) and tool.name != "self_update_observe"]
        web_use_enabled = False
    if req.goal_verification or req.source in {"self_update_verify", "self_update_diagnose", "self_update_repair"}:
        # These stages cannot search for tools, so their pinned tools ship with full schemas.
        tools = [_undeferred(tool) for tool in tools or []]
    override = getattr(req, "model_override", None)
    if not override and getattr(req, "session_id", None):
        from openprogram.runtime.conversation.session_model import (
            ensure_session_chat_model,
            read_session_chat_model,
            override_string,
        )
        if req.profile_snapshot is not None:
            provider, model_id = read_session_chat_model(req.session_id)
        else:
            provider, model_id = ensure_session_chat_model(
                req.session_id, getattr(req, "agent_id", None),
            )
        override = override_string(provider, model_id)
        if override:
            req.model_override = override
    model = _dispatcher._resolve_model(agent_profile, override)
    _log.info(
        "turn model session=%r override=%r resolved=%s/%s api=%s",
        getattr(req, "session_id", None),
        override,
        getattr(model, "provider", None),
        getattr(model, "id", None),
        getattr(model, "api", None),
    )
    if "image" not in (model.input or []) and any(
        isinstance(attachment, dict) and attachment.get("type") == "image"
        and attachment.get("data") for attachment in (req.attachments or [])
    ):
        raise ValueError(
            "The selected model does not support image input. Choose a model that supports images."
        )
    # The Search switch follows the model: a provider with its own web search
    # runs it (request option, set by run_loop_blocking from this flag) and
    # the local web_search tool leaves this turn's tools; otherwise the local
    # tool stays. Resolved before the prompt and contract see the tools.
    from openprogram.runtime.agent.provider_search import (
        resolve_web_search,
        session_search_intent,
    )
    search_intent = session_search_intent(req.tools_override, agent_profile) and any(
        tool.name == "web_search" for tool in tools or []
    )
    web_search_option, tools = resolve_web_search(model, tools, search_intent)
    req._provider_web_search = bool(web_search_option)
    from openprogram.programs import install_allowed_tool_names
    install_allowed_tool_names({tool.name for tool in tools or []})
    _log_resolved_tools(req, tools)
    if tools:
        tools = [_wrap_with_approval(tool, req, event_sink) for tool in tools]
        if req.goal_verification:
            tools = [verification.wrap_read(tool, req) if tool.name == "read" else tool for tool in tools]
        if assistant_msg_id is not None:
            wrapped = []
            for tool in tools:
                if getattr(tool, "_is_agent_method", False):
                    wrapped.append(_wrap_agentic_runtime_block(
                        tool, req, event_sink, assistant_msg_id,
                    ))
                else:
                    wrapped.append(tool)
            tools = wrapped
    from openprogram.runtime.context.components import build_system_prompt
    saved_system_prompt = None if saved_runtime_contract is None else saved_runtime_contract["system_prompt"]
    # A continuation uses the prompt that produced its saved decision.
    # Memory, dates and project text may change while a human is deciding;
    # rebuilding them is neither necessary nor the context we will execute.
    recordable_prompt = saved_system_prompt if saved_system_prompt is not None else build_system_prompt(
        agent_profile, tools=tools,
        channel=req.source,
        additional_working_dirs=getattr(req, "additional_working_dirs", None),
        plan_mode=req.permission_mode == "plan" or _plan_mode.is_plan_mode(req.session_id),
    )
    system_prompt = recordable_prompt
    if saved_system_prompt is None and req.source != "agent_spawn":
        if req.goal_verification:
            system_prompt += verification.instructions(req.session_id, req)
        else:
            from openprogram.programs.tools.planning.goal.chat import instructions
            system_prompt += instructions(req.session_id)
    # This call's sections (L2): the open browser Pages, when the browser
    # application is loaded.
    from openprogram.runtime.context.components import build_turn_sections
    surface_prompt = build_turn_sections(
        agent_profile,
        {"surface_context": req.surface_context, "web_use_enabled": web_use_enabled},
        channel=req.source, tools=tools,
    )
    if surface_prompt and saved_system_prompt is None:
        system_prompt = f"{system_prompt}\n\n{surface_prompt}"
    contract = runtime_contract_snapshot(
        model=model, system_prompt=system_prompt, tools=tools, request=req,
        structured_output=req.response_format, toolset=agent_profile.get("toolset"),
    )
    return agent_profile, tools, recordable_prompt, system_prompt, model, contract


def with_current_location(snapshot: dict, session_id: str) -> dict:
    """Record where the rest of the turn runs in a safe-point snapshot.

    A tool may create or leave a worktree mid-turn (``worktree_create``);
    a resume resolves the location afresh, so a safe point must record the
    location as it is now rather than as it was when the turn began. It is
    resolved the way a resume resolves it, from the session's records and not
    from the running context: ``worktree_create`` binds its worktree only in
    the context the tool ran in.
    """
    semantics = snapshot.get("request_semantics")
    if not isinstance(semantics, dict):
        return snapshot
    from openprogram.runtime.conversation.workdir import runtime_location_for
    location = runtime_location_for(session_id, use_context=False)
    return {**snapshot, "request_semantics": {**semantics, "execution_location": location}}


def _continuation_agent_context(req, continuation, *, db, model, tools, runtime_contract):
    """Rebuild a resumed turn's AgentContext from its checkpoint, without the context engine."""
    from openprogram.runtime.agent.loop.types import AgentContext

    # Resume is not a new user turn.  Re-running the context engine would
    # perform its normal auto-compact/system-prompt bookkeeping and could
    # change the provider prefix captured by the checkpoint.  Render the
    # persisted branch directly at the user anchor and use the resolved
    # prompt stored by the original provider boundary.
    snapshot = continuation.resolved_snapshot
    durable_prompt = snapshot.get("system_prompt")
    durable_model = snapshot.get("model")
    if not isinstance(durable_prompt, str) or not isinstance(durable_model, dict):
        raise ValueError("Agent checkpoint resolved snapshot is invalid")
    if durable_model.get("id") != getattr(model, "id", None):
        raise ValueError("Agent checkpoint model no longer resolves")
    from openprogram.runtime.context.nodes import render_context
    from openprogram.runtime.context.render import render_dag_messages
    from openprogram.state.store.session.session_node_writer import SessionNodeWriter

    graph = SessionNodeWriter(db, req.session_id).load()
    anchor = getattr(req, "_steering_tail_id", None) or continuation.state.payload["turn"]["user_message_id"]
    if anchor not in graph.nodes:
        raise ValueError("Agent checkpoint user anchor is not in the session graph")
    # provider.before persists the exact provider message list in its
    # committed effect. Reuse it on restart so tool results from earlier
    # decisions in the same turn are retained. Runtime steering is then
    # appended by agent_loop's existing queue handling.
    from openprogram.runtime.execution.store import default_store as default_execution_store

    context_messages = provider_context_from_effect(
        continuation, continuation.execution_store or default_execution_store()
    )
    if context_messages is None:
        context_messages = render_dag_messages(
            graph,
            render_context(graph, head_id=anchor, frame_entry_seq=-1),
        )
    return AgentContext(
        system_prompt=durable_prompt,
        messages=context_messages,
        tools=tools,
        memory_prefetch="",
        runtime_contract=runtime_contract,
    )


def _auto_compact_new_turn(
    context_engine, req, *, db, on_event, agent_profile, model, tools,
    system_prompt, session, history, prep,
):
    """Compact the session into a durable summary node when the new turn is over budget."""
    # Auto-compact FIRST: the durable fix. It writes a summary node
    # into the DAG, so the shrink survives this turn (panel, next
    # turns, reload). Snip runs only as a fallback below.
    if req.history_override is None and context_engine.should_auto_compact(prep):
        try:
            loop = asyncio.new_event_loop()
            try:
                compact_res = loop.run_until_complete(
                    context_engine.compact(
                        agent=agent_profile,
                        session_id=req.session_id,
                        model=model,
                        on_event=on_event,
                        user_initiated=False,
                    )
                )
            finally:
                _shutdown_loop_clients(loop)
                loop.close()
            if compact_res.summary_id:
                # Re-load the post-compact view (summary + kept
                # tail) so the LLM call sees the shorter context.
                from openprogram.runtime.context.persistence import rendered_history
                history = rendered_history(db, req.session_id) or history
                prep = context_engine.prepare(
                    agent=agent_profile,
                    session=db.get_session(req.session_id) or session,
                    history=history,
                    model=model,
                    tools=tools,
                    system_prompt=system_prompt,
                )
        except Exception as e:  # noqa: BLE001
            # Auto-compact must never crash a new user turn.
            on_event({"type": "chat_response",
                      "data": {"type": "compaction_failed",
                               "session_id": req.session_id,
                               "error": f"{type(e).__name__}: {e}",
                               "user_initiated": False}})
    return history, prep


def _snip_new_turn(
    context_engine, req, *, db, on_event, agent_profile, model, tools,
    system_prompt, session, history, prep,
):
    """Drop the oldest turns when the new turn is still over budget after compaction."""
    # Snip fallback: compact failed, was skipped (<4 messages), or the
    # summary alone didn't free enough. This is only for a new turn.
    if req.history_override is None and context_engine.should_auto_compact(prep):
        try:
            from openprogram.runtime.context.snip import snip
            from openprogram.runtime.context.tokens import count_tokens
            snipped, n_snipped = snip(
                prep.history_dicts,
                token_counter=lambda msgs: count_tokens(msgs, model),
                context_window=prep.context_window,
            )
            if n_snipped > 0:
                history = snipped
                prep = context_engine.prepare(
                    agent=agent_profile,
                    session=db.get_session(req.session_id) or session,
                    history=history,
                    model=model,
                    tools=tools,
                    system_prompt=system_prompt,
                )
                on_event({"type": "chat_response",
                          "data": {"type": "snip",
                                   "session_id": req.session_id,
                                   "turns_removed": n_snipped}})
        except Exception:
            _log.warning(
                "history snip failed for session %s",
                req.session_id, exc_info=True,
            )
    return history, prep


def _recalled_memory_prefetch(db, req, *, assistant_msg_id, history) -> str:
    """Read the memory recalled for this turn from its user node."""
    # Memory recalled for a new turn. ``process_user_turn`` stamped it on
    # the user node; the resume path must not perform another read/write.
    memory_prefetch = ""
    prefetch_history = history
    prefetch_head = assistant_msg_id or req.user_msg_id
    if prefetch_head:
        prefetch_history = db.get_branch(req.session_id, prefetch_head) or history
    for message in reversed(prefetch_history or []):
        if message.get("role") == "user":
            memory_prefetch = message.get("memory_prefetch") or ""
            break
    return memory_prefetch


def _new_turn_agent_context(
    req, history, on_event, *, db, agent_profile, model, tools,
    system_prompt, recordable_system_prompt, runtime_contract, assistant_msg_id,
):
    """Route a new user turn's history through the context engine into an AgentContext."""
    from openprogram.runtime.agent.loop.types import AgentContext

    # Route a new user turn through the context engine: applies
    # tool-result aging in-memory and computes the provider budget.
    from openprogram.runtime.context import resolve_engine_for
    _ctx_engine = resolve_engine_for(agent_profile)
    _ctx_engine.on_session_start(req.session_id)
    # The prompt is recorded for new turns only.  A continuation reuses
    # the checkpointed resolved prompt instead.
    from openprogram.runtime.context.system_prompt_node import record_system_prompt
    record_system_prompt(db, req.session_id, recordable_system_prompt)
    session = db.get_session(req.session_id) or {}
    from openprogram.runtime.context import Context
    request_context = Context.current()
    if request_context is not None:
        history = request_context.filter_history(history)
    prep = _ctx_engine.prepare(
        agent=agent_profile,
        session=session,
        history=history,
        model=model,
        tools=tools,
        system_prompt=system_prompt,
    )
    budget = dict(
        db=db, on_event=on_event, agent_profile=agent_profile, model=model,
        tools=tools, system_prompt=system_prompt, session=session,
    )
    history, prep = _auto_compact_new_turn(_ctx_engine, req, history=history, prep=prep, **budget)
    history, prep = _snip_new_turn(_ctx_engine, req, history=history, prep=prep, **budget)
    return AgentContext(
        system_prompt=system_prompt,
        messages=prep.agent_messages,
        tools=tools,
        memory_prefetch=_recalled_memory_prefetch(
            db, req, assistant_msg_id=assistant_msg_id, history=history,
        ),
        runtime_contract=runtime_contract,
    )


def _restore_continuation_runtime(continuation, runtime_contract) -> None:
    """Check the live runtime still matches the checkpoint and reload its deferred tools."""
    from openprogram.runtime.agent.durable_steps import retained_function_names
    from openprogram.runtime.execution import default_store
    validate_runtime_contract(continuation.resolved_snapshot, runtime_contract, durable_function_names=retained_function_names(default_store(), continuation.checkpoint.execution_id))
    from openprogram.programs._host.runtime import mark_deferred_loaded
    mark_deferred_loaded(list(continuation.state.payload.get("loaded_deferred_tools", [])))


def _steering_source(req, *, model, db, assistant_msg_id, execution_context):
    """Build the loop's steering callback over the execution's durable steer queue.

    Returns the callback and the map of delivered steering messages that the
    drain publishes when each one's message_start arrives.
    """
    canonical_execution = bool((execution_context or {}).get("canonical_execution"))
    durable_steer_inputs = (execution_context or {}).get("steer_inputs")
    durable_steer_consumed_ids = (execution_context or {}).get("steer_consumed_ids")

    delivered_steers: dict[int, dict] = {}

    def _steer_images(payload: Mapping) -> list:
        # The text already names every file by path; the model also sees the
        # pictures when it takes images, as with a sent message.
        if "image" not in (model.input or []):
            return []
        from openprogram.models.providers.types import ImageContent

        blocks = []
        for image in payload.get("images") or []:
            try:
                data = base64.b64encode(Path(image["path"]).read_bytes()).decode("ascii")
                blocks.append(ImageContent(data=data, mime_type=image.get("media_type") or "image/png"))
            except (OSError, KeyError, TypeError):
                _log.warning("steer image dropped for session %s", req.session_id, exc_info=True)
        return blocks

    async def _get_one_steering_message():
        # Runtime steering is available only to a canonical execution and is
        # consumed from its durable execution command queue at a safe point.
        # Session-local inboxes are not a second steering transport.
        if req.source == "agent_spawn" or not canonical_execution:
            return []
        if not isinstance(durable_steer_inputs, list) or not durable_steer_inputs:
            return []
        item = durable_steer_inputs.pop(0)
        payload = item.get("payload") if isinstance(item, Mapping) else None
        text = payload.get("message") if isinstance(payload, Mapping) else None
        command_id = item.get("command_id") if isinstance(item, Mapping) else None
        if not isinstance(text, str) or not text.strip():
            return []
        if isinstance(durable_steer_consumed_ids, set) and isinstance(command_id, str):
            durable_steer_consumed_ids.add(command_id)
        from openprogram.state.store.session.nodes import Call, ROLE_USER
        from openprogram.models.providers.types import TextContent, UserMessage
        from openprogram.state.store import SessionNodeWriter

        if isinstance(command_id, str):
            import hashlib
            message_id = hashlib.sha256(f"{req.session_id}:{command_id}".encode()).hexdigest()[:24]
        else:
            message_id = uuid.uuid4().hex[:12]
        timestamp = time.time()
        predecessor = (
            getattr(req, "_steering_tail_id", None)
            or req.user_msg_id
            or "ROOT"
        )
        metadata = {
            "source": "web",
            "steering": True,
            "command_id": command_id,
            "agent_id": req.agent_id,
        }
        from openprogram.state.memory.policy import stamp
        metadata.update(stamp(req))
        try:
            from openprogram.state.authority import normalize_authority, stamp_schema

            metadata.update(normalize_authority(req))
            stamp_schema(metadata)
            persist = (execution_context or {}).get("persist_steer")
            delivery = (
                persist(command_id, message_id)
                if callable(persist) and isinstance(command_id, str)
                else contextlib.nullcontext()
            )
            with delivery:
                writer = SessionNodeWriter(db, req.session_id, advance_head=False)
                # Replay the idempotent append even when the memory index has
                # the ID: an earlier history write may have failed after indexing.
                writer.append(Call(
                    id=message_id,
                    created_at=timestamp,
                    role=ROLE_USER,
                    output=text,
                    predecessor=predecessor,
                    metadata=metadata,
                ))
                writer.update(assistant_msg_id, predecessor=message_id)
                if not db.has_persisted_ancestor(req.session_id, message_id, assistant_msg_id):
                    raise RuntimeError("steering message is not persisted in the assistant branch")
        except Exception as exc:
            if isinstance(durable_steer_consumed_ids, set) and isinstance(command_id, str):
                durable_steer_consumed_ids.discard(command_id)
            if getattr(exc, "code", None) == "steer_withdrawn":
                # Taken back before delivery: nothing was written, and the
                # inputs queued behind it are still due at this boundary.
                return None
            # Retain the command for another safe point if either the user
            # message or its delivery receipt could not be persisted.
            if isinstance(durable_steer_inputs, list):
                durable_steer_inputs.insert(0, item)
            _log.warning(
                "failed to persist steering for session %s",
                req.session_id,
                exc_info=True,
            )
            return []
        req._steering_tail_id = message_id
        message = UserMessage(content=[TextContent(text=text), *_steer_images(payload)],
                              timestamp=int(timestamp * 1000))
        # The producer can run ahead of the event consumer. Publish only when
        # its message_start reaches the ordered event stream, after prior output.
        delivered_steers[id(message)] = {
            "type":"user_message", "session_id":req.session_id, "msg_id":message_id,
            "content":text, "source":"web", "steering":True,
            "assistant_msg_id":assistant_msg_id, "command_id":command_id,
            "timestamp":timestamp, "predecessor":predecessor,
        }
        return [message]

    async def _get_steering_messages():
        # All commands already queued at this boundary belong to the next
        # decision. Leaving one behind would request another answer on resume.
        messages = []
        while isinstance(durable_steer_inputs, list) and durable_steer_inputs:
            delivered = await _get_one_steering_message()
            if delivered is None:
                continue
            if not delivered:
                break
            messages.extend(delivered)
        return messages

    return _get_steering_messages, delivered_steers


def _safe_point_hook_for(req, *, tools, assistant_msg_id, execution_context):
    """Build the loop's safe-point hook, or None when the execution has no safe-point callback."""
    safe_point_callback = (execution_context or {}).get("safe_point_hook")
    last_safe_point_snapshot: dict[str, object] = {}

    async def _safe_point_hook(kind: str, payload: dict) -> bool:
        nonlocal last_safe_point_snapshot
        if safe_point_callback is None:
            return False
        durable_payload = dict(payload)
        from openprogram.programs._host.runtime import loaded_deferred_names
        durable_payload["loaded_deferred_tools"] = [
            name for name in loaded_deferred_names()
            if name in {tool.name for tool in tools or []}
        ]
        snapshot = durable_payload.get("resolved_snapshot")
        if isinstance(snapshot, dict):
            last_safe_point_snapshot = dict(snapshot)
        elif last_safe_point_snapshot:
            durable_payload["resolved_snapshot"] = dict(last_safe_point_snapshot)
        if isinstance(durable_payload.get("resolved_snapshot"), dict):
            durable_payload["resolved_snapshot"] = with_current_location(
                durable_payload["resolved_snapshot"], req.session_id,
            )
        durable_payload["turn"] = {
            "user_message_id": req.user_msg_id or "",
            "assistant_message_id": assistant_msg_id or "",
            "base_history_head_id": req.user_msg_id or "",
            "branch_id": "main",
        }
        result = safe_point_callback(kind, durable_payload)
        if inspect.isawaitable(result):
            result = await result
        payload.update(durable_payload)
        # AgentLoop treats a true result as an ownership hand-off.  Preserve
        # it verbatim so no later tool, persistence, or finalize stage runs.
        handed_off = bool(result)
        if handed_off and execution_context is not None:
            execution_context["safe_point_committed"] = True
        return handed_off

    return _safe_point_hook if safe_point_callback is not None else None


def _permission_context_transform(req, continuation):
    """Build the transform that appends the request context and the current permission mode."""
    async def _permission_context(messages, _cancel):
        from openprogram.models.providers.types import TextContent, UserMessage
        from openprogram.runtime.permissions import current_permission_request
        from openprogram.runtime.context import Context
        request_context = Context.current()
        if request_context is not None and continuation is None:
            messages = request_context.add_to_messages(messages)
        current = current_permission_request(req)
        version = getattr(current, "_permission_version", 0)
        if not version:
            return messages
        return [*messages, UserMessage(
            role="user", content=[TextContent(text=(
                f"[Runtime permission setting, owner-confirmed version {version}] "
                f"The current permission mode is {current.permission_mode}. "
                "Use this current mode instead of earlier mode descriptions. "
                "Authority, explicit rules, mandatory approvals, and Sandbox still apply."
            ))], timestamp=0,
        )]

    return _permission_context


def _agent_loop_config(req, *, agent_profile, model, transform_context,
                       get_steering_messages, safe_point_hook):
    """Assemble the AgentLoopConfig from the request, the agent profile and the turn's callbacks."""
    from openprogram.runtime.agent.loop.types import AgentLoopConfig
    # _default_convert_to_llm filters out non-LLM messages (e.g. our
    # custom error / system entries) — agent.py already provides this.
    from openprogram.runtime.agent.loop.driver import _default_convert_to_llm
    from openprogram.models.providers.settings.fast import resolve_service_tier

    turn_options = agent_profile.get('_agent_turn_options') or {}
    return AgentLoopConfig(
        model=model,
        max_iterations=turn_options.get('max_iterations'),
        tool_choice=turn_options.get('tool_choice'),
        parallel_tool_calls=turn_options.get('parallel_tool_calls'),
        convert_to_llm=_default_convert_to_llm,
        transform_context=transform_context,
        # Pass session_id so providers that support it
        # (openai_codex/openai_responses/azure) set prompt_cache_key on
        # every request. Without it OpenAI prompt cache can only match
        # the anonymous static prefix (~ instructions), so longer
        # conversations sit at ~10-20% hit rate even though the message
        # tail is identical turn-to-turn.
        session_id=req.session_id,
        reasoning=reasoning_from_config(SessionRunConfig(
            thinking_effort=req.thinking_effort
            if req.thinking_effort is not None
            else agent_profile.get("thinking_effort"),
        )),
        # Per-turn speed tier → SimpleStreamOptions.service_tier →
        # provider request body. Per-turn value wins; else the agent
        # profile's stored default; else None (provider default).
        service_tier=resolve_service_tier(model, (
            req.service_tier
            if req.service_tier is not None
            else agent_profile.get("service_tier")
        )),
        response_format=req.response_format,
        # Provider-side search, resolved with the tools in resolve_agent_runtime.
        web_search=True if getattr(req, "_provider_web_search", False) else None,
        get_steering_messages=get_steering_messages,
        safe_point_hook=safe_point_hook,
    )


def _start_cancel_bridge(cancel_event: threading.Event, turn_over: threading.Event,
                         loop_cancel: asyncio.Event) -> None:
    """Bridge the thread-side cancel event into the running asyncio loop."""
    # Bridge thread-side cancel into asyncio. Capture the
    # running loop here (the watch thread can't call
    # ``get_event_loop`` — Python 3.12+ raises in non-main
    # threads with no loop set).
    asyncio_loop = asyncio.get_running_loop()

    def _watch():
        while not (cancel_event.wait(0.1) or turn_over.is_set()):
            pass
        if cancel_event.is_set():
            try:
                asyncio_loop.call_soon_threadsafe(loop_cancel.set)
            except RuntimeError:
                # Loop already closed — the turn finished first.
                pass
    threading.Thread(
        target=_watch, daemon=True, name="turn-cancel-bridge",
    ).start()


def _start_agent_stream(req, context, config, continuation, loop_cancel, stream_fn):
    """Start agent_loop with the user's prompt, or resume the continuation's decision."""
    from openprogram.runtime.agent.loop import agent_loop, agent_loop_resume

    # Normal turns add their prompt once. A continuation already owns a
    # persisted user anchor and restores its provider decision directly.
    # plus UserMessage prompt added by agent_loop exactly once.
    # The old user_already_persisted branch used agent_loop_continue
    # with history that included the duplicated user_msg as both
    # the tail of context.messages AND the "current turn" prompt,
    # which broke OpenAI prompt cache because the prefix's last
    # item flipped between turns (user N's duplicate → user N's
    # assistant reply).
    from openprogram.models.providers.types import (
        ImageContent, TextContent, UserMessage,
    )
    if continuation is None:
        content_blocks: list = []
        if req.user_text:
            from openprogram.runtime.permissions.authority import render_model_input_from
            content_blocks.append(TextContent(
                text=render_model_input_from(req, req.user_text)
            ))
        for att in (req.attachments or []):
            if not isinstance(att, dict):
                continue
            if att.get("type") == "image":
                try:
                    content_blocks.append(ImageContent(
                        data=att.get("data") or "",
                        mime_type=att.get("media_type") or "image/png",
                    ))
                except Exception:
                    _log.warning("image attachment dropped for session %s",
                                 req.session_id, exc_info=True)
        if not content_blocks:
            content_blocks = [TextContent(text="")]
        prompt = UserMessage(
            content=content_blocks,
            timestamp=int(time.time() * 1000),
        )
        return agent_loop([prompt], context, config,
                          loop_cancel, stream_fn)
    return agent_loop_resume(
        continuation, context, config, loop_cancel, stream_fn,
    )


@dataclass
class _TurnTally:
    """What the drain accumulates from the event stream for the turn's result."""

    final_text_parts: list[str] = field(default_factory=list)
    usage_total: dict = field(default_factory=lambda: {
        "input_tokens": 0, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
        "provider_request_count": 0, "agent_iteration_count": 0,
        "context_tokens": 0,
    })
    tool_calls: list[dict] = field(default_factory=list)
    seen_tool_ids: set[str] = field(default_factory=set)
    # Capture tool_use inputs so we can rebuild the same
    # collapsible scaffold on reload. tool_execution_end events
    # don't carry the input args, so we stash them at start time.
    tool_inputs_by_id: dict[str, dict] = field(default_factory=dict)


def _seed_tally_from_continuation(tally: _TurnTally, continuation, ordered_blocks_out) -> None:
    """Carry the resumed decision's cards, tool calls and usage into the tally."""
    tally.seen_tool_ids = _seed_continuation_cards(
        continuation,
        ordered_blocks_out=ordered_blocks_out,
        tool_calls=tally.tool_calls,
        final_text_parts=tally.final_text_parts,
    )
    prior_usage = continuation.assistant_message.usage
    prior_tiers = _extract_usage(continuation.assistant_message).get("service_tiers")
    if prior_tiers:
        tally.usage_total["service_tiers"] = list(prior_tiers)
    tally.usage_total.update({
        "input_tokens": int(getattr(prior_usage, "input", 0) or 0),
        "output_tokens": int(getattr(prior_usage, "output", 0) or 0),
        "cache_read_tokens": int(getattr(prior_usage, "cache_read", 0) or 0),
        "cache_write_tokens": int(getattr(prior_usage, "cache_write", 0) or 0),
        "provider_request_count": 1,
        "agent_iteration_count": 1,
    })


def _raise_provider_error(msg) -> None:
    """Re-raise a stream-level provider failure as LLMError."""
    # Stream-level provider failure (HTTP 4xx/5xx
    # surfaced as an error event, not an exception).
    # Without this the turn "succeeds" with empty
    # text — a blank assistant bubble. Re-raise as
    # LLMError so the dispatcher's exception path
    # renders the red error bubble with taxonomy,
    # same as a synchronously-raised failure.
    from openprogram.models.providers.utils.errors import (
        ErrorReason, LLMError,
    )
    _reason_val = getattr(msg, "error_reason", None)
    try:
        _reason = (ErrorReason(_reason_val)
                   if _reason_val else ErrorReason.UNKNOWN)
    except ValueError:
        _reason = ErrorReason.UNKNOWN
    raise LLMError(
        message=(getattr(msg, "error_message", "") or
                 "provider returned an error"),
        reason=_reason,
        retryable=bool(
            getattr(msg, "error_retryable", None) or False),
        retry_after_s=getattr(
            msg, "error_retry_after_s", None),
        provider=getattr(msg, "provider", None),
        model=getattr(msg, "model", None),
    )


def _record_turn_end(ev, tally: _TurnTally, *, req, on_event, ordered_blocks_out) -> None:
    """Fold one provider call's message into the turn's text, usage and ordered cards."""
    tally.usage_total["provider_request_count"] += 1
    tally.usage_total["agent_iteration_count"] += 1
    msg = getattr(ev, "message", None)
    if getattr(msg, "structured_output_mode", None) is not None:
        req.structured_output = getattr(msg, "structured_output", None)
        req.structured_output_mode = msg.structured_output_mode
        req.structured_output_attempt = getattr(
            msg, "structured_output_attempt", None
        )
    if getattr(msg, "stop_reason", None) == "error":
        _raise_provider_error(msg)
    text = _extract_text(msg)
    if text:
        tally.final_text_parts.append(text)
    usage = _extract_usage(msg)
    if usage.get("service_tiers"):
        tally.usage_total.setdefault("service_tiers", []).extend(usage["service_tiers"])
    for k in ("input_tokens", "output_tokens",
              "cache_read_tokens", "cache_write_tokens"):
        tally.usage_total[k] += usage.get(k, 0)
    # 当前上下文占用 ≈ 最后一次调用的 prompt 体积
    # （input + cache_read）。turn 内多次调用的 input
    # 之和会远超窗口，只能用于计费，不能用于占用率。
    prompt_tokens = (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_tokens", 0)
    )
    # Empty terminal events must not erase the last request.
    if prompt_tokens > 0:
        tally.usage_total["context_tokens"] = prompt_tokens
        tally.usage_total["request_input_estimate"] = usage.get("request_input_estimate", 0)
    if prompt_tokens > 0:
        on_event({
            "type": "chat_response",
            "data": {
                "type": "context_usage",
                "session_id": req.session_id,
                "msg_id": req.user_msg_id,
                "usage": usage,
            },
        })
    # Build ordered blocks from msg.content so the
    # webui can render thinking / text / tool cards
    # interleaved in their original LLM emission
    # order. Without this the bubble shows all LLM
    # text first and then every tool card stacked at
    # the bottom — wrong when the LLM said something,
    # called a tool, then kept narrating.
    if ordered_blocks_out is not None and msg is not None:
        try:
            for blk in getattr(msg, "content", None) or []:
                ordered = _ordered_block_from_content(blk)
                if ordered is None:
                    continue
                tool_id = ordered.get("tool_call_id")
                if (
                    ordered.get("type") == "tool"
                    and tool_id
                    and str(tool_id) in tally.seen_tool_ids
                ):
                    continue
                ordered_blocks_out.append(ordered)
                if ordered.get("type") == "tool" and tool_id:
                    tally.seen_tool_ids.add(str(tool_id))
        except Exception:
            # Provider block shapes vary; a normalisation miss
            # costs one rendered block, not the turn.
            _log.debug(
                "provider block normalisation failed",
                exc_info=True,
            )


def _record_agent_event(ev, tally: _TurnTally, *, req, on_event, ordered_blocks_out) -> None:
    """Record the side effects of one agent event that the turn's result needs."""
    # Side-effects we care about for the final result.
    # Approval is gated INSIDE the wrapped tool execute (see
    # _wrap_with_approval) — by the time tool_execution_start
    # fires, the user has already approved (or the wrapper
    # short-circuited with a denial result).
    if hasattr(ev, "type"):
        if ev.type == "tool_execution_start":
            _tid = getattr(ev, "tool_call_id", None)
            _args = getattr(ev, "args", None)
            if _tid is not None:
                tally.tool_inputs_by_id[_tid] = {
                    "tool": getattr(ev, "tool_name", None),
                    "input": json.dumps(_args, default=str)
                             if _args is not None else None,
                }
        if ev.type == "tool_execution_end":
            _tid = getattr(ev, "tool_call_id", None)
            _meta = tally.tool_inputs_by_id.get(_tid, {})
            _tc = {
                "id": _tid,
                "tool_call_id": _tid,
                "tool": getattr(ev, "tool_name", None) or _meta.get("tool"),
                "input": _meta.get("input"),
                "result": _shorten(getattr(ev, "result", "")),
                "is_error": bool(getattr(ev, "is_error", False)),
                "outcome": getattr(ev, "outcome", None),
            }
            tally.tool_calls.append(_tc)
        if ev.type == "turn_end":
            _record_turn_end(
                ev, tally, req=req, on_event=on_event,
                ordered_blocks_out=ordered_blocks_out,
            )


async def _drain_agent_events(
    *, req, context, config, continuation, stream_fn, cancel_event,
    turn_over: threading.Event, on_event, ordered_blocks_out, delivered_steers,
) -> tuple[str, dict, list[dict]]:
    """Run the agent loop and forward each AgentEvent to on_event, tallying the result."""
    loop_cancel = asyncio.Event()
    if cancel_event is not None:
        _start_cancel_bridge(cancel_event, turn_over, loop_cancel)

    ev_stream = _start_agent_stream(req, context, config, continuation, loop_cancel, stream_fn)

    tally = _TurnTally()
    if continuation is not None:
        _seed_tally_from_continuation(tally, continuation, ordered_blocks_out)

    # aclosing so an early exit (the LLMError raise below) runs the
    # generator's finally/aclose here, instead of leaving it for the
    # GC to schedule on a loop we are about to close.
    async with contextlib.aclosing(
            _aiter_event_stream(ev_stream)) as _events:
        async for ev in _events:
            if getattr(ev, "type", None) == "message_start":
                delivered = delivered_steers.pop(id(getattr(ev, "message", None)), None)
                if delivered is not None:
                    if ordered_blocks_out is not None:
                        ordered_blocks_out.append({"type":"steering", "message_id":delivered["msg_id"],
                                                   "text":delivered["content"], "timestamp":delivered["timestamp"]})
                    on_event({"type":"chat_response", "data":delivered})
            envelope = _agent_event_to_envelope(ev, req)
            if envelope is not None:
                on_event(envelope)
            _record_agent_event(
                ev, tally, req=req, on_event=on_event,
                ordered_blocks_out=ordered_blocks_out,
            )

    return "".join(tally.final_text_parts).strip(), tally.usage_total, tally.tool_calls


def run_loop_blocking(
    *,
    req: "TurnRequest",
    history: list[dict],
    on_event: "EventCallback",
    cancel_event: Optional[threading.Event],
    stream_fn=None,
    assistant_msg_id: Optional[str] = None,
    agentic_tool_names_out: Optional[set[str]] = None,
    ordered_blocks_out: Optional[list[dict]] = None,
    execution_context: Optional[dict] = None,
    continuation=None,
) -> tuple[str, dict, list[dict]]:
    """Build AgentContext, kick off agent_loop, drain its EventStream.

    Returns (final_text, usage, tool_calls).

    `ordered_blocks_out`, if provided, is mutated in place to hold the
    per-turn ordered block list (``[{"type":"thinking"|"text"|"tool",
    ...}, ...]``) reconstructed from the final AssistantMessage's
    content. Used by the webui to render LLM text / thinking / tool
    cards in the order they appeared, instead of stacking all tools
    at the bottom of the bubble.

    Runs synchronously inside a fresh asyncio loop so callers don't
    need to be async. Cancel via cancel_event flips an asyncio.Event
    inside the loop.

    `stream_fn` is the seam tests use to inject a fake provider —
    see tests/unit/agent/dispatcher/test_dispatcher_integration.py. None means use
    the default (real provider via stream_simple).
    """
    from openprogram.runtime.agent.turn_api import _current_turn_agent
    owner = _current_turn_agent.get()
    if stream_fn is None and owner is not None:
        stream_fn = owner._options.get('stream_fn')
    # Continuation already binds TurnBindings in process_agent_continuation.
    # Nested worktree here only covers resolve_agent_runtime when this
    # function is invoked without those bindings (tests and older callers).
    _worktree_token = None
    if continuation is not None:
        from openprogram.runtime.conversation.workdir import runtime_location_for
        from openprogram.state.worktree.context import reset_worktree, set_worktree
        _worktree_token = set_worktree(
            runtime_location_for(req.session_id, use_context=False)["workdir"],
        )
    try:
        # Resolve agent profile → tools, system_prompt, model.
        agent_profile, tools, recordable_system_prompt, system_prompt, model, runtime_contract = resolve_agent_runtime(
            req, assistant_msg_id=assistant_msg_id, on_event=on_event,
            saved_runtime_contract=continuation.resolved_snapshot if continuation is not None else None,
        )
    finally:
        if _worktree_token is not None:
            reset_worktree(_worktree_token)
    if agentic_tool_names_out is not None:
        agentic_tool_names_out.update(
            tool.name for tool in tools if getattr(tool, "_is_agent_method", False)
        )
    # One assembler (dag/overview.md §7). The tool-runtime block, the Layer 6
    # deferred-tool catalog and the plan-mode reminder are registered
    # components now — the dispatcher no longer hand-appends anything, so the
    # string the engine budgets is the string that ships.
    #
    # We do NOT split ``tools`` for dispatch here — the agent_loop re-splits
    # before every provider call so newly-loaded deferred tools show up with
    # full schema on the next call. The catalog component only lists the
    # *initial* deferred names so the LLM can discover them from turn 1.
    from openprogram.runtime.context import Context
    db = Context.turn_store(req.session_id)
    if continuation is not None:
        context = _continuation_agent_context(
            req, continuation, db=db, model=model, tools=tools,
            runtime_contract=runtime_contract,
        )
    else:
        context = _new_turn_agent_context(
            req, history, on_event, db=db, agent_profile=agent_profile,
            model=model, tools=tools, system_prompt=system_prompt,
            recordable_system_prompt=recordable_system_prompt,
            runtime_contract=runtime_contract, assistant_msg_id=assistant_msg_id,
        )

    if continuation is not None:
        _restore_continuation_runtime(continuation, runtime_contract)

    get_steering_messages, delivered_steers = _steering_source(
        req, model=model, db=db, assistant_msg_id=assistant_msg_id,
        execution_context=execution_context,
    )
    config = _agent_loop_config(
        req, agent_profile=agent_profile, model=model,
        transform_context=_permission_context_transform(req, continuation),
        get_steering_messages=get_steering_messages,
        safe_point_hook=_safe_point_hook_for(
            req, tools=tools, assistant_msg_id=assistant_msg_id,
            execution_context=execution_context,
        ),
    )

    # Async drain that forwards each AgentEvent → on_event envelope.
    # Released once the drain loop is done so the cancel-bridge thread
    # exits when the turn ends normally. Without it the thread parks on
    # ``cancel_event.wait()`` for the life of the process — one leaked
    # thread per turn.
    _turn_over = threading.Event()

    # Run the async drain in a fresh loop (we're in a thread).
    loop = asyncio.new_event_loop()
    try:
        from openprogram.host._platform.power import prevent_idle_sleep

        with prevent_idle_sleep():
            return loop.run_until_complete(_drain_agent_events(
                req=req, context=context, config=config, continuation=continuation,
                stream_fn=stream_fn, cancel_event=cancel_event, turn_over=_turn_over,
                on_event=on_event, ordered_blocks_out=ordered_blocks_out,
                delivered_steers=delivered_steers,
            ))
    finally:
        # Let the cancel-bridge thread exit before the loop it would post to
        # is gone.
        _turn_over.set()
        # Close any async generator the provider/agent layers left open
        # (an abandoned one otherwise schedules its aclose onto this loop
        # right as we close it, which never runs and warns at GC time).
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            _log.debug("asyncgen shutdown failed", exc_info=True)
        # The provider clients this loop built are keyed by it: close them
        # here, on the loop, or their cache entries outlive it and count
        # against the shared cache's limit for the rest of the process.
        _shutdown_loop_clients(loop)
        loop.close()
