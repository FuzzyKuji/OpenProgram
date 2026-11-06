"""always_on_report — an always-on conversation tells the user what it found."""
from __future__ import annotations

from openprogram.programs._host.runtime import function


@function(
    name="always_on_report",
    description=(
        "Report a finding to the user from this always-on conversation's check-in. "
        "The user gets a notification, the report is kept with this conversation, and "
        "it is also sent to the channel conversations chosen for this Agent. Use once per "
        "check-in, only for something worth their attention: a short title, the "
        "essentials in body, and any links."
    ),
    toolset=["always_on"],
)
def always_on_report(title: str, body: str = "", links: list[str] | None = None) -> str:
    """Save the report and notify the user."""
    from openprogram.runtime.conversation.always_on import report
    from openprogram.runtime.execution.run_control import get_current_session_id
    sid = get_current_session_id()
    if not sid:
        return "[always_on_report error] no active conversation"
    try:
        row = report(sid, title, body, links)
    except ValueError as exc:
        return f"[always_on_report error] {exc}"
    sending = len(row.get("deliveries") or [])
    return f"Reported: {row['title']}" + (f" (sending to {sending} channel conversation(s))" if sending else "")
