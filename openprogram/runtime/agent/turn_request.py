"""The request one persistent turn runs under, and the request in force now.

``TurnRequest`` carries what a turn needs and what may not be downgraded
below it: the session and Agent, the source, the permission mode and rules,
and the speaker's authority. The conversation engine builds one per turn and
binds it with :func:`set_turn_request`; the call core reads it back, binds a
standalone one around a plain library call (``runtime_scope``) and derives
the request an inner ``AgentSession``'s tools are gated by
(:func:`inner_turn_request`). Nothing bound means no turn is running.

The types depend only on the standard library, so every layer can import
them; ``openprogram.runtime.conversation.turn_runtime`` re-exports them.
"""
from __future__ import annotations

import contextvars
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

PermissionMode = Literal["ask", "acceptEdits", "plan", "auto", "bypass"]


# Sentinel: "caller did not specify predecessor, dispatcher should pick"
# vs explicit ``None`` which means "fork from root". The two cases need
# different behavior — see TurnRequest.caller.
class _InheritParent:
    __slots__ = ()
    def __repr__(self) -> str: return "<INHERIT>"


INHERIT_PARENT: Any = _InheritParent()


@dataclass
class TurnRequest:
    session_id: str
    user_text: str
    agent_id: str
    source: str                                  # "tui" / "web" / "wechat" / ...
    peer_display: Optional[str] = None
    peer_id: Optional[str] = None
    model_override: Optional[str] = None
    thinking_effort: Optional[str] = None
    permission_mode: PermissionMode = "ask"
    # Optional explicit tool whitelist that overrides the agent's
    # configured tools. Channels can opt out of risky tools per turn
    # (e.g. wechat shouldn't ever hit destructive bash).
    tools_override: Optional[list[str]] = None
    # Branching: predecessor of the user message we're about to write.
    #   - INHERIT_PARENT (default) → dispatcher uses the active
    #     branch's tail (head_id walk). Normal append.
    #   - explicit string → fork sibling branch off that message.
    #     Retry / edit flows pass the parent of the message being
    #     replaced.
    #   - explicit None → root-level fork (the very first turn of a
    #     new conversation tree, or "retry the very first user
    #     message" case from context/git/dag.py).
    # Mirrors Claude Code's parentUuid chain: append-only, no mutation
    # of historical messages.
    branch_from: Any = INHERIT_PARENT
    # When the caller has already linearized "the branch the user
    # currently sees" (e.g. webui has its in-memory active-branch
    # walk), pass it here so the dispatcher uses it as the LLM
    # context instead of re-querying SessionDB. Each entry is a row-
    # shaped dict with role/content/timestamp/id at minimum. Passing
    # None means "load history from SessionDB via get_branch".
    history_override: Optional[list[dict]] = None
    # Caller-supplied id for the user message. When omitted dispatcher
    # mints one. Useful for webui where the WS handler pre-emits a
    # ``chat_ack`` envelope tied to a frontend-known msg_id.
    user_msg_id: Optional[str] = None
    # When True, the caller has already persisted the user message
    # under ``user_msg_id`` and advanced head — dispatcher should
    # NOT re-write it. Used by webui where the WS handler appends
    # the user msg before kicking off the agent thread.
    user_already_persisted: bool = False
    # Per-turn speed / priority tier ("priority" = Fast, "flex" =
    # cheaper-slower, None = provider default). Set by the composer's
    # speed pill; flows to ``SimpleStreamOptions.service_tier`` and on
    # to the provider request body. Falls back to the session's stored
    # value when the caller doesn't pin one for this turn.
    service_tier: Optional[str] = None
    # Multimodal attachments to include in the user message. Each
    # entry is ``{"type": "image", "data": <base64>, "media_type":
    # "image/png"}`` (or jpeg/webp/gif). The dispatcher attaches
    # these as ImageContent blocks alongside the text TextContent.
    # Providers that don't support vision will reject; the dispatcher
    # surfaces that as an error envelope, not a crash.
    attachments: Optional[list[dict]] = None
    # Spawn caller: when this turn STARTS a new branch that was spawned by
    # another node (send_message to="new"), this is the id of the
    # spawning node. The dispatcher sets the new branch-root's ``caller`` to
    # it (instead of ROOT), so the branch is an explicit spawn — otherwise a
    # ROOT-parented branch root with no predecessor gets seq-stitched into a
    # sibling branch and the chat view flattens all branches into one.
    # See docs/design/runtime/dag/overview.md §2.3.
    spawn_caller: Optional[str] = None
    # 用户配的权限规则（allow/deny/ask，各来源合并后），供 _gated_execute 的
    # _match_rule 判定。见 docs/design/runtime/permission-model.md §3.4。
    # 类型是 session_config.PermissionRules，这里用 Any 避免循环 import。
    permission_rules: Any = None
    # HEAD single-writer (context/compaction.md §5): a same-session
    # SPAWNED turn (task / send_message sub-agent) is machinery, not
    # the conversation the user is on — it must never move the session
    # head. With head stolen mid-run, every head-following surface (the
    # transcript mirror, branches_list broadcasts) switched to the
    # agent's window until the outer turn's reply moved it back.
    advance_head: bool = True
    # 路径安全的额外工作目录集（acceptEdits / safetyCheck 用，§3.5）。
    additional_working_dirs: list = field(default_factory=list)
    # Runtime-owned provenance and authorization. Appended after all existing
    # fields so external positional constructors retain their historical
    # meaning. Production entry points construct these explicitly; internal
    # reconstruction that loses them may render/reply but cannot perform a
    # host side effect.
    speaker_kind: Optional[str] = None
    speaker_id: Optional[str] = None
    speaker_display: Optional[str] = None
    principal_id: Optional[str] = None
    authority_tier: Optional[Literal["owner", "paired"]] = None
    interaction: Optional[str] = None
    response_format: Any = None
    structured_output: Any = None
    structured_output_mode: Optional[str] = None
    structured_output_attempt: Optional[int] = None
    # Default DAG slice for agentic functions invoked during this turn.
    # Kept at the end for positional-constructor compatibility. An explicit
    # decorator value takes precedence.
    render_range: Optional[dict[str, int]] = None
    # Validated, turn-scoped descriptor and DOM/ARIA preview for a visible
    # OpenProgram desktop surface. Raw renderer refs never reach providers.
    surface_context: Optional[dict[str, Any]] = None
    # Session that owns ``spawn_caller`` when it is outside this turn's
    # session.  Appended for positional-constructor compatibility.  The node
    # id remains the real caller edge; this field supplies its namespace for
    # persisted provenance and cross-session rendering.
    spawned_from_session: Optional[str] = None
    profile_snapshot: Optional[dict[str, Any]] = None
    goal_context: Optional[dict] = None
    goal_trigger: bool = False
    goal_previous_execution: Optional[str] = None
    goal_verification: Optional[str] = None

    memory_policy_override: Optional[dict[str, Any]] = None
    memory_policy_snapshot: Optional[dict[str, Any]] = None
    memory_degraded_reason: Optional[str] = None
    # A job_followup's per-job summary (agent/job/notices.py
    # ``notice_items``), stamped on its user message so the chat draws one
    # row per finished agent instead of the notice text.
    notice: Optional[list[dict[str, Any]]] = None
    # The turn that continues a run a worker restart interrupted. Its
    # prompt is an instruction to the model, not something the owner said,
    # so the chat shows the continued reply without a user message.
    restart_resume: bool = False
    # An always-on check-in: what the owner should see it reports mid-turn
    # with ``always_on_report``, which marks the conversation unread then.
    # Its end leaves the unread dot alone, so a check-in that finds nothing
    # stays quiet in the sidebar.
    quiet_finish: bool = False

    def __post_init__(self) -> None:
        if self.profile_snapshot is not None:
            if not isinstance(self.profile_snapshot, dict):
                raise ValueError("profile_snapshot must be a dict")
            self.profile_snapshot = deepcopy(self.profile_snapshot)


