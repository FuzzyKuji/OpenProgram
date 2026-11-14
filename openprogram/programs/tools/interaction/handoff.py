"""handoff — give a piece of work to another of the user's conversations."""
from __future__ import annotations

from openprogram.programs._host.runtime import function


@function(
    name="handoff",
    description=(
        "Hand a piece of work to another of the user's conversations when that conversation owns "
        "the job (one owner per stage). `to` is the conversation's id or exact title, an Agent's "
        "name or id when that Agent has one other conversation, or a SID:HEAD address; "
        "list_agents scope=\"all\", if you have it, shows them all. The message is delivered "
        "asynchronously: the other conversation handles it as its next turn, and its answer comes "
        "back to this conversation as a new message later, so do not wait for it. The message is "
        "labelled with this conversation's title. Chains of handoffs are limited, so do the work "
        "here when it belongs here."
    ),
    toolset=["always_on"],
    # send_message took its place for the model: it reaches an Agent by
    # name, and its reply waits as a notice without a timeout. Kept for
    # the handoffs already stored (always_on/handoff.py replays them).
    expose=False,
)
def handoff(to: str, message: str) -> str:
    """Send ``message`` to the conversation ``to`` names (id, title, Agent or SID:HEAD)."""
    return _handoff_impl(to, message)


def _handoff_impl(to: str, message: str) -> str:
    from openprogram.runtime.agent.turn_request import get_turn_request
    from openprogram.runtime.conversation.always_on import handoff as handoffs
    from openprogram.runtime.execution.run_control import get_current_session_id
    from openprogram.runtime.permissions.identity import check_in
    sid = get_current_session_id()
    if not sid:
        return "[handoff error] no active conversation"
    request = get_turn_request()
    try:
        sent = handoffs.send(sid, to, message,
                             msg_id=getattr(request, "user_msg_id", None),
                             # A check-in runs off the head but speaks for its conversation.
                             advance_head=(bool(getattr(request, "advance_head", True)) or check_in(request))
                             and not getattr(request, "spawned_from_session", None),
                             resumes=getattr(request, "resumes_message_id", None),
                             goal_turn=bool(getattr(request, "goal_trigger", False)))
    except handoffs.HandoffRefused as exc:
        return f"[handoff refused] {exc}"
    return (f"Sent to “{sent['target_title']}” ({sent['target_id']}), hop {sent['hop']} of "
            f"{sent['max_hops']}. Its answer will arrive here as a new message; continue meanwhile.")
