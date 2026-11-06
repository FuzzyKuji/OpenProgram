"""Shared operation decisions, permission rules and hard constraints."""
from __future__ import annotations

from typing import Any

# A turn request: the conversation package's ``TurnRequest`` or any object
# with its fields. Permission code reads the fields; it never imports it.
TurnRequest = Any


# 即使 bypass 也强制审批的工具（提交计划要用户签字）。
_FORCE_APPROVAL_TOOLS = {"exit_plan_mode"}


def _self_update_install(name: str, args: dict | None) -> bool:
    """A self_update prepare or retry: it binds one exact candidate and must never
    become a project-wide allow rule; a later candidate needs its own owner decision."""
    if name != "self_update":
        return False
    from openprogram.programs.tools.system.self_update import APPROVED_ACTIONS, action_of
    return action_of(args) in APPROVED_ACTIONS


def _web_use_evaluates(args: dict | None) -> bool:
    """A web_use call that runs arbitrary JavaScript in a page, in any argument spelling."""
    if not isinstance(args, dict):
        return False
    nested = args.get("arguments") if isinstance(args.get("arguments"), dict) else {}
    return any(str(value or "").strip().lower() == "evaluate"
               for value in (args.get("action"), nested.get("action")))


def _page_script(name: str, args: dict | None) -> bool:
    """A call that runs JavaScript in a browser Page."""
    if name == "computer_use_agent":
        from openprogram.programs.tools.computer_use.computer_use_agent import evaluates
        return evaluates(args)
    return name == "web_use" and _web_use_evaluates(args)


def _session_poll(name: str, args: dict | None) -> bool:
    """write_stdin that only waits for output or sends Ctrl-C to the agent's own command."""
    if name != "write_stdin" or not isinstance(args, dict):
        return False
    return str(args.get("chars") or "") in {"", "\x03"}


def sends_on_behalf(name: str) -> bool:
    """A tool that puts something in front of other people for the user: an
    MCP tool the adapter marked (send_email, chat.postMessage, create_comment)."""
    from openprogram.programs._host.runtime import get
    return bool(getattr(get(name), "_sends_on_behalf", False))


def _held_outbound(name: str, req) -> bool:
    """The Agent holds what it sends as a draft the user approves."""
    if not sends_on_behalf(name):
        return False
    from openprogram.runtime.permissions.session_facts import facts
    return facts().holds_outbound(getattr(req, "agent_id", None) or "main")


def force_approval(name: str, args: dict | None) -> bool:
    """Calls that ask in every mode, whatever the rules say."""
    return name in _FORCE_APPROVAL_TOOLS or _self_update_install(name, args)


def page_script(name: str, args: dict | None) -> bool:
    """A page script reads everything a signed-in page holds, including what
    observations redact. Outside bypass it asks, unless the conversation
    allowed page scripts; the card shows it untruncated and never offers a
    project-wide rule."""
    return _page_script(name, args)


def one_shot_approval(name: str, args: dict | None) -> bool:
    """Calls whose approval covers this request only and never becomes an allow rule.

    Each message an Agent sends for the user is approved alone: approving one
    draft never approves the next.
    """
    return _self_update_install(name, args) or sends_on_behalf(name)


# Desktop control is granted per application (and a VM per endpoint): in the
# modes that ask, the first touch asks until an allow rule (this conversation
# or the project) names it. Bypass runs it and Auto reviews it like any other
# call. Calls the tool marks approval-free (list_apps, built-in browser Pages)
# skip this.
_APP_GRANT_TOOLS = {"computer_use_agent"}
# Rules written for the tool's earlier name still grant the same app.
_RULE_ALIASES = {"computer_use_agent": {"computer_use"}}
# auto 档下即便未声明 requires_approval 也仍要审批的高风险工具。
_RISKY_TOOLS = {"bash", "exec", "shell", "execute_code", "write_stdin"}
# Non-interactive worktree side effects mutate repository state outside the
# spawned agent's working directories, and those turns cannot ask approval.
_WORKTREE_TOOLS = {
    "worktree_create", "worktree_merge", "worktree_discard", "worktree_keep",
}
_WRITE_TOOLS = {"write", "write_file", "edit", "edit_file"}
_PATCH_PATH_PREFIXES = (
    "*** Add File: ",
    "*** Update File: ",
    "*** Delete File: ",
    "*** Move to: ",
)
_NON_INTERACTIVE_SOURCES = {"agent_spawn", "cron", "scheduler", "mcp"}
_SCHEDULED_MEMORY_TOOLS = {"memory_search", "memory_get", "memory_update"}
_SCHEDULED_ALLOWED_TOOLS = {
    "read", "read_file", "grep", "glob", "list", "list_files", "tool_search",
} | _SCHEDULED_MEMORY_TOOLS


