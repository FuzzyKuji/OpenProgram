"""Session hydration: the ``load_session`` action."""
from __future__ import annotations

import asyncio
import json

from .tool_output import _truncate_tool_outputs_for_wire
from .transcript import _annotate_spawn_origin
from .transcript import _spawned_branch
from .transcript import _ordered_fn_run_siblings
from .transcript import splice_compaction_event_rows
from .transcript import _is_top_function_run
from .transcript import _rebuild_runtime_cards


def _branched_from(session_row: dict) -> dict | None:
    """``{"session_id", "msg_id", "title", "exists"}`` for a branched
    session, else None.

    ``title`` is the source's title now (or "" when it has none or is
    gone); the client prefers its live session list for renames.
    ``exists`` is False once the source was deleted.
    """
    lineage = (session_row.get("extra_meta") or {}).get("branched_from") \
        or session_row.get("branched_from")
    if not isinstance(lineage, dict) or not lineage.get("session_id"):
        return None
    title, exists = "", False
    try:
        from openprogram.runtime.context.session_db import default_db
        source = default_db().get_session(str(lineage["session_id"]))
        exists = source is not None
        title = str((source or {}).get("title") or "")
    except Exception:  # noqa: BLE001 — the banner falls back to a generic name
        title, exists = "", False
    return {"session_id": lineage["session_id"], "msg_id": lineage.get("msg_id"),
            "title": title, "exists": exists}


def _session_todos(session_id: str) -> list:
    try:
        from openprogram.programs.tools.planning.todo import shared as _todos
        return _todos.load(session_id)
    except Exception:
        return []


def _session_todo_plans(session_id: str) -> list:
    try:
        from openprogram.programs.tools.planning.todo import shared as _todos
        return _todos.load_plans(session_id)
    except Exception:
        return []


async def _session_io(func, *args, **kwargs):
    """Run one bounded session-store read without blocking the WS loop."""
    return await asyncio.to_thread(func, *args, **kwargs)


async def _serve_cached_history_page(ws, cmd: dict, session_id) -> bool:
    """Validate a history-page request and answer it from the cached snapshot; True when served."""
    from openprogram.interfaces.server.ws_errors import OperationError
    from openprogram.runtime.context.session_db import default_db
    from openprogram.interfaces.server.session_history import HistorySnapshot
    history_before = cmd.get("history_before")
    history_after = cmd.get("history_after")
    history_around = cmd.get("history_around")
    if sum(key in cmd for key in ("history_before", "history_after", "history_around", "history_latest")) != 1:
        raise OperationError("invalid_request", scope="session")
    for value in (history_before, history_after, history_around):
        if value is not None and not isinstance(value, str):
            raise OperationError("invalid_request", scope="session")
    cached = getattr(ws, "_history_snapshots", {}).get(session_id)
    if (not cmd.get("history_latest") and isinstance(cached, HistorySnapshot) and cached.token == cmd.get("history_snapshot")
            and cached.head_id == cmd.get("history_head")):
        if not await _session_io(default_db().get_session, session_id):
            raise OperationError("invalid_request", scope="session")
        ws._history_snapshots.move_to_end(session_id)
        try:
            messages, history = await _session_io(cached.page, before=history_before, after=history_after, around=history_around)
        except ValueError as exc:
            raise OperationError("invalid_request", scope="session") from exc
        await ws.send_text(json.dumps({"type": "session_history_page", "data": {
            "id": session_id, "messages": messages, "history": history,
            "request_id": cmd.get("request_id"), "action": "load_session",
        }}, ensure_ascii=False, default=str))
        return True
    return False


async def _find_or_hydrate_session(_s, session_id):
    """The in-memory session, hydrated from SessionDB on a cold load; None when it does not exist."""
    with _s._sessions_lock:
        conv = _s._sessions.get(session_id)
    # Cold load (fresh worker, new browser session, or a session created
    # by the fn-form REST path that never went through a WS chat turn):
    # the conv isn't in the in-memory map yet. If it exists on disk,
    # hydrate it from SessionDB so the full aggregation below runs —
    # otherwise we'd fall to the empty-stub ``else`` and the page would
    # render the Welcome screen for a session that actually has history
    # (e.g. a manually-invoked Agent method's top-level code node).
    if conv is None and session_id:
        from openprogram.runtime.context.session_db import default_db as _db_probe
        try:
            _exists = await _session_io(
                lambda: _db_probe().get_session(session_id) is not None
            )
        except Exception:
            _exists = False
        if _exists:
            conv = await _session_io(
                _s._get_or_create_session, session_id
            )
    return conv


