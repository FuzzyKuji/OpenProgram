"""Bind permission decisions to durable approval waits and tool execution.

The Agent safe point publishes manifests before effects start. Execution
consumes only the resolved wait for the exact session, execution and tool call.
"""
from __future__ import annotations

from typing import Any, Callable
import logging

_log = logging.getLogger(__name__)

# A turn request: the conversation package's ``TurnRequest`` or any object
# with its fields. Permission code reads the fields; it never imports it.
TurnRequest = Any

from openprogram.runtime.permissions.file_state import capture as capture_file_state

from openprogram.runtime.permissions.policy import (
    _RISKY_TOOLS,
    _hard_constraint_violation, one_shot_approval, page_script, permission_decision,
)

EventCallback = Callable[[dict], None]


def _persist_always_allow_rule(session_id: str, tool_name: str, args: dict) -> bool:
    """把 "总是允许" 写成一条精确操作规则，落到**项目**层
    （<project>/.openprogram/settings.json 的 permission_rules.allow）。
    规则跟项目走——切会话仍生效、长期记住。见 permission-model.md §2.3。"""
    if not session_id:
        return False
    try:
        from openprogram.runtime.permissions.rule import (
            exact_rule_for_call, rule_to_string,
        )
        from openprogram.state.store.project import project_store as _projects
        value = exact_rule_for_call(tool_name, args)
        if value is None:
            return False
        serialized = rule_to_string(value)
        proj = _projects.project_for_session(session_id) or _projects.get_default_project()
        settings = _projects.load_project_settings(proj.id)
        rules = settings.get("permission_rules") or {"allow": [], "deny": [], "ask": []}
        allow = rules.setdefault("allow", [])
        if serialized not in allow:
            allow.append(serialized)
        settings["permission_rules"] = rules
        _projects.save_project_settings(proj.id, settings)
        saved = _projects.load_project_settings(proj.id)
        return serialized in (saved.get("permission_rules") or {}).get("allow", [])
    except Exception:
        return False


# Tools whose approval card offers "allow for this conversation": the grant
# is written as a session-layer rule, so it ends with the conversation.
_SESSION_SCOPE_TOOLS = {"computer_use_agent"}


def _persist_session_allow_rule(session_id: str, tool_name: str, args: dict) -> bool:
    """Write "allow for this conversation" as an exact rule in the session layer."""
    if not session_id:
        return False
    try:
        from openprogram.runtime.permissions.rule import exact_rule_for_call, rule_to_string
        from openprogram.runtime.permissions.session_facts import facts
        value = exact_rule_for_call(tool_name, args)
        if value is None:
            return False
        serialized = rule_to_string(value)
        from openprogram.runtime.context.session_db import default_db
        row = default_db().get_session(session_id)
        if row is None:
            return False
        rules = facts().session_rules(session_id)
        allow = list(rules.allow) if rules is not None else []
        if serialized not in allow:
            allow.append(serialized)
        facts().save_session_rules(session_id, row.get("agent_id"), {
            "allow": allow,
            "deny": list(rules.deny) if rules is not None else [],
            "ask": list(rules.ask) if rules is not None else [],
        })
        saved = facts().session_rules(session_id)
        return saved is not None and serialized in saved.allow
    except Exception:
        return False



# Tools that take sandbox_permissions="require_escalated": the model asks to
# leave the sandbox before the command runs, as Codex does, and the approval
# is published at the Agent safe point like any other.
ESCALATION_TOOLS = frozenset({"bash"})
ESCALATION_SUFFIX = "sandbox-escalation"

# "Allow for this conversation" on an escalation: the exact commands, in
# memory, so a worker restart asks again. Never written as a permission rule,
# because an allow rule would also skip the sandbox's own approval.
_session_escalations: dict[str, set[str]] = {}


