"""``context="fresh"``: hand the task to a new agent that starts from a brief.

The new agent is an ordinary spawned agent (``agent(start_from="clean")``)
of this conversation's model and settings. It sees the brief, the target's
guide and nothing of the conversation; it works with ``computer_use_agent``
itself and only its final reply comes back.

Spawned turns cannot ask for approval, so the call carries its own: the
approval this call received for its app or VM is written as a conversation
rule for as long as the new agent runs, unless such a rule already exists.
"""
from __future__ import annotations

from typing import Any

from openprogram.programs._host.execution import ToolReturn

def nested() -> bool:
    """Whether this call already runs inside a spawned agent."""
    from openprogram.programs.tools.agents.send_message.send_message.depth import current_chain_generations
    return current_chain_generations() > 0


def prompt(target: str, args: dict, brief: str, guide: str) -> str:
    lines = [brief.strip(), "",
             f"Do this with the computer_use_agent tool, target=\"{target}\""
             + (f", args={{\"app\": \"{args['app']}\"}}" if args.get("app") else "") + ". "
             "The guide for this target follows, so start acting right away. When you are done, reply with the "
             "result only: what you found or changed, and anything that did not work.",
             "", guide]
    return "\n".join(lines)


def _carried_rule(session: str, args_for_rule: dict) -> str | None:
    """Add the call's approval as a conversation rule; the rule to take back afterwards, if added."""
    from openprogram.runtime.permissions.approval import _persist_session_allow_rule
    from openprogram.runtime.conversation.session_config import load_session_run_config
    from openprogram.runtime.permissions.rule import exact_rule_for_call, rule_to_string

    value = exact_rule_for_call("computer_use_agent", args_for_rule)
    if value is None or not session:
        return None
    serialized = rule_to_string(value)
    rules = load_session_run_config(session).permission_rules
    if rules is not None and serialized in rules.allow:
        return None
    return serialized if _persist_session_allow_rule(session, "computer_use_agent", args_for_rule) else None


def _take_back(session: str, serialized: str) -> None:
    from openprogram.runtime.conversation.session_config import load_session_run_config, save_session_run_config
    from openprogram.runtime.context.session_db import default_db

    row = default_db().get_session(session)
    rules = load_session_run_config(session).permission_rules
    if row is None or rules is None or serialized not in rules.allow:
        return
    save_session_run_config(session, agent_id=row.get("agent_id"), permission_rules={
        "allow": [rule for rule in rules.allow if rule != serialized],
        "deny": list(rules.deny), "ask": list(rules.ask),
    })


def run(target: str, args: dict, brief: str, guide: str, session: str, *, needs_grant: bool) -> ToolReturn:
    from openprogram.programs.tools.agents.agent.agent.agent import _agent_impl

    if nested():
        return ToolReturn(text="Error: this agent was itself started fresh; do the work here with context=\"inherit\".",
                          is_error=True)
    if not brief.strip():
        return ToolReturn(text="Error: context=\"fresh\" needs brief: the task, what is already known (names, values, "
                               "where things are) and what to report back. The new agent sees nothing else.",
                          is_error=True)
    carried = _carried_rule(session, {"target": target, "args": args}) if needs_grant else None
    try:
        reply: Any = _agent_impl(prompt(target, args, brief, guide),
                                 description=f"computer_use_agent {target}", start_from="clean")
    finally:
        if carried:
            _take_back(session, carried)
    text = str(reply or "").strip()
    failed = text.startswith(("[agent error", "[agent refused"))
    return ToolReturn(text=text or "The agent finished without a reply.", is_error=failed)


__all__ = ["nested", "prompt", "run"]