def _match_rule(rules, tool_name: str, args: dict) -> "str | None":
    """匹配用户配的权限规则，返回 "deny" | "ask" | "allow" | None（未命中）。
    优先级固定 deny > ask > allow。每档内：先 per-tool，再 per-pattern。
    见 docs/design/runtime/permission-model.md §3.4。"""
    if rules is None:
        return None
    from openprogram.runtime.permissions.rule import parse_rule, parse_command, pattern_matches
    cmd = None  # 惰性求值：只在遇到 per-pattern 规则时解析命令
    for behavior, ruleset in (("deny", rules.deny), ("ask", rules.ask), ("allow", rules.allow)):
        for raw in ruleset:
            rv = parse_rule(raw)
            if rv.tool_name != tool_name and rv.tool_name not in _RULE_ALIASES.get(tool_name, ()):
                continue
            if rv.pattern is None:
                return behavior
            if cmd is None:
                cmd = parse_command(tool_name, args)
            if cmd is not None and pattern_matches(
                rv.pattern, cmd, allow=(behavior == "allow"),
            ):
                return behavior
    return None


def _path_is_safe(tool_name: str, args: dict, req: "TurnRequest") -> bool:
    """acceptEdits 档下判断写目标是否安全（工作目录内 + 非危险文件/目录 +
    无 Windows 绕过）。完整规则集在 file_safety.check_path_safety。"""
    import os
    from openprogram.runtime.permissions.rule import parse_command
    from openprogram.programs.tools.files.file_safety import check_path_safety
    from openprogram.state.worktree.context import current_worktree_path
    path = parse_command(tool_name, args)
    if not path:
        return True  # 无路径参数（如 glob/grep）视为安全
    # 围栏基准与 system prompt 的 cwd 同源（_model_tools 同一 ContextVar）：
    # dispatcher 每 turn 把真实 cwd（worktree / 项目路径）绑进
    # current_worktree_path，进程 getcwd 只是无绑定时的回落。
    worktree = current_worktree_path() or os.getcwd()
    work_dirs = [worktree, *getattr(req, "additional_working_dirs", [])]
    target = path if os.path.isabs(path) else os.path.join(worktree, path)
    return check_path_safety(target, work_dirs)["safe"]