def _escalation_needed(tool_name: str, args) -> bool:
    if tool_name not in ESCALATION_TOOLS or not isinstance(args, dict):
        return False
    if args.get("sandbox_permissions") != "require_escalated":
        return False
    from openprogram.host.sandbox import resolve_policy
    return resolve_policy() is not None


def _escalation_args(args: dict) -> dict:
    import sys
    escalation = {
        "from": "seatbelt" if sys.platform == "darwin" else "bubblewrap",
        "to": "hard-constraints-only",
    }
    justification = str(args.get("justification") or "").strip()
    if justification:
        escalation["justification"] = justification
    return {**args, "_sandbox_escalation": escalation}


def _escalation_granted(session_id: str, args: dict) -> bool:
    return str(args.get("command") or "") in _session_escalations.get(session_id or "", set())


def _grant_escalation(session_id: str, args: dict) -> None:
    if session_id:
        _session_escalations.setdefault(session_id, set()).add(str(args.get("command") or ""))


def wrap_with_approval(
    agent_tool,
    req: "TurnRequest",
    on_event: EventCallback,
    *,
    _live: bool = True,
):
    """Return a copy of ``agent_tool`` whose ``execute`` first checks
    approval, awaiting (not blocking) the user's response. Falls back
    to the original tool when permission_mode is "bypass" or the
    tool's per-tool gate decides no approval is needed.

    Why a wrapper layer (vs. inspecting tool_execution_start in the
    drain): agent_loop schedules ``await tool.execute(...)`` directly
    after pushing tool_execution_start. The dispatcher's async-for
    consumer can't reliably block the tool from running because the
    tool already runs as a thread-pool task in parallel. Gating
    inside the tool's own coroutine is the only safe seam.
    """
    from openprogram.models.providers.types import AgentTool, AgentToolResult
    from openprogram.models.providers.types import TextContent

    if _live:
        from openprogram.runtime.permissions import wrap_live_permission
        return wrap_live_permission(agent_tool, req, on_event)

    orig_execute = agent_tool.execute
    name = agent_tool.name
    prepared = None
    approved_recovery = None

    async def _permission_preflight(call_id, args, *, operation_id=None):
        nonlocal prepared
        from openprogram.runtime.permissions.auto_review import prepare_review
        prepared = await prepare_review(agent_tool, req, call_id, args, operation_id=operation_id)

    def _fallback(call_id, args):
        return bool(prepared is not None and prepared.matches(call_id, args)
                    and prepared.verdict.code == "AUTO_CLASSIFIER_DENY"
                    and prepared.record and prepared.record["fallback"] and _approval_authorized())

    def _interaction_manifest(call_id: str, args: dict) -> dict | None:
        """Describe an approval before the Agent loop dispatches its effect."""
        decision, reason, _, _ = permission_decision(agent_tool, req, args)
        if (decision != "deny" and req.permission_mode != "bypass"
                and _escalation_needed(name, args)
                and not _escalation_granted(req.session_id, args)
                and _approval_authorized()):
            return _escalation_manifest(call_id, args)
        if decision != "deny" and reason != "RECOVERY_EFFECT_UNCERTAIN":
            from openprogram.host.system_access import access_manifest_for_tool
            access = access_manifest_for_tool(name, args)
            if access is not None:
                return access
        if decision == "allow" and name == "ask_user_question":
            from openprogram.programs.tools.interaction.clarify import interaction_manifest
            return interaction_manifest(args)
        if decision == "auto" and _fallback(call_id, args):
            decision, reason = "ask", "AUTO_REFUSAL_FALLBACK"
        if decision != "ask":
            return None
        from openprogram.state.worktree.context import current_worktree_path
        import os
        from openprogram.runtime.permissions.rule import exact_rule_for_call
        scopes = ["once"]
        if reason not in {"AUTO_REFUSAL_FALLBACK", "RECOVERY_EFFECT_UNCERTAIN"} and not one_shot_approval(name, args) and exact_rule_for_call(name, args) is not None:
            if name in _SESSION_SCOPE_TOOLS:
                scopes.append("session")
            if not page_script(name, args):
                scopes.append("always")
        from openprogram.runtime.permissions.recovery import approval_context
        recovery = approval_context(agent_tool, req)
        shown = _shown_args(name, args, req)
        detail = _approval_detail(name, shown)
        if recovery:
            detail = ("Previous operations have unknown outcomes. This approval authorizes only "
                      "the new operation below; it does not confirm or resolve prior operations.\n"
                      + "\n".join(f"{item['tool']}: {item['effect_id']}" for item in recovery)
                      + "\n\n" + detail)
        return {
            "kind": "approval",
            "prompt": f"允许执行 {name}？",
            "options": ["允许", "拒绝"],
            "allow_custom": False,
            "detail": detail,
            "request_metadata": {
                "tool": name, "args": args, "tool_call_id": str(call_id),
                **({"shown_args": shown} if shown is not args else {}),
                "risk_level": _risk_level(name, args),
                "approval_reason": reason,
                "allowed_scopes": scopes,
                "recovery_effects": recovery,
                "permission_version": getattr(req, "_permission_version", 0),
                "file_preconditions": capture_file_state(name, args),
                "accept_edits_safe": bool(getattr(agent_tool, "_accept_edits_safe", False)),
                "working_dir": current_worktree_path() or os.getcwd(),
            },
            "policy_snapshot": {
                # A refusal is an answer for the model, not a failed run.
                "version": 1, "kind": "approval", "on_answer": "continue",
                "on_decline": "continue", "on_timeout": "fail",
                "allowed_scopes": scopes,
            },
            "timeout": None,
        }

    def _escalation_manifest(call_id: str, args: dict) -> dict:
        from openprogram.state.worktree.context import current_worktree_path
        import os
        shown = _escalation_args(args)
        justification = str(args.get("justification") or "").strip()
        detail = _approval_detail(name, {"command": args.get("command"), "workdir": args.get("workdir")})
        if justification:
            detail = f"{justification}\n\n{detail}"
        scopes = ["once", "session"]
        return {
            "kind": "approval",
            "prompt": f"允许 {name} 在沙箱外执行？",
            "options": ["允许", "拒绝"],
            "allow_custom": False,
            "detail": detail,
            "request_metadata": {
                "tool": f"{name}:{ESCALATION_SUFFIX}", "args": shown, "tool_call_id": str(call_id),
                "risk_level": "high",
                "approval_reason": "SANDBOX_ESCALATION",
                "allowed_scopes": scopes,
                "recovery_effects": [],
                "permission_version": getattr(req, "_permission_version", 0),
                "file_preconditions": {},
                "accept_edits_safe": False,
                "working_dir": current_worktree_path() or os.getcwd(),
            },
            "policy_snapshot": {
                "version": 1, "kind": "approval", "on_answer": "continue",
                "on_decline": "continue", "on_timeout": "fail",
                "allowed_scopes": scopes,
            },
            "timeout": None,
        }

    def _denied(
        text: str,
        reason_code: str,
        authority_decision=None,
        *, execution_started=False,
    ) -> "AgentToolResult":
        from openprogram.runtime.permissions.execution import mark_refused
        mark_refused(reason_code)
        details = {
            "denied": True,
            "reason_code": reason_code,
            "outcome": "failed" if execution_started else "not_started",
            "execution_started": execution_started,
        }
        if authority_decision is not None:
            details["authority_decision"] = authority_decision.to_dict()
        return AgentToolResult(
            content=[TextContent(text=text)],
            details=details,
            is_error=True,
        )

    def _approval_authorized() -> bool:
        from openprogram.state.authority import has_capability, normalize_authority
        from openprogram.runtime.permissions.authority import owner_principal_id

        authority = normalize_authority(req)
        try:
            is_owner = authority.get("principal_id") == owner_principal_id()
        except Exception:
            is_owner = False
        return bool(
            authority
            and is_owner
            and authority.get("authority_tier") == "owner"
            and authority.get("speaker_kind") == "owner"
            and authority.get("interaction") == "interactive"
            and has_capability(authority, "approval.request")
        )

    def _sandbox_metadata(result) -> dict | None:
        details = getattr(result, "details", None)
        if not isinstance(details, dict):
            return None
        direct = details.get("sandbox")
        nested = details.get("json")
        value = direct if isinstance(direct, dict) else (
            nested.get("sandbox") if isinstance(nested, dict) else None
        )
        return value if isinstance(value, dict) else None

    async def _run_original(call_id, args, cancel, on_update):
        from openprogram.runtime.permissions.recovery import approval_context
        try:
            recovery = approval_context(agent_tool, req)
        except Exception:
            return _denied("[denied] cannot verify unresolved prior operations", "RECOVERY_STATE_UNAVAILABLE")
        if (recovery or approved_recovery) and recovery != approved_recovery:
            return _denied("[denied] prior operations changed; request a new one-shot approval", "RECOVERY_APPROVAL_STALE")
        try:
            from openprogram.runtime.permissions.file_state import check_current, current_files
            check_current()
            # Restored approvals retain a durable baseline across worker restarts.
            from openprogram.state.store.snapshot.read_tracking import mark_seen
            for path in current_files():
                mark_seen(path)
        except (OSError, ValueError) as exc:
            return _denied(str(exc), "APPROVAL_FILE_CHANGED")
        from openprogram.runtime.permissions.file_state import file_scope
        from openprogram.runtime.permissions.execution import mark_started
        await mark_started()
        with file_scope():
            result = await orig_execute(call_id, args, cancel, on_update)
        sandbox = _sandbox_metadata(result)
        if not sandbox or sandbox.get("kind") != "denied":
            return result

        event = {
            "type": "sandbox.violation",
            "data": {
                "session_id": req.session_id,
                "tool": name,
                "args": args,
                "sandbox": sandbox,
            },
        }
        try:
            on_event(event)
        except Exception:
            # Caller-supplied callback: the denial below still reaches the model.
            _log.warning("sandbox violation event not delivered for session %s", req.session_id, exc_info=True)

        # The denial text tells the model to call again with
        # sandbox_permissions="require_escalated". Asking here, after the
        # command ran, cannot work: approvals are published at the Agent
        # safe point, before any effect starts.
        return result

    async def _escalate_then_run(call_id, args, cancel, on_update):
        """Run one command outside the sandbox the model asked to leave."""
        if req.permission_mode == "bypass":
            return _denied(
                "[denied] Bypass mode keeps the configured sandbox and asks no "
                "questions, so this command cannot leave it. Tell the user it "
                "needs network or writes outside the workspace; they can turn "
                "on sandbox.network or switch permission mode.",
                "SANDBOX_ESCALATION_BYPASS",
            )
        if not _approval_authorized():
            return _denied(
                "[denied] sandbox escalation requires an interactive local owner",
                "SANDBOX_ESCALATION_OWNER_REQUIRED",
            )
        hard_violation = _hard_constraint_violation(name, args, req)
        if hard_violation:
            return _denied(f"[denied] hard constraint: {hard_violation}", "HARD_CONSTRAINT_DENIED")
        if not _escalation_granted(req.session_id, args):
            approved, reason, scope = await await_user_approval(
                req=req, tool_name=f"{name}:{ESCALATION_SUFFIX}",
                args=_escalation_args(args), on_event=on_event, tool_call_id=str(call_id),
            )
            if not approved:
                said = (f" The user said: {reason.strip()}"
                        if isinstance(reason, UserDeclineReason) else "")
                return _denied(
                    f"[denied] The user did not let this command leave the sandbox, "
                    f"so it did not run.{said} Do not retry it unchanged.",
                    "SANDBOX_ESCALATION_NOT_APPROVED",
                )
            if scope == "session":
                _grant_escalation(req.session_id, args)
        from openprogram.host.sandbox import escalated_policy
        with escalated_policy():
            return await _run_original(call_id, args, cancel, on_update)

    async def _approve_then_run(call_id, args, cancel, on_update):
        nonlocal approved_recovery
        if not _approval_authorized():
            return _denied(
                "[denied] approval requires an interactive local owner",
                "APPROVAL_LOCAL_OWNER_REQUIRED",
            )
        approval_args = args
        if _self_update_retry(name, args):
            from openprogram.operations.self_update.repair.next_candidate import approval_preview
            try:
                preview = approval_preview(args.get("update_id"), args.get("candidate_sha"), req)
            except Exception as exc:
                return _denied(f"[denied] {exc}", "SELF_UPDATE_RETRY_INVALID")
            approval_args = {**args, "candidate": preview}
        from openprogram.runtime.permissions.recovery import approval_context
        recovery = approval_context(agent_tool, req)
        approved, reason, scope = await await_user_approval(
            req=req, tool_name=name, args=approval_args, on_event=on_event,
            tool_call_id=str(call_id), **({"recovery_effects": recovery} if recovery else {}))
        if not approved:
            if isinstance(reason, UserDeclineReason):
                msg = (f"[denied] The user declined this {name} call, so it did not run. "
                       f"The user said: {reason.strip()}\n"
                       "Follow the user's instruction instead of retrying this call.")
            elif isinstance(reason, str) and reason.strip():
                msg = f"[denied] {reason.strip()}"
            else:
                msg = (f"[denied] The user declined this {name} call, so it did not run. "
                       "Do not retry it or work around it; stop and ask the user how to proceed.")
            return _denied(msg, "APPROVAL_DENIED")
        if recovery and scope != "once":
            return _denied("[denied] uncertain operations require one-shot approval", "RECOVERY_APPROVAL_SCOPE")
        approved_recovery = recovery
        if scope == "always" and not recovery and page_script(name, args):
            return _denied("[denied] page scripts are allowed once or for this conversation, never project-wide", "APPROVAL_SCOPE_INVALID")
        if scope == "always" and not recovery and not one_shot_approval(name, args):
            if not _persist_always_allow_rule(req.session_id, name, args):
                return _denied("[denied] could not save the project approval rule; operation was not executed", "APPROVAL_RULE_SAVE_FAILED")
        if scope == "session" and not recovery and name in _SESSION_SCOPE_TOOLS:
            if not _persist_session_allow_rule(req.session_id, name, args):
                return _denied("[denied] could not save the conversation approval rule; operation was not executed", "APPROVAL_RULE_SAVE_FAILED")
        if _fallback(call_id, args) and prepared.history is not None:
            prepared.history.record(blocked=False, reason="owner approved operation",
                               code="AUTO_OWNER_APPROVED", approved=True)
        return await _run_original(call_id, args, cancel, on_update)

    async def _gated_execute(call_id, args, cancel, on_update):
        decision, code, message, authority = permission_decision(agent_tool, req, args)
        if decision == "deny":
            return _denied(f"[denied] {message}", code, authority)
        if _escalation_needed(name, args):
            # The escalation card is the one approval: it also covers what
            # an ordinary "ask" would have asked.
            return await _escalate_then_run(call_id, args, cancel, on_update)
        if decision == "ask":
            return await _approve_then_run(call_id, args, cancel, on_update)
        if decision == "auto":
            if prepared is None or not prepared.matches(call_id, args):
                await _permission_preflight(call_id, args)
            if not prepared.matches(call_id, args):
                return _denied("[denied] operation changed during review", "PERMISSION_REVIEW_STALE")
            from openprogram.runtime.permissions.file_state import validate
            import os
            from openprogram.state.worktree.context import current_worktree_path
            if prepared.working_dir != (current_worktree_path() or os.getcwd()):
                return _denied("[denied] working directory changed during review", "PERMISSION_REVIEW_STALE")
            try:
                validate(prepared.files)
            except (OSError, ValueError) as exc:
                return _denied(str(exc), "PERMISSION_REVIEW_STALE")
            if _fallback(call_id, args):
                return await _approve_then_run(call_id, args, cancel, on_update)
            blocked, reason = prepared.verdict
            if blocked:
                return _denied(f"[denied] auto classifier: {reason}", prepared.verdict.code)
        return await _run_original(call_id, args, cancel, on_update)

    wrapped = AgentTool(
        name=agent_tool.name,
        description=agent_tool.description,
        parameters=agent_tool.parameters,
        label=getattr(agent_tool, "label", agent_tool.name) or agent_tool.name,
        execute=_gated_execute,
    )
    # Carry over sidecar flags the dispatcher reads downstream.
    # _is_agent_method in particular is how runtime-block rendering is
    # triggered for LLM-invoked Agent method calls.
    for _attr in (
        "_is_agent_method", "_python_callable", "_method_options", "_dag_expose", "_defer", "_tier", "_program_owner", "_workflow_owner", "_run_in_worker", "_mcp_server",
        "_runtime_implementation", "_requires_approval", "_accept_edits_safe",
    ):
        setattr(wrapped, _attr, getattr(agent_tool, _attr, None))
    object.__setattr__(wrapped, "_permission_managed", True)
    object.__setattr__(wrapped, "_permission_preflight", _permission_preflight)
    object.__setattr__(wrapped, "_interaction_manifest", _interaction_manifest)
    return wrapped


