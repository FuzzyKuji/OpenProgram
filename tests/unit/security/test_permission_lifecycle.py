"""Shared approval boundary contracts."""
import pytest
from openprogram.runtime.permissions.authority import owner_authority
from openprogram.runtime.agent.turn_request import TurnRequest
from openprogram.runtime.permissions.approval import wrap_with_approval
from openprogram.runtime.permissions.modes import PermissionRules
from openprogram.models.providers.types import AgentTool, AgentToolResult

@pytest.mark.parametrize("name,rules,args", [
    ("bash", PermissionRules(ask=["bash"]), {}),
    ("self_update", None, {"action": "prepare", "worktree_id": "wt_1", "candidate_sha": "a" * 40,
                           "goal": "docs", "assertions": ["the page names help"]}),
    ("exit_plan_mode", None, {}),
])
def test_bypass_preserves_required_approval_manifest(name, rules, args, monkeypatch):
    # The interactive wrapper reads current project rules at each operation.
    monkeypatch.setattr("openprogram.runtime.permissions.rule.load_merged_rules", lambda _sid: rules)
    async def execute(*args):
        return AgentToolResult(content=[], details={})
    req = TurnRequest(session_id="manifest-audit", user_text="test", agent_id="main",
        source="web", permission_mode="bypass", permission_rules=rules,
        **owner_authority("owner/install/0123456789abcdef"))
    tool = AgentTool(name=name, label=name, description="probe", parameters={"type":"object"}, execute=execute)
    wrapped = wrap_with_approval(tool, req, lambda event: None)
    manifest = wrapped._interaction_manifest("call-1", args)
    assert manifest is not None
    assert manifest["kind"] == "approval"
    # Declining is the user's answer: the model hears it, the run goes on.
    assert manifest["policy_snapshot"]["on_decline"] == "continue"