async def _read_session_messages(_db_load, conv: dict, conv_snapshot: dict):
    """Persisted head plus the visible raw rows and their tool-aggregated form: ``(persisted_head, raw_msgs, all_msgs)``."""
    from openprogram.interfaces.server.persistence import aggregate_tool_messages
    try:
        # Capture the persisted head before history I/O. A concurrent
        # chat may advance the store while get_messages is in progress;
        # using a later head would point this response outside its
        # captured message snapshot.
        _sess_for_load = await _session_io(
            _db_load.get_session, conv["id"]
        ) or {}
        _persisted_head = _sess_for_load.get("head_id")
    except Exception:
        _persisted_head = None
    try:
        # Session hydration is a bounded snapshot.  Capture the database
        # handle and session id before yielding; all later aggregation is
        # performed against this snapshot, so a concurrent turn cannot
        # change the frame's message set halfway through construction.
        raw_msgs = await _session_io(
            _db_load.get_messages, conv["id"]
        ) or []
        hidden_ids = {
            m.get("id") for m in raw_msgs
            if m.get("execution_control") and m.get("id")
        }
        changed = True
        while changed:
            before = len(hidden_ids)
            hidden_ids.update(
                m.get("id") for m in raw_msgs
                if m.get("caller") in hidden_ids
            )
            changed = len(hidden_ids) != before
        raw_msgs = [
            m for m in raw_msgs if m.get("id") not in hidden_ids
        ]
        from openprogram.programs.tools.planning.goal.presentation import annotate_messages
        raw_msgs = await _session_io(annotate_messages, conv["id"], raw_msgs)
        # Fold standalone role="tool" rows into their parent assistant's
        # tool_calls[] so the chat UI sees the same shape on refresh
        # as it does on live WS stream.
        all_msgs = await _session_io(aggregate_tool_messages, raw_msgs)
    except Exception:
        all_msgs = conv_snapshot["messages"]
        raw_msgs = all_msgs
    return _persisted_head, raw_msgs, all_msgs


def _resolve_head(cmd: dict, is_history_page: bool, head, raw_msgs: list, all_msgs: list):
    """The head this load anchors on: the requested page head, walked up past rows aggregation folded away."""
    if is_history_page and not cmd.get("history_latest"):
        from openprogram.interfaces.server.ws_errors import OperationError
        requested_head = cmd.get("history_head")
        if (not isinstance(requested_head, str)
                or requested_head not in {m.get("id") for m in all_msgs}):
            raise OperationError("invalid_request", scope="session", retryable=True)
        head = requested_head
    # If the persisted head points at a row that aggregation just
    # folded away (e.g. a role="tool" child of an assistant whose
    # turn never reached step 6's ``update_session(head_id=...)``
    # — common after a worker restart mid-turn), walk up the raw
    # predecessor chain until we hit a row that survived
    # aggregation. Without this the get_branch(head) walk below
    # anchors on a folded-away id and returns [], so the page
    # renders the empty Welcome screen despite real history.
    if head:
        agg_ids = {m.get("id") for m in all_msgs}
        if head not in agg_ids:
            raw_by_id = {m.get("id"): m for m in raw_msgs}
            cur = head
            hops = 0
            while cur and cur not in agg_ids and hops < 100:
                # A call row hangs off its reply by ``caller`` with an
                # empty predecessor, so the walk takes either edge.
                row = raw_by_id.get(cur) or {}
                parent = row.get("predecessor") or row.get("caller")
                if not parent or parent == cur:
                    cur = None
                    break
                cur = parent
                hops += 1
            if cur and cur in agg_ids:
                head = cur
    return head