def _risk_level(tool_name: str, args: dict) -> str:
    """审批卡片的危险分级 "low"|"medium"|"high"，驱动前端高亮。
    完整规则集见 file_safety.py（S13）；这里是基础判定。"""
    name = tool_name.lower()
    if name in _RISKY_TOOLS:
        cmd = str((args or {}).get("command", "")).lower()
        if any(p in cmd for p in ("rm -rf", "sudo", "mkfs", ":(){", "| sh", "| bash", "curl", "wget")):
            return "high"
        return "medium"
    if any(k in name for k in ("write", "edit", "apply_patch", "delete", "remove")):
        return "medium"
    return "low"


def _self_update_retry(tool_name: str, args) -> bool:
    return tool_name == "self_update" and isinstance(args, dict) and args.get("action") == "retry"


def _shown_args(tool_name: str, args: dict, req) -> dict:
    """A retry approves a candidate, so its card shows that candidate's paths, tests and budget."""
    if not _self_update_retry(tool_name, args):
        return args
    from openprogram.operations.self_update.repair.next_candidate import approval_preview
    try:
        return {**args, "candidate": approval_preview(args.get("update_id"), args.get("candidate_sha"), req)}
    except Exception:
        # Execution rechecks the candidate and refuses it with the reason.
        return args


