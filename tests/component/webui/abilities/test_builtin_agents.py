"""The built-in Agents are saved Agents: installed once, then ordinary records."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openprogram import Agent, Runtime
from openprogram.runtime.agent_registry import manager
from openprogram.interfaces.server.routes.catalog import agents


def test_builtin_agents_are_saved_independent_and_preserve_owner_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "_state_root", lambda: tmp_path)
    manager.create("main", name="Existing", make_default=True)
    before = manager.get("main").to_dict()
    from openprogram.runtime.agent_registry.builtin_agents import BUILTIN_IDS, create_builtin_agents
    rows = create_builtin_agents(model_refs={"utility": manager.AgentModelRef("fixture", "small")})
    assert [row.id for row in rows] == list(BUILTIN_IDS)
    assert {"decision", "utility", "planner", "chief-of-staff", "research-desk", "writer"} <= set(BUILTIN_IDS)
    assert manager.get("main").to_dict() == before
    assert manager.get_default().id == "main"
    assert manager.get("image") is None
    assert manager.get("decision").name == "Decision"
    assert manager.get("utility").model.id == "small"
    specialists = [manager.get(agent_id) for agent_id in ("decision", "utility", "planner")]
    assert all(row.memory["mode"] == "off" for row in specialists)
    assert all(row.system_prompt == "" for row in specialists)
    from openprogram.runtime.agent.runtime.shared import _current_instructions
    seen_instructions = []
    def call(content, **kwargs):
        seen_instructions.append(_current_instructions.get())
        return '{"call":"B"}' if any("Pick." in block.get("text", "") for block in content) else "extracted"
    runtime = Runtime(call=call)
    token = _current_instructions.set("Instructions supplied by the caller")
    try:
        instance = Agent.from_spec(manager.get("utility"), runtime=runtime)
        assert instance.instructions is None
        assert instance("Extract one field") == "extracted"
        picker = Agent.from_spec(manager.get("decision"), runtime=runtime)
        assert picker.choose("Pick.", {"A": "First", "B": "Second"}) == "B"
        assert seen_instructions == ["Instructions supplied by the caller"] * 2
    finally:
        _current_instructions.reset(token)
        runtime.close()
    manager.update("utility", {"name": "My helper", "system_prompt": "Owner instructions"})
    saved = manager.get("utility").to_dict()
    create_builtin_agents()
    assert manager.get("utility").to_dict() == saved
    app = FastAPI()
    agents.register(app)
    with TestClient(app) as client:
        assert len(client.get("/api/agents").json()["agents"]) == 1 + len(BUILTIN_IDS)
        manager.delete("decision")
        assert len(client.get("/api/agents").json()["agents"]) == len(BUILTIN_IDS)
        assert manager.get("decision") is None
    # A deleted built-in stays deleted: the index remembers it was installed.
    assert [row.id for row in create_builtin_agents()] == [agent_id for agent_id in BUILTIN_IDS if agent_id != "decision"]
    assert manager.get("decision") is None
    assert manager.installed_builtins() == set(BUILTIN_IDS)


def test_job_agents_carry_a_prompt_tools_memory_and_always_on_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "_state_root", lambda: tmp_path)
    manager.create("main", name="Main", make_default=True)
    from openprogram.programs._host.runtime import all_tools
    from openprogram.runtime.agent_registry.builtin_agents import BUILTINS, create_builtin_agents
    known = {tool.name for tool in all_tools()}
    create_builtin_agents()
    for entry in BUILTINS:
        saved = manager.get(entry["id"])
        assert saved.name == entry["name"] and saved.description == entry["description"]
        assert saved.default is False
        allowed = set(saved.tools.get("allowed") or [])
        assert allowed <= known, (entry["id"], sorted(allowed - known))
        if "system_prompt" not in entry:
            continue
        prompt = saved.system_prompt
        assert prompt.startswith("Job: ") and "\nDeliverable: " in prompt and "\nNever:\n- " in prompt
        assert "\nDone when: " in prompt and "\nWorking style:\n- " in prompt and "\nFirst task: " in prompt
        assert saved.tools["mode"] == "selected" and allowed
        assert saved.memory["mode"] == entry["memory"] and saved.memory["write_space"] == "self"
        assert saved.always_on["enabled"] is False and saved.always_on["autonomy"] == "report"
        assert saved.always_on["wake_minutes"] == entry["always_on"]["wake_minutes"]
        assert saved.always_on["research"] is entry["always_on"]["research"]
        assert saved.hold_outbound is True
        assert saved.skills["disabled"] == [] and saved.mcp["disabled"] == []
    # The verifier never edits; the producer does.
    assert not {"edit", "write", "apply_patch"} & set(manager.get("pr-verifier").tools["allowed"])
    assert {"edit", "write"} <= set(manager.get("pr-producer").tools["allowed"])


def test_builtin_agents_install_in_chinese_and_refuse_other_languages(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "_state_root", lambda: tmp_path)
    manager.create("main", name="Main", make_default=True)
    import pytest
    from openprogram.runtime.agent_registry.builtin_agents import create_builtin_agents
    with pytest.raises(ValueError):
        create_builtin_agents(language="fr")
    create_builtin_agents(language="zh")
    assert manager.get("research-desk").name == "研究简报"
    assert manager.get("research-desk").description == "跟踪一个主题，阅读新来源，按计划写带引用的简报。"
    assert manager.get("research-desk").system_prompt.startswith("Job: ")