async def _active_branch_chain(_db_load, session_id, head, all_msgs: list) -> list:
    """The displayed branch, oldest-first, from the store's branch walk under ``head``."""
    from openprogram.runtime.context.git import active_branch_chain
    # The active branch is authoritative: get_branch(head) walks
    # predecessor + caller + ROOT-seq edges (handling fn-call gaps a
    # pure predecessor walk misses) and yields exactly this branch's
    # node ids. active_branch_chain keeps only those ids out of the
    # full, tool-aggregated all_msgs — so the chat shows one branch,
    # oldest-first, with each assistant's folded tool_calls intact,
    # and sibling turns from OTHER branches never leak in. Falls back
    # to a predecessor walk (or all_msgs) if the head is stale/None.
    try:
        branch_rows = await _session_io(
            _db_load.get_branch, session_id, head
        ) or []
        branch_ids = {m.get("id") for m in branch_rows}
    except Exception:
        branch_ids = set()
    return active_branch_chain(all_msgs, branch_ids, head)


def _splice_attach_pointers(chain: list, all_msgs: list) -> list:
    """Insert attach pointer rows right after the chain message they hang off."""
    # Splice attach pointer rows (function="attach") into the
    # displayed chain. They hang off a parent message via
    # predecessor — not on the conv chain itself — so
    # linear_history skips them, but the chat needs them inline
    # as standalone AttachCard rows.
    chain_ids = {m.get("id") for m in chain}
    attach_by_parent: dict[str, list[dict]] = {}
    for m in all_msgs:
        if m.get("function") != "attach":
            continue
        # Skip pointers already in the chain — older writes set
        # both predecessor and caller, which made attach pointers
        # appear as conv children too. New writes only set
        # predecessor; this guard keeps old data from doubling up.
        if m.get("id") in chain_ids:
            continue
        parent = m.get("predecessor") or ""
        if parent and parent in chain_ids:
            attach_by_parent.setdefault(parent, []).append(m)
    if attach_by_parent:
        spliced: list[dict] = []
        for m in chain:
            spliced.append(m)
            extras = attach_by_parent.get(m.get("id"), [])
            extras.sort(key=lambda x: x.get("timestamp") or 0)
            spliced.extend(extras)
        chain = spliced
    return chain


def _splice_runtime_placeholders(chain: list, all_msgs: list) -> list:
    """Insert runtime-block placeholder rows right after their owning assistant reply."""
    # Splice runtime-block placeholder rows written by the
    # dispatcher's Agent method wrapper. They hang off the
    # assistant reply that called the tool via predecessor but are
    # not on the conv chain itself (the chain's head is the
    # assistant reply, not its runtime child). The chat needs
    # each placeholder as a standalone RuntimeBlock row right
    # after its owning assistant reply.
    chain_ids = {m.get("id") for m in chain}
    runtime_by_parent: dict[str, list[dict]] = {}
    for m in all_msgs:
        if m.get("type") != "status" or m.get("display") != "runtime":
            continue
        if m.get("id") in chain_ids:
            continue
        parent = m.get("predecessor") or ""
        if parent and parent in chain_ids:
            runtime_by_parent.setdefault(parent, []).append(m)
    if runtime_by_parent:
        spliced2: list[dict] = []
        for m in chain:
            spliced2.append(m)
            extras = runtime_by_parent.get(m.get("id"), [])
            extras.sort(key=lambda x: x.get("timestamp") or 0)
            spliced2.extend(extras)
        chain = spliced2
    return chain


def _messages_by_id(all_msgs: list) -> dict:
    """Every dict row keyed by id."""
    by_id_all = {}
    for mm in all_msgs:
        if not isinstance(mm, dict):
            continue
        try:
            by_id_all[mm.get("id")] = mm
        except TypeError:
            continue
    return by_id_all