def _json_form(value):
    """Compare an approval as stored: the wait keeps JSON, the live call may hold tuples."""
    import json
    return json.loads(json.dumps(value, default=str))


def _approval_detail(tool_name: str, args: dict) -> str:
    """批准卡片的危险摘要：工具名 + 参数全文（超长截断，首尾保留）。
    第一版不做危险 token 高亮（docs/reference/design/ui/composer/composer-interaction-modes.md 决策）。"""
    try:
        import json
        body = json.dumps(args, ensure_ascii=False, indent=2) if args else ""
    except Exception:
        body = str(args)
    if len(body) > 2000 and not one_shot_approval(tool_name, args) and not page_script(tool_name, args):
        body = body[:1200] + "\n…（已截断）…\n" + body[-600:]
    return f"{tool_name}\n{body}".rstrip()


class UserDeclineReason(str):
    """What the user typed when declining, as opposed to a system refusal."""


async def await_user_approval(
    *,
    req: "TurnRequest",
    tool_name: str,
    args: dict,
    on_event: EventCallback,
    timeout: float = 300.0,
    tool_call_id: str | None = None,
    recovery_effects: list[dict[str, str]] | None = None,
) -> tuple[bool, "str | None", str]:
    """Consume the resolved approval wait selected by the Agent safe point.
    返回 (approved, reason, scope)：approved=是否放行；reason=拒绝理由（可为 None）；
    scope ∈ {"once","session","always","always_path"}——"总是允许"经 canonical
    wait answer command 的 scope 字段带回。

    审批等待由 Agent safe-point handoff 预先发布，答案通过 canonical
    ``execution.wait.answer`` / ``execution.wait.decline`` command 写入 durable
    execution state；此函数只读取该结果，不创建第二个本地审批状态。
    """
    from openprogram.runtime.permissions.session_facts import facts
    preapproved_wait_id = facts().preapproved_wait_id()
    if preapproved_wait_id:
        from openprogram.runtime.execution import default_store
        from openprogram.runtime.execution.waits import DurableWaitStore, WaitStatus

        wait = DurableWaitStore(default_store()).get_wait(preapproved_wait_id)
        if wait is None or wait.kind != "approval":
            raise RuntimeError("preapproved wait is unavailable")
        execution = default_store().get_execution(wait.execution_id)
        current_execution = facts().current_execution_id()
        if (execution is None or execution.session_id != req.session_id
                or wait.request.get("tool") != tool_name
                or _json_form(wait.request.get("shown_args", wait.request.get("args"))) != _json_form(args)
                or (current_execution and current_execution != wait.execution_id)
                or (tool_call_id and wait.request.get("tool_call_id") != tool_call_id)):
            return False, "approval does not authorize this operation", "once"
        if wait.request.get("approval_reason") == "AUTO_REFUSAL_FALLBACK":
            import os
            from openprogram.state.worktree.context import current_worktree_path
            if (wait.request.get("permission_version", 0) != getattr(req, "_permission_version", 0)
                    or wait.request.get("working_dir") != (current_worktree_path() or os.getcwd())):
                return False, "permission or working directory changed after this approval", "once"
        if recovery_effects or wait.request.get("recovery_effects"):
            import os
            from openprogram.state.worktree.context import current_worktree_path
            if (wait.request.get("approval_reason") != "RECOVERY_EFFECT_UNCERTAIN"
                    or wait.request.get("recovery_effects") != recovery_effects
                    or wait.request.get("permission_version", 0) != getattr(req, "_permission_version", 0)
                    or wait.request.get("working_dir") != (current_worktree_path() or os.getcwd())):
                return False, "recovery context changed; request a new one-shot approval", "once"
        if wait.status is WaitStatus.RESOLVED:
            from openprogram.runtime.permissions.file_state import validate
            if tool_name in {"edit", "write", "apply_patch"} and "file_preconditions" not in wait.request:
                return False, "This file approval has no saved file state. Read the current file and request a new approval.", "once"
            try:
                validate(dict(wait.request.get("file_preconditions") or {}))
            except (OSError, ValueError) as exc:
                return False, str(exc), "once"
            value = wait.answer
            answer, scope = (
                (value.get("answer"), value.get("scope", "once"))
                if isinstance(value, dict) else (value, "once")
            )
            allowed = (
                answer.strip() in ("允许", "approve", "yes", "y", "true", "ok", "是")
                if isinstance(answer, str) else bool(answer)
            )
            return allowed, None, (
                scope if scope in ("once", "session", "always", "always_path") else "once"
            )
        if wait.status is WaitStatus.DECLINED and isinstance(wait.answer, str) and wait.answer.strip():
            return False, UserDeclineReason(wait.answer.strip()), "once"
        if wait.status in {WaitStatus.DECLINED, WaitStatus.EXPIRED, WaitStatus.CANCELLED}:
            return False, None, "once"
        raise RuntimeError("approval continuation has no durable outcome")

    raise RuntimeError(
        "tool approval requires a pre-dispatch durable wait safe point"
    )