def _hard_constraint_violation(
    tool_name: str,
    args: dict,
    req: "TurnRequest",
) -> str | None:
    """Return the non-configurable constraint violated by an external turn."""
    import os
    from openprogram.runtime.permissions.rule import parse_command
    from openprogram.host.sandbox.protected_paths import applications_root, installed_program_roots, application_catalog_path
    from openprogram.state.worktree.context import current_worktree_path

    protected = [applications_root(), *installed_program_roots(), application_catalog_path()]

    def _targets_agentics(path: str | None) -> bool:
        if not path or not protected:
            return False
        if not os.path.isabs(path):
            path = os.path.join(current_worktree_path() or os.getcwd(), path)
        target = os.path.realpath(path)
        return any(target == os.path.realpath(root) or target.startswith(os.path.realpath(root) + os.sep) for root in protected)

    if tool_name in _WRITE_TOOLS:
        path = parse_command(tool_name, args)
        if _targets_agentics(path):
            if req.source in {"agent_spawn", "mcp"}:
                _audit_path(req, tool_name, "protected agentic target")
            return "model tools cannot write auto-imported agentic Python"
    if tool_name == "apply_patch":
        patch = args.get("patch") if isinstance(args, dict) else None
        if isinstance(patch, str):
            for line in patch.splitlines():
                prefix = next(
                    (p for p in _PATCH_PATH_PREFIXES if line.startswith(p)), None
                )
                if prefix and _targets_agentics(line[len(prefix):].strip()):
                    if req.source in {"agent_spawn", "mcp"}:
                        _audit_path(req, tool_name, "protected agentic target")
                    return "model tools cannot write auto-imported agentic Python"

    if req.source in {"cron", "scheduler"}:
        if tool_name not in _SCHEDULED_ALLOWED_TOOLS:
            return f"{req.source} cannot execute side-effect tool {tool_name}"
        if (
            tool_name in _SCHEDULED_MEMORY_TOOLS
            and req.authority_tier != "owner"
        ):
            return f"{req.source} Memory lifecycle requires owner authority"
        return None
    if req.source not in {"agent_spawn", "mcp"}:
        return None
    if tool_name in _WORKTREE_TOOLS:
        return f"{req.source} cannot execute {tool_name}"
    # Owner-delegated Agents use their admitted permission snapshot for
    # shell/process tools. Authority checks, explicit rules, non-interactive
    # approval limits and the backend sandbox still apply below.
    if tool_name in _RISKY_TOOLS and not (
        req.source == "agent_spawn" and req.authority_tier == "owner"
    ):
        return f"{req.source} cannot execute {tool_name}"
    if tool_name in _WRITE_TOOLS:
        raw = (args.get("path") or args.get("file_path")) if isinstance(args, dict) else None
        if not isinstance(raw, str) or not raw.strip():
            _audit_path(req, tool_name, "missing write target")
            return f"{req.source} write requires an explicit target path: {tool_name}"
        if not _path_is_safe(tool_name, args, req):
            _audit_path(req, tool_name, "unsafe write target")
            return (
                f"{req.source} cannot write outside its working directories: "
                f"{tool_name}"
            )
        return None
    if tool_name != "apply_patch":
        return None

    patch = args.get("patch") if isinstance(args, dict) else None
    if not isinstance(patch, str):
        return None
    for line in patch.splitlines():
        prefix = next((p for p in _PATCH_PATH_PREFIXES if line.startswith(p)), None)
        if prefix is None:
            continue
        path = line[len(prefix):].strip()
        if not path:
            _audit_path(req, "apply_patch", "empty patch target")
            return f"{req.source} cannot apply a patch with an empty target path"
        if not _path_is_safe("write", {"file_path": path}, req):
            _audit_path(req, "apply_patch", "unsafe patch target")
            return (
                f"{req.source} cannot apply a patch outside its working "
                "directories"
            )
    return None


def _audit_path(req: "TurnRequest", tool_name: str, reason: str) -> None:
    from openprogram.runtime.permissions.audit import log_path_safety_violation
    log_path_safety_violation(req.session_id or "", tool_name, reason)


def _audit_delegated_risky(tool_name: str, req: "TurnRequest") -> None:
    if tool_name in _RISKY_TOOLS and req.source in _NON_INTERACTIVE_SOURCES:
        from openprogram.runtime.permissions.audit import log_delegated_risky_tool
        log_delegated_risky_tool(
            req.session_id or "", tool_name, req.source, req.authority_tier or "",
        )


def _user_browser(args: dict) -> str:
    """The user's own Chrome or Edge, which the conversation's Page grant does not cover."""
    from openprogram.programs._host import services as _services
    browser = _services.lookup("browser")
    if browser is None:
        return ""
    nested = args.get("args") if isinstance(args.get("args"), dict) else {}
    return browser.browser_of(nested)


def _app_grant_needed(agent_tool, args: dict) -> bool:
    from openprogram.programs import tool_requires_approval
    try:
        needed, _reason = tool_requires_approval(agent_tool, args)
    except Exception:
        return True
    return bool(needed)