def _rows_with_sibling_navigation(chain: list, all_msgs: list, by_id_all: dict, session_id) -> list:
    """Chain rows with their version-switcher fields, attach pointers enriched with embed stats."""
    from openprogram.runtime.context.git import deepest_leaf, sibling_navigation_index
    from openprogram.runtime.context.session_db import default_db as _ddb
    from openprogram.state.store.session.graph.branches import (
        _attach_info as _ainfo, _attach_embed_stats as _astats,
    )
    # Version switcher for a Function-call card must count only the
    # COMPLETE runs that are true alternatives of THIS run — i.e. the
    # other top-level Agent method entry nodes sharing this run's
    # conversation predecessor (a retry forks off the original's
    # predecessor; a new run chains off the head, so it has no
    # alternatives). Plain ``sibling_index`` counts every node sharing
    # the parent — for legacy ROOT-anchored runs that lumps together
    # all root-level calls AND their predecessor-less sub-calls (the
    # "1/12" the user saw). Restrict the sibling set to fn-run entry
    # nodes so a fresh, model-anchored session shows exactly 2/2.

    def _norm_pred(mm):
        """The fork-point id of a run: its conversation predecessor,
        falling back to ``caller`` (a retry expresses the fork via
        caller, a chained new run via the predecessor field — both name
        the same fork parent). ROOT / absent → None (root-level)."""
        p = mm.get("predecessor") or mm.get("caller") or None
        return None if p == "ROOT" else p

    _fn_run_ids = set()
    _fn_run_siblings_by_pred = {}
    for position, mm in enumerate(all_msgs):
        if not isinstance(mm, dict):
            continue
        message_id = mm.get("id")
        try:
            if (
                mm.get("role") in ("tool", "code")
                and _is_top_function_run(mm, by_id_all)
            ):
                _fn_run_ids.add(message_id)
                _fn_run_siblings_by_pred.setdefault(
                    _norm_pred(mm), []
                ).append((mm, position))
        except TypeError:
            continue

    def _fn_run_siblings(mid_):
        """Ordered ids of the fn-run entries sharing ``mid_``'s
        predecessor (self included), by created_at then insertion."""
        return _ordered_fn_run_siblings(
            by_id_all, _fn_run_siblings_by_pred, mid_, _norm_pred,
        )

    _chat_navigation = sibling_navigation_index(
        all_msgs,
        target_ids={m.get("id") for m in chain if m.get("id")},
    )
    shown = []
    for m in chain:
        mid = m.get("id")
        # Function-call cards get fn-run-scoped sibling nav; every
        # other row (chat turns) keeps the plain predecessor-share nav.
        if m.get("display") == "runtime" and mid in _fn_run_ids:
            ids = _fn_run_siblings(mid)
            i = ids.index(mid) if mid in ids else -1
            idx = (i + 1) if i >= 0 else 0
            total = len(ids)
            prev_id = next_id = None
            if i > 0:
                prev_id = deepest_leaf(all_msgs, ids[i - 1])
            if 0 <= i < total - 1:
                next_id = deepest_leaf(all_msgs, ids[i + 1])
        else:
            idx, total, prev_id, next_id = _chat_navigation.get(
                mid, (0, 0, None, None),
            )
        # Enrich attach pointer rows with embed stats so the
        # AttachCard can render "EMBEDS N messages · M tokens"
        # without a follow-up round trip. Cost = one O(1)
        # commit-file read per attach pointer.
        enriched = {**m,
            "sibling_index": idx,
            "sibling_total": total,
            "prev_sibling_id": prev_id,
            "next_sibling_id": next_id,
        }
        if m.get("function") == "attach":
            _ref, _man, _src = _ainfo(m)
            if _src:
                _n, _tok = _astats(_ddb(), session_id, _src)
                attach_dict = dict(m.get("attach") or {})
                attach_dict.setdefault("source_commit_id", _src)
                if _n is not None:
                    attach_dict["embed_count"] = _n
                if _tok is not None:
                    attach_dict["embed_tokens"] = _tok
                enriched["attach"] = attach_dict
        shown.append(enriched)
    return shown


