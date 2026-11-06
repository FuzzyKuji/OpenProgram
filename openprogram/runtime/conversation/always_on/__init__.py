"""Always-on: an Agent configuration that makes its conversations wake.

Every conversation that uses an always-on Agent wakes on the Agent's
schedule, works on the standing goal as an ordinary chat Goal there, does
read-only check-ins while it has no unfinished Goal, and reports findings
with ``always_on_report``, in the App and to the channel conversations
chosen for the Agent. Quiet hours and wake days hold scheduled wakes back,
and ``handoff`` gives work to another conversation of the owner.

Design: docs/reference/design/runtime/always-on-agents.md
"""
from openprogram.runtime.conversation.always_on.delivery import channel_targets
from openprogram.runtime.conversation.always_on.handoff import HandoffRefused
from openprogram.runtime.conversation.always_on.runtime import (
    WakeRefused,
    agent_for_session,
    join,
    report,
    status,
    wake,
)

__all__ = ["HandoffRefused", "WakeRefused", "agent_for_session", "channel_targets",
           "join", "report", "status", "wake"]