def permission_decision(agent_tool, req, args: dict) -> tuple[str, str, str, object]:
    """One synchronous decision for both wait publication and execution.

    Auto classification runs only during execution. The final item carries
    structured authority evidence when a capability check denies access.
    """
    name = agent_tool.name
    violation = _hard_constraint_violation(name, args, req)
    if violation:
        return "deny", "HARD_CONSTRAINT_DENIED", f"hard constraint: {violation}", None
    from openprogram.programs._authoring import guides
    unread = guides.missing_required(name, args if isinstance(args, dict) else {})
    if unread:
        return "deny", "GUIDE_REQUIRED", guides.refusal(name, unread), None
    from openprogram.programs._authoring import prechecks
    invalid = prechecks.problem(name, args)
    if invalid:
        return "deny", "INVALID_ARGUMENTS", f"{name}: {invalid}", None
    from openprogram.runtime.permissions.tool_authority import decide_tool_authority
    authority = decide_tool_authority(req, name, args)
    if not authority.allowed:
        return "deny", authority.reason_code, f"authority tier does not allow {authority.capability}", authority
    from openprogram.runtime.permissions.session_facts import facts
    from openprogram.programs import _unsafe_in_for
    if (req.permission_mode == "plan" or facts().in_plan_mode(req.session_id)) and "plan" in _unsafe_in_for(name):
        return "deny", "PLAN_MODE_DENY", f"plan mode cannot execute {name}", None
    verdict = _match_rule(getattr(req, "permission_rules", None), name, args)
    if verdict == "deny":
        return "deny", "PERMISSION_RULE_DENY", f"blocked by deny rule: {name}", None
    from openprogram.runtime.permissions.recovery import approval_context
    try:
        recovery = approval_context(agent_tool, req)
    except Exception:
        return "deny", "RECOVERY_STATE_UNAVAILABLE", "cannot verify unresolved prior operations", None
    if recovery:
        reason = "RECOVERY_EFFECT_UNCERTAIN"
    elif verdict == "ask" or force_approval(name, args):
        reason = "PERMISSION_RULE_ASK" if verdict == "ask" else "MANDATORY_APPROVAL"
    elif _page_script(name, args) and verdict != "allow" and (
            req.permission_mode != "bypass" or req.source in _NON_INTERACTIVE_SOURCES):
        reason = "PAGE_SCRIPT_APPROVAL"
    elif _held_outbound(name, req):
        reason = "OUTBOUND_HOLD"
    elif (name in _APP_GRANT_TOOLS and verdict != "allow"
          and req.permission_mode not in {"bypass", "auto"}
          and _app_grant_needed(agent_tool, args)):
        reason = "APP_GRANT_REQUIRED"
    else:
        if name == "web_use" or (name == "computer_use_agent" and isinstance(args, dict)
                                 and args.get("target") == "browser" and not _user_browser(args)):
            if facts().web_use_available(getattr(req, "surface_context", None)):
                return "allow", "SURFACE_GRANT", "", None
        if _session_poll(name, args):
            # The command itself was approved when bash started it.
            return "allow", "SESSION_POLL", "", None
        if req.permission_mode == "bypass" or verdict == "allow":
            _audit_delegated_risky(name, req)
            return "allow", "BYPASS" if req.permission_mode == "bypass" else "PERMISSION_RULE_ALLOW", "", None
        if req.source in {"cron", "scheduler"} and name in _SCHEDULED_MEMORY_TOOLS:
            return "allow", "SCHEDULED_MEMORY", "", None
        from openprogram.runtime.permissions.classifier import safe_call
        if safe_call(name, args):
            return "allow", "SAFE_TOOL", "", None
        if req.permission_mode == "acceptEdits" and getattr(agent_tool, "_accept_edits_safe", False) and _path_is_safe(name, args, req):
            return "allow", "SAFE_EDIT", "", None
        if req.permission_mode == "auto":
            return "auto", "AUTO_CLASSIFY", "", None
        reason = "MODE_APPROVAL"
    if req.source in _NON_INTERACTIVE_SOURCES:
        return "deny", "APPROVAL_UNAVAILABLE_NON_INTERACTIVE", f"non-interactive {req.source} cannot approve {name}", None
    return "ask", reason, "", None