def _execution_rows(chain: list, all_msgs: list, by_id_all: dict) -> list:
    """The caller-linked execution rows under the chain's assistant replies, depth-first."""
    # caller 链执行行：agent 调函数的层级树（paper_agent → 子调用 →
    # … → LLM 叶子）不在线性对话链上，靠 caller 挂在链上的回复。把
    # 这些行补进 payload——前端 conv-mapper 把它们折成调用树喂给时
    # 间线渲染，不作为顶层消息显示。spawn 分支根（role=user）和
    # attach 指针（父是 assistant）天然不匹配，不会被带进来。
    _chain_ids = {m.get("id") for m in chain}
    _kids_by_caller: dict = {}
    for _m in all_msgs:
        _c = _m.get("caller")
        if _c and _c != "ROOT":
            _kids_by_caller.setdefault(_c, []).append(_m)

    def _collect_exec_rows(mid, acc):
        parent = by_id_all.get(mid) or {}
        for _k in _kids_by_caller.get(mid, []):
            _is_tool = _k.get("role") == "tool" and _k.get("function")
            _is_leaf = (
                _k.get("role") == "assistant"
                and parent.get("role") == "tool"
            )
            if not (_is_tool or _is_leaf):
                continue
            if _k.get("id") in _chain_ids:
                continue
            acc.append(_k)
            _collect_exec_rows(_k.get("id"), acc)

    _exec_rows: list = []
    for _m in chain:
        # A top-level runtime card already carries its complete caller
        # subtree in context_tree. Re-appending those descendants here
        # makes conv-mapper see the rebuilt root as role=assistant rather
        # than its original role=tool, so direct LLM children fail the
        # call-tree test and leak out as ordinary assistant chat bubbles.
        if (_m.get("role") == "assistant"
                and _m.get("display") != "runtime"):
            _collect_exec_rows(_m.get("id"), _exec_rows)
    return _exec_rows


async def _session_graph(ws, session_id, head, raw_msgs: list) -> list:
    """The DAG dump: full layout, annotations only, or nothing, per the client's history mode."""
    from openprogram.state.store.session.graph.builder import build_session_graph
    bounded_history = getattr(ws, "_bounded_history", False)
    # Plain transcripts need neither drawing geometry nor graph metadata.
    # Compaction and spawn/attach cards still share the graph's semantic
    # filtering, but only an actual DAG viewport needs its coordinates.
    needs_graph_annotations = any(
        m.get("covers_ids") or m.get("source") == "agent_spawn"
        or m.get("function") == "attach"
        for m in raw_msgs
    )
    if not bounded_history:
        graph = await asyncio.to_thread(
            build_session_graph, session_id, head, messages=raw_msgs
        )
    elif needs_graph_annotations:
        graph = await asyncio.to_thread(
            build_session_graph, session_id, head, messages=raw_msgs,
            include_layout=False,
        )
    else:
        graph = []
    return graph


def _annotate_spawned_from(shown: list, graph: list, raw_msgs: list) -> None:
    """Mark each spawned sub-branch's root, in the graph and in ``shown``, with the turn that spawned it."""
    # Reverse-link each spawned sub-branch's root user msg back
    # to the main-lane turn that produced it, so the frontend
    # can render a "Spawned from: <branch>" card at the top of
    # the sub branch (mirror of the AttachCard on main).
    _annotate_spawn_origin(graph, raw_msgs)
    # Mirror the spawned_from annotation onto ``shown`` (what the
    # chat list renders), keyed by id.
    _spawn_by_id = {
        n["id"]: n["spawned_from"]
        for n in graph if n.get("spawned_from")
    }
    for m in shown:
        sf = _spawn_by_id.get(m.get("id"))
        if sf:
            m["spawned_from"] = sf


async def _page_history_window(ws, cmd: dict, session_id, head, shown: list, chain: list, is_history_page: bool):
    """Install a history snapshot and cut the requested window: ``(shown, history, page_sent)``."""
    history = None
    if getattr(ws, "_history_protocol", 0) == 1:
        from openprogram.interfaces.server.ws_errors import OperationError
        try:
            from openprogram.interfaces.server.session_history import HistorySnapshot, install_snapshot
            snapshot = await _session_io(HistorySnapshot, session_id, head, shown, {m.get("id") for m in chain})
            install_snapshot(ws, snapshot)
            shown, history = await _session_io(snapshot.page, before=cmd.get("history_before"), after=cmd.get("history_after"), around=cmd.get("history_around"), initial=not is_history_page)
        except ValueError as exc:
            raise OperationError("invalid_request", scope="session", retryable=True) from exc
        if is_history_page:
            await ws.send_text(json.dumps({"type": "session_history_page", "data": {
                "id": session_id, "messages": shown, "history": history,
                "request_id": cmd.get("request_id"), "action": "load_session",
            }}, ensure_ascii=False, default=str))
            return shown, history, True
    return shown, history, False


