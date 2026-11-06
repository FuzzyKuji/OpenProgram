"""Per-session run configuration shared by TUI, web, and channels.

工具集设计原则（见 docs/reference/design/runtime/agent-configuration/tool-toggle-management.md）：
工具范围由会话的 Agent 配置决定，会话自己不开关工具、不选 Access preset。
会话只存两种叠加意图，绝不存"展开后的工具名列表快照"：
- ``web_search``（bool）：在 Agent 工具集之上加 / 去掉 web_search，
  由 ``tools_override_from_config`` 组合成 dict 意图，运行时经
  ``_model_tools`` 的 dict 分支实时展开。
- ``tools_override``（list[str]）：/skill 声明的 allowed-tools 白名单，
  原样透传。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union


VALID_THINKING = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
# Permission modes and rule sets belong to the permission package
# (``openprogram.runtime.permissions.modes``); session settings store them.
from openprogram.runtime.permissions.modes import (
    DEFAULT_PERMISSION,
    PermissionRules,
    as_permission_rules as _as_permission_rules,
    normalize_permission as _normalize_permission,
)

# 工具意图的统一类型：dict（意图）/ list[str]（用户显式精选）/ None
ToolsOverride = Union[dict, list, None]


@dataclass
class SessionRunConfig:
    # /skill allowed-tools 白名单。见模块 docstring。
    tools_override: Optional[list[str]] = None
    # 叠加意图：在 Agent 工具集之上加 / 去掉 web_search。
    web_search: Optional[bool] = None
    thinking_effort: Optional[str] = None
    permission_mode: Optional[str] = None
    # ── 权限规则（见 permission-model.md §2.2）──
    permission_rules: Optional[PermissionRules] = None
    # 路径安全的额外工作目录集（§3.5）。
    additional_working_dirs: list[str] = field(default_factory=list)
    # Plus-menu Sandbox switch. None = inherit project/global sandbox.mode.
    sandbox_enabled: Optional[bool] = None


def load_session_run_config(session_id: str) -> SessionRunConfig:
    try:
        from openprogram.runtime.context.session_db import default_db
        row = default_db().get_session(session_id) or {}
    except Exception:
        row = {}

    return _config_from_row(row)


def _config_from_row(row: dict) -> SessionRunConfig:
    return SessionRunConfig(
        tools_override=_as_tools_override(row.get("tools_override")),
        web_search=_as_bool_or_none(row.get("web_search")),
        thinking_effort=_normalize_thinking(row.get("thinking_effort")),
        permission_mode=_normalize_permission((row.get("permission_state") or {}).get("mode") or row.get("permission_mode")),
        permission_rules=_as_permission_rules(row.get("permission_rules")),
        additional_working_dirs=_as_str_list(row.get("additional_working_dirs")),
        sandbox_enabled=_as_bool_or_none(row.get("sandbox_enabled")),
    )


def save_session_run_config(
    session_id: str,
    *,
    agent_id: str,
    tools: Any = None,
    web_search: Any = None,
    thinking_effort: Any = None,
    permission_mode: Any = None,
    permission_rules: Any = None,
    additional_working_dirs: Any = None,
    sandbox_enabled: Any = None,
) -> SessionRunConfig:
    fields: dict[str, Any] = {}

    override = _as_tools_override(tools)
    if override is not None:
        fields["tools_override"] = override

    ws = _as_bool_or_none(web_search)
    if ws is not None:
        fields["web_search"] = ws

    thinking = _normalize_thinking(thinking_effort)
    if thinking is not None:
        fields["thinking_effort"] = thinking

    permission = _normalize_permission(permission_mode)
    if permission is not None:
        fields["permission_mode"] = permission

    if permission_rules is not None:
        rules = _as_permission_rules(permission_rules)
        # 存成 dict（schemaless meta 里放纯数据结构）。空规则也存（用于清空）。
        fields["permission_rules"] = (
            {"allow": rules.allow, "deny": rules.deny, "ask": rules.ask}
            if rules is not None else None
        )


    if additional_working_dirs is not None:
        fields["additional_working_dirs"] = _as_str_list(additional_working_dirs)

    sandbox = _as_bool_or_none(sandbox_enabled)
    if sandbox is not None:
        fields["sandbox_enabled"] = sandbox

    from openprogram.runtime.context.session_db import default_db
    db = default_db()
    row = db.get_session(session_id)
    if row is not None and additional_working_dirs is None and "additional_working_dirs" not in row:
        from openprogram.state.store.project import project_store as projects
        project = projects.project_for_session(session_id)
        if project and project.source_folders:
            fields["additional_working_dirs"] = list(project.source_folders)
    if fields and row is not None:
        db.update_session(session_id, agent_id=agent_id, **fields)
        row = db.get_session(session_id)
    # An unsent draft has no session row. Return its normalized settings to
    # admission; the first message persists them without creating a ghost.
    return _config_from_row({**(row or {}), **fields})


def tools_override_from_config(cfg: SessionRunConfig) -> ToolsOverride:
    """Turn the stored INTENT into the override the dispatcher consumes.

    Output is one of:
      * ``list``  — a /skill allowed-tools selection (kept as-is)
      * ``dict``  — the web_search intent over the Agent's tool set,
                    expanded live by ``_model_tools``
      * ``None``  — no session-level override; the Agent profile decides
    """
    if cfg.tools_override:
        return _with_web_search(list(cfg.tools_override), cfg.web_search)
    if cfg.web_search is not None:
        return {"inherit": True, "web_search": cfg.web_search}
    return None


def reasoning_from_config(cfg: SessionRunConfig) -> Optional[str]:
    effort = _normalize_thinking(cfg.thinking_effort)
    if not effort or effort == "off":
        return None
    return effort


def permission_from_config(cfg: SessionRunConfig, *, default: str | None = None) -> str:
    """session override → caller default (usually project) → ``DEFAULT_PERMISSION``.

    Invalid values are dropped, so a missing or illegal mode cannot become
    ``bypass``.
    """
    return (
        _normalize_permission(cfg.permission_mode)
        or _normalize_permission(default)
        or DEFAULT_PERMISSION
    )


def project_defaults(session_id: str) -> dict:
    """会话所属项目的默认设置（permission_mode / toolset / thinking_effort）。
    新会话没自己设这些时的回落值。规则见 permission-model.md §2.3；这里是
    档位默认（非规则）。项目没设 → {}。"""
    try:
        from openprogram.state.store.project import project_store as _projects
        proj = _projects.project_for_session(session_id) or _projects.get_default_project()
        s = _projects.load_project_settings(proj.id)
        return {
            k: s[k] for k in (
                "permission_mode", "thinking_effort", "sandbox_mode",
            )
            if s.get(k)
        }
    except Exception:
        return {}


def sandbox_override_from_config(
    cfg: SessionRunConfig, session_id: str = "",
) -> Optional[bool]:
    """Session switch, else project ``sandbox_mode``, else None (inherit)."""
    if cfg.sandbox_enabled is not None:
        return cfg.sandbox_enabled
    if not session_id:
        return None
    mode = project_defaults(session_id).get("sandbox_mode")
    if not mode:
        return None
    from openprogram.host.sandbox import MODE_WORKSPACE_WRITE
    return str(mode).strip().lower() == MODE_WORKSPACE_WRITE


# ── intent helpers ──

def _with_web_search(override: list[str], web_search: Optional[bool]) -> list[str]:
    """Overlay the web_search intent onto a /skill selection."""
    if web_search is None:
        return override
    if web_search is False:
        return [name for name in override if name != "web_search"]
    return override if "web_search" in override else [*override, "web_search"]


def _as_tools_override(value: Any) -> Optional[list[str]]:
    if isinstance(value, list):
        out = [str(v) for v in value if str(v)]
        return out or None
    return None


def _as_bool_or_none(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return None


def _normalize_thinking(value: Any) -> Optional[str]:
    if value is None:
        return None
    effort = str(value).strip().lower()
    if effort == "none":
        effort = "off"
    return effort if effort in VALID_THINKING else None


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v)]
    return []


def load_agent_session_binding(session_id: str) -> dict[str, Any]:
    """Read an accepted trial's immutable profile from existing session storage.

    Shared by every dispatcher entry, including retry/edit and restored turns.
    The read-only memory restriction belongs to the session, not to a renderer
    flag which could disappear after refresh or a later normal chat message.
    """
    from copy import deepcopy
    from openprogram.runtime.context.session_db import default_db

    row = default_db().get_session(session_id) or {}
    if not row.get("agent_trial"):
        return {}
    profile = row.get("agent_profile_snapshot")
    if not isinstance(profile, dict) or profile.get("id") != row.get("agent_id"):
        raise ValueError("The saved Agent trial configuration is unavailable")
    return {
        "profile_snapshot": deepcopy(profile),
        "memory_policy_override": {
            "mode": "off" if (profile.get("memory") or {}).get("mode") == "off" else "read_only",
        },
    }
