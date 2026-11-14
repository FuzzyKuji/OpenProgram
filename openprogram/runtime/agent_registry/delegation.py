"""Which saved Agents other agents may start, and how.

Two settings on an Agent decide it (``AgentSpec.delegation`` and
``AgentSpec.isolation``); an empty value means the default here, so no
stored ``agent.json`` is rewritten when these settings appear.

* ``delegation``: "on" lists the Agent in the ``agent`` tool's description
  and lets ``agent(agent=…)`` start it. The default is on for an Agent
  with tools and off for one without (``tools.mode == "none"``: Decision,
  Lightweight helper), whose use is a single model call, not a task. This
  is OpenCode's ``mode: primary | subagent | all`` reduced to one switch.
* ``isolation``: "worktree" or "none" fixes where it works when another
  agent starts it (Claude Code's agent frontmatter ``isolation``). The
  default rule: a background helper that can edit files works in its own
  worktree when the folder is a git repository; a foreground helper (the
  caller waits, so there is one writer) and a read-only one share the
  folder. A call's own ``isolation`` wins over both.

An Agent never gains permission by being delegated to: the helper runs
under its caller's permission mode and rules, and its own tool policy can
only narrow what it may use (Codex ``role.rs``: a role narrows, never
widens).
"""
from __future__ import annotations

from typing import Iterable, Optional

from openprogram.runtime.agent_registry import manager

# Tools that change files or run commands; an Agent with any of them is a
# writer for the default isolation rule.
WRITE_TOOLS = frozenset({
    "write", "edit", "apply_patch", "bash", "exec", "shell", "execute_code",
    "write_stdin", "notebook_edit",
})
ROSTER_MAX = 30


def delegation_enabled(spec: manager.AgentSpec) -> bool:
    if spec.delegation in ("on", "off"):
        return spec.delegation == "on"
    return (spec.tools or {}).get("mode") != "none"


def writes_files(spec: manager.AgentSpec) -> bool:
    """Whether the Agent's tool policy lets it change files or run commands."""
    tools = spec.tools or {}
    mode = tools.get("mode") or "automatic"
    if mode == "none":
        return False
    disabled = set(tools.get("disabled") or ())
    if mode == "selected":
        allowed = set(tools.get("allowed") or ())
        return bool((allowed - disabled) & WRITE_TOOLS)
    return not WRITE_TOOLS <= disabled


def isolation_for(
    spec: Optional[manager.AgentSpec], *, requested: str, background: bool,
) -> tuple[str, bool]:
    """``(isolation, from_default_rule)`` for a helper about to start.

    ``isolation`` is "worktree" or "" (shared folder). The second value is
    True when only the default rule asked for a worktree, in which case a
    folder that is not a git repository falls back to sharing instead of
    failing the call.
    """
    requested = (requested or "").strip().lower()
    if requested in ("worktree", "none"):
        return ("worktree" if requested == "worktree" else ""), False
    if spec is not None and spec.isolation in ("worktree", "none"):
        return ("worktree" if spec.isolation == "worktree" else ""), False
    if background and spec is not None and writes_files(spec):
        return "worktree", True
    return "", False


def find(ref: str, specs: Optional[Iterable[manager.AgentSpec]] = None) -> Optional[manager.AgentSpec]:
    """The Agent ``ref`` names: its id, else its name (case-insensitive)."""
    needle = (ref or "").strip()
    if not needle:
        return None
    rows = list(specs) if specs is not None else manager.list_all()
    for spec in rows:
        if spec.id == needle:
            return spec
    folded = needle.casefold()
    named = [spec for spec in rows if (spec.name or "").casefold() == folded]
    return named[0] if len(named) == 1 else None


def roster(specs: Optional[Iterable[manager.AgentSpec]] = None) -> list[tuple[str, str, str]]:
    """``(id, name, description)`` of every Agent other agents may start,
    sorted by id so one Agent's edit moves no other line."""
    rows = list(specs) if specs is not None else manager.list_all()
    listed = sorted((s for s in rows if delegation_enabled(s)), key=lambda s: s.id)
    return [(s.id, s.name, s.description) for s in listed[:ROSTER_MAX]]