def _context_stats_for_load(conv: dict):
    """Current-version context stats with the cached breakdown folded in: ``(stats, refresh_after_load)``."""
    _stats = conv.get("_last_context_stats") or {}
    if _stats.get("context_usage_version") != 2:
        conv.pop("_last_context_stats", None)
        conv.pop("_last_context_breakdown", None)
        conv.pop("_chat_usage", None)
        _stats = {}
    refresh_context_after_load = not conv.get("_last_context_breakdown")
    _bd = conv.get("_last_context_breakdown")
    if _bd and "breakdown" not in _stats:
        _stats = {**_stats, "type": "context_stats", "breakdown": _bd}
        conv["_last_context_stats"] = _stats
    return _stats, refresh_context_after_load


async def _send_session_loaded(ws, _s, cmd: dict, conv: dict, session_id, shown: list, history, graph: list, head, raw_msgs: list):
    """Send the ``session_loaded`` frame: transcript, graph, settings and run state; returns ``(run_task, refresh_context_after_load)``."""
    from openprogram.runtime.context.session_db import default_db as _ddb
    from openprogram.runtime.conversation.session_config import (
        load_session_run_config,
        permission_from_config,
        project_defaults,
    )
    from openprogram.host.sandbox import ui_state as _sandbox_ui
    run_cfg = load_session_run_config(conv["id"])
    from openprogram.runtime.permissions import permission_state
    _permission_state = permission_state(session_id)
    _effective_permission = permission_from_config(
        run_cfg, default=project_defaults(conv["id"]).get("permission_mode"))
    _run_seq = _s._next_run_seq()
    _run_active = _s._is_run_active(conv["id"])
    _run_task = _s._run_identity(conv["id"]) if _run_active else None
    _stats, refresh_context_after_load = _context_stats_for_load(conv)
    _db_sess = _ddb().get_session(session_id) or {}
    from openprogram.programs.tools.planning.goal.presentation import history_projection
    tree_data = {}  # tree Context retired — execution trace lives in SessionDB DAG nodes
    await ws.send_text(json.dumps({
        "type": "session_loaded",
        "data": {
            "request_id": cmd.get("request_id"),
            "action": "load_session",
            "id": conv["id"],
            "title": _db_sess.get("title", ""),
            "messages": shown,
            **({"history": history} if history is not None else {}),
            "graph": [] if getattr(ws, "_bounded_history", False) else graph,
            "head_id": head,
            "spawned_branch": _spawned_branch(head, raw_msgs),
            # Lineage of a conversation made with "Copy conversation":
            # the transcript's "Copied from" banner.
            "branched_from": _branched_from(_db_sess),
            "context_tree": tree_data,
            "provider_info": _s._get_provider_info(session_id),
            "context_stats": _stats or None,
            "channel": _db_sess.get("channel"),
            "account_id": _db_sess.get("account_id"),
            "environment_id": _db_sess.get("environment_id"),
            "peer": _db_sess.get("peer"),
            "peer_display": _db_sess.get("peer_display"),
            "source": _db_sess.get("source"),
            # Session goal (/goal) — the composer's GoalChip hydrates
            # from this on load; live changes ride goal_update frames.
            "goal": history_projection((_db_sess.get("extra_meta") or {}).get("goal"), session_id),
            # The task lists drawn under the turns that changed the plan
            # hydrate from these; live changes ride todos_update frames.
            "todos": _session_todos(session_id),
            "todo_plans": _session_todo_plans(session_id),
            "settings": {
                "tools_override": run_cfg.tools_override,
                "thinking_effort": run_cfg.thinking_effort,
                "permission_mode": _effective_permission,
                "permission_version": _permission_state["version"],
                "additional_working_dirs": run_cfg.additional_working_dirs,
                **_sandbox_ui(run_cfg.sandbox_enabled),
            },
            "run_active": _run_active,
            "run_task": _run_task,
            "run_seq": _run_seq,
            "status": (_ddb().get_session(session_id) or {}).get("status", "idle"),
        },
    }, default=str))
    return _run_task, refresh_context_after_load