current_turn_request: contextvars.ContextVar[Optional[Any]] = (
    contextvars.ContextVar("openprogram_current_turn_request", default=None)
)


def set_turn_request(req: Any):
    return current_turn_request.set(req)


def get_turn_request() -> Optional[Any]:
    return current_turn_request.get(None)


def reset_turn_request(token) -> None:
    try:
        current_turn_request.reset(token)
    except ValueError:
        pass


def inner_turn_request(source: str) -> Optional[Any]:
    """Derive the request an inner AgentSession's tools are gated by.

    Inherits the outer request's authority through ``runtime_authority``
    (which pins ``interaction="non-interactive"`` and the runtime speaker),
    and keeps source/permission_mode/permission_rules so neither the hard
    constraints nor a deny rule can be dropped by descending a level.
    """
    outer = get_turn_request()
    if outer is None:
        return None
    from openprogram.runtime.permissions.authority import runtime_authority

    authority = runtime_authority(outer, source)
    if not authority:
        return None
    return TurnRequest(
        session_id=getattr(outer, "session_id", "") or "",
        user_text="",
        agent_id=getattr(outer, "agent_id", "main") or "main",
        # A nested program cannot widen the outer source. agent_spawn and
        # cron stay themselves so their hard-constraint sets keep applying.
        source=getattr(outer, "source", "web") or "web",
        permission_mode=getattr(outer, "permission_mode", None),
        permission_rules=getattr(outer, "permission_rules", None),
        surface_context=getattr(outer, "surface_context", None),
        additional_working_dirs=list(
            getattr(outer, "additional_working_dirs", None) or ()
        ),
        **authority,
    )


__all__ = [
    "PermissionMode", "INHERIT_PARENT", "TurnRequest",
    "current_turn_request", "set_turn_request", "get_turn_request",
    "reset_turn_request", "inner_turn_request",
]