async def _send_running_task_state(ws, _s, session_id, _run_task) -> None:
    """Follow up with the live running task, or clear the slot of a turn that ended during the load."""
    # The run guard owns stale runtime and reservation cleanup. A quiet
    # live task must retain its execution identity for reconnect controls.
    _followup_seq = _s._next_run_seq()
    with _s._running_tasks_lock:
        task = _s._running_tasks.get(session_id)
        task_info = dict(task) if task else None
    task_info = _s._canonical_foreground_task(session_id) or task_info
    if _run_task and not task_info:
        # The turn this load reported ended while the load was in
        # flight; its broadcast clear may have reached the client before
        # the running slot did, so close that slot by name here.
        await ws.send_text(json.dumps({
            "type": "running_task_clear",
            "data": {"session_id": session_id, "run_seq": _followup_seq, **{
                key: value for key, value in _run_task.items() if value}},
        }))
    if task_info:
        # Live partial-tree dump retired with the tree-Context
        # event system. The DAG nodes the function has produced so
        # far are already queryable via the GraphStore.
        await ws.send_text(json.dumps({
            "type": "running_task",
            "data": {
                "session_id": session_id,
                "msg_id": task_info["msg_id"],
                "func_name": task_info["func_name"],
                "execution_id": task_info.get("execution_id"),
                "status_version": task_info.get("status_version"),
                "started_at": task_info["started_at"],
                "display_params": task_info.get("display_params", ""),
                "partial_tree": None,
                "stream_events": task_info.get("stream_events", []),
                "status": task_info.get("status"),
                "reason_code": task_info.get("reason_code"),
                "run_seq": _followup_seq,
            },
        }, default=str))


async def _replay_open_waits(ws, _s, session_id) -> None:
    """Resend the question and system-access frames of waits still open for this session."""
    # Reconnect recovery (user-input-requests.md): a function may be
    # blocked in runtime.ask right now. The live ``question.asked`` frame
    # already fired before this client (re)connected, so its card was
    # never drawn / was lost on refresh — replay any still-pending
    # questions for this session as the SAME frame the live path sends,
    # so the frontend's existing card logic redraws with no extra round trip.
    try:
        from openprogram.runtime.execution import default_store
        from openprogram.runtime.execution.waits import DurableWaitStore, question_frame_data
        for q in DurableWaitStore(default_store()).list_open(session_id=session_id):
            request = dict(q.request)
            execution = default_store().get_execution(q.execution_id)
            if q.kind == "system_access":
                await ws.send_text(json.dumps({
                    "type": "system_access.waiting",
                    "data": {
                        "id": q.wait_id,
                        "wait_id": q.wait_id,
                        "kind": q.kind,
                        "session_id": session_id,
                        "execution_id": q.execution_id,
                        "required_capabilities": list(request.get("required_capabilities", [])),
                        "capabilities": list(request.get("capabilities", [])),
                        "wait_generation": q.claim_generation,
                        "expected_version": execution.status_version if execution is not None else 0,
                        "expires_at": q.expires_at,
                        "reason_code": "system_access_required",
                        "live": False,
                    },
                }, default=str))
                continue
            await ws.send_text(json.dumps({
                "type": "question.asked",
                "data": question_frame_data(
                    q, session_id=session_id,
                    expected_version=execution.status_version if execution is not None else 0,
                ),
            }, default=str))
    except Exception as e:
        _s._log(f"[load_session] question replay {session_id}: {e}")


async def _send_session_not_found(ws, cmd: dict, session_id) -> None:
    """Tell the client the session does not exist."""
    # No such session: the client drops the row or tab it asked for
    # instead of showing an empty "New conversation" in its place.
    await ws.send_text(json.dumps({
        "type": "operation_error",
        "data": {
            "action": "load_session",
            "code": "session_not_found",
            "session_id": session_id,
            "request_id": cmd.get("request_id"),
        },
    }, default=str))


async def handle_load_session(ws, cmd: dict):
    """Hydrate a session: linear chain under HEAD + full DAG dump + running-task probe."""
    from openprogram.interfaces.server import server as _s
    session_id = cmd.get("session_id")
    # A load does not mark the session as viewed: split panes and
    # background loads read sessions nobody is looking at. Only
    # ``mark_session_read`` records the focus that keeps a finishing turn
    # from leaving an unread dot.
    is_history_page = any(key in cmd for key in ("history_before", "history_after", "history_around", "history_latest"))
    if is_history_page:
        if await _serve_cached_history_page(ws, cmd, session_id):
            return
    conv = await _find_or_hydrate_session(_s, session_id)
    if conv is None and is_history_page:
        from openprogram.interfaces.server.ws_errors import OperationError
        raise OperationError("invalid_request", scope="session", retryable=True)
    if not conv:
        await _send_session_not_found(ws, cmd, session_id)
        return
    # A chat turn can advance this mirror while the bounded hydration
    # reads run in worker threads. Keep the load payload tied to the
    # captured request, but never let an older load overwrite a newer
    # in-memory head when it returns.
    load_started_head = conv.get("head_id")
    conv_snapshot = {**conv, "messages": list(conv.get("messages") or [])}
    # Hydration is also a recovery boundary.  A worker restart marker can
    # be written during the handoff from a resolved wait to its next
    # continuation; canonical execution state must repair that projection
    # before messages are serialized for the client.
    try:
        from openprogram.runtime.execution.dag import reconcile_session_projection
        if not is_history_page:
            await _session_io(
                reconcile_session_projection, session_id
            )
    except Exception as exc:
        _s._log(f"[load_session] canonical projection repair {session_id}: {exc}")
    from openprogram.runtime.context.git import head_or_tip
    from openprogram.runtime.context.session_db import default_db as _db_for_load
    _db_load = _db_for_load()
    _persisted_head, raw_msgs, all_msgs = await _read_session_messages(_db_load, conv, conv_snapshot)
    head = _persisted_head or head_or_tip(conv_snapshot, all_msgs)
    head = _resolve_head(cmd, is_history_page, head, raw_msgs, all_msgs)
    chain = await _active_branch_chain(_db_load, session_id, head, all_msgs)
    chain = _splice_attach_pointers(chain, all_msgs)
    chain = _splice_runtime_placeholders(chain, all_msgs)
    # Rebuild Function-call cards from top-level Agent method
    # code nodes (manual /run, fn-form). Without this a refreshed
    # manual call renders as a bare system-text blob instead of the
    # RuntimeBlock card the live runtime shows; its nested sub-nodes
    # are absorbed into the card's context_tree.
    chain = await _session_io(_rebuild_runtime_cards, chain, all_msgs, conv["id"])
    with _s._sessions_lock:
        current_conv = _s._sessions.get(session_id)
        if not is_history_page and current_conv is conv and conv.get("head_id") == load_started_head:
            conv["messages"] = chain
            conv["head_id"] = head
    by_id_all = _messages_by_id(all_msgs)
    shown = _rows_with_sibling_navigation(chain, all_msgs, by_id_all, conv["id"])
    shown.extend(_execution_rows(chain, all_msgs, by_id_all))

    graph = await _session_graph(ws, conv["id"], head, raw_msgs)
    _annotate_spawned_from(shown, graph, raw_msgs)
    shown = splice_compaction_event_rows(shown, graph, all_msgs)
    shown = _truncate_tool_outputs_for_wire(shown)
    shown, history, page_sent = await _page_history_window(ws, cmd, session_id, head, shown, chain, is_history_page)
    if page_sent:
        return

    _run_task, refresh_context_after_load = await _send_session_loaded(
        ws, _s, cmd, conv, session_id, shown, history, graph, head, raw_msgs,
    )
    # Cold context accounting is cache warming, not session hydration.
    # refresh_context_stats broadcasts its own context_stats frame after
    # the computation finishes, so the transcript can render first.
    if refresh_context_after_load:
        await asyncio.to_thread(_s.refresh_context_stats, session_id)
    await _send_running_task_state(ws, _s, session_id, _run_task)
    await _replay_open_waits(ws, _s, session_id)
