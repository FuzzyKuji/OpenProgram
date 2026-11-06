"""Errors in memory writing are repaired by an agent, not only reported.

Staged edits that fail the checks go back to the agent to fix in place,
committed Topic files broken by a hand edit are fixed before any writer
runs, and a writer model this account cannot use is swapped for one it can.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.component.memory.test_memory_history_commits import _record, _write


class _ScriptedAgent:
    """Runs no model: each run applies the next scripted edit to the stage."""

    def __init__(self, *edits):
        self.edits = list(edits)
        self.prompts: list[str] = []

    def run(self, *, prompt, cwd, **_kwargs):
        self.prompts.append(prompt)
        if self.edits:
            self.edits.pop(0)(Path(cwd))
        return SimpleNamespace(
            turns=[], reply="done", text="done", num_turns=1,
            input_tokens=1, output_tokens=1, stop_reason="end_turn",
            anthropic_equivalent_cost_usd=0.0,
        )


@pytest.fixture
def no_tools(monkeypatch):
    from openprogram.state.memory.management import agent as agent_module

    monkeypatch.setattr(agent_module, "management_tools", lambda ws, audit: [])


@pytest.fixture
def memory(tmp_path: Path, chats):
    from openprogram.state.memory.store import _ensure_git_history

    root = tmp_path / "memory"
    (root / "topics").mkdir(parents=True)
    first, second = _record(chats, "m1", "tea", 1), _record(chats, "m2", "walks", 2)
    _ensure_git_history(root)
    _write(root, first, "topics/tea.md", "Owner likes tea.")
    return root, second


def _subjects(root: Path) -> list[str]:
    return subprocess.run(
        ["git", "-C", str(root), "log", "--format=%s"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()


def test_failing_edits_are_fixed_in_place_not_redone(memory, no_tools):
    from openprogram.state.memory.chat_refs import link
    from openprogram.state.memory.management import agent as agent_module

    root, second = memory

    def write_uncited(stage: Path):
        (stage / "topics/walks.md").write_text("# Walks\n\nOwner walks daily.[^e1]\n")

    def add_definition(stage: Path):
        path = stage / "topics/walks.md"
        path.write_text(
            path.read_text()
            + f"\n[^e1]: Time: `2026-08-10`; Sources: [note]({link(second.ref)})\n"
        )

    agent = _ScriptedAgent(write_uncited, add_definition)
    agent_module._run_agent(
        root, agent=agent, task="write walks",
        allowed_new_source_refs={second.ref},
    )

    assert len(agent.prompts) == 2
    assert "fail the memory checks" in agent.prompts[1]
    assert "undefined footnote" in agent.prompts[1]
    assert "Owner walks daily." in (root / "topics/walks.md").read_text()


def test_fixing_stops_after_the_last_round(memory, no_tools):
    from openprogram.state.memory.management import agent as agent_module
    from openprogram.state.memory.writing import _declined

    root, second = memory

    def write_uncited(stage: Path):
        (stage / "topics/walks.md").write_text("# Walks\n\nOwner walks daily.[^e1]\n")

    agent = _ScriptedAgent(write_uncited)
    audit = agent_module._run_agent(
        root, agent=agent, task="write walks",
        allowed_new_source_refs={second.ref},
    )
    # The turn, its fix rounds, then the redo, which staged nothing.
    assert len(agent.prompts) == 1 + agent_module.FIX_ROUNDS + 1
    assert not (root / "topics/walks.md").exists()
    assert not _declined(audit), "a rejected batch stays unwritten"


def test_a_hand_broken_topic_is_repaired_before_the_writer_runs(memory, no_tools):
    from openprogram.state.memory.management import agent as agent_module
    from openprogram.state.memory.markdown import parse_topic_tree

    root, _second = memory
    tea = root / "topics/tea.md"
    good = tea.read_text()
    block_ids = {unit.memory_id for unit in parse_topic_tree(root / "topics")}
    tea.write_text(
        "\n".join(line for line in good.splitlines() if not line.startswith("[^"))
        + "\n"
    )

    def restore(stage: Path):
        (stage / "topics/tea.md").write_text(good)

    agent = _ScriptedAgent(restore)
    agent_module._run_agent(root, agent=agent, task="organize")

    assert "topics/tea.md: undefined footnote" in agent.prompts[0]
    assert len(agent.prompts) == 2, "the repair, then the writer's own turn"
    assert {unit.memory_id for unit in parse_topic_tree(root / "topics")} == block_ids
    assert _subjects(root)[:2] == [
        "memory: repair topic format", "memory: edits made outside OpenProgram",
    ]


def test_an_unrepaired_topic_stops_the_writer_instead_of_dropping_its_turn(
    memory, no_tools,
):
    from openprogram.state.memory.management import agent as agent_module
    from openprogram.state.memory.management.transaction import TransactionError

    root, _second = memory
    tea = root / "topics/tea.md"
    tea.write_text(
        "\n".join(l for l in tea.read_text().splitlines() if not l.startswith("[^"))
        + "\n"
    )

    agent = _ScriptedAgent()
    with pytest.raises(TransactionError) as caught:
        agent_module._run_agent(root, agent=agent, task="organize")
    assert caught.value.code == "INVALID_TOPIC_FORMAT"

    from openprogram.state.memory.backend import classify_memory_write_failure

    # Not the conversation's fault: its write waits for the next repair.
    assert classify_memory_write_failure(caught.value).retryable is True
    prompts = len(agent.prompts)

    # The same broken file is not handed to another agent until it changes.
    with pytest.raises(TransactionError):
        agent_module._run_agent(root, agent=agent, task="organize")
    assert len(agent.prompts) == prompts
    tea.write_text(tea.read_text() + "\nMore.\n")
    with pytest.raises(TransactionError):
        agent_module._run_agent(root, agent=agent, task="organize")
    assert len(agent.prompts) > prompts


def test_an_unusable_writer_model_falls_back_to_one_that_works(monkeypatch):
    from openprogram.runtime.conversation import memory_agent as module
    from openprogram.state.memory.agent_runtime.claude_code import AgentExecutionError
    from openprogram.models.providers.types import Model

    def model(model_id: str) -> Model:
        return Model(id=model_id, name=model_id, api="a", provider="p",
                     base_url="http://scripted.invalid")

    monkeypatch.setattr(module, "_default_model", lambda override: model("configured"))
    monkeypatch.setattr(
        module, "_fallback_models", lambda: [model("configured"), model("chat")]
    )
    used: list[str] = []

    def run_once(self, **_kwargs):
        used.append(self.model.id)
        if self.model.id == "configured":
            raise AgentExecutionError(
                "model not supported with this account",
                reason="invalid", retryable=False,
            )
        return "written"

    monkeypatch.setattr(module.OpenProgramAgent, "_run_once", run_once)
    writer = module.OpenProgramAgent(model="configured")

    assert writer.run(prompt="p", system_prompt="s", cwd=".") == "written"
    assert used == ["configured", "chat"]
    assert writer.model.id == "chat"


@pytest.mark.parametrize("reason,retryable,turns,falls_back", [
    ("rate_limit", True, [], False),
    ("rate_limit", False, [], True),
    ("auth", None, [], True),
    ("invalid", False, [{"tool": "Write"}], False),
    ("transport", False, [], False),
])
def test_only_an_unusable_model_before_any_edit_falls_back(
    monkeypatch, reason, retryable, turns, falls_back,
):
    from openprogram.runtime.conversation import memory_agent as module
    from openprogram.state.memory.agent_runtime.claude_code import AgentExecutionError
    from openprogram.models.providers.types import Model

    def model(model_id: str) -> Model:
        return Model(id=model_id, name=model_id, api="a", provider="p",
                     base_url="http://scripted.invalid")

    monkeypatch.setattr(module, "_default_model", lambda override: model("configured"))
    monkeypatch.setattr(module, "_fallback_models", lambda: [model("chat")])

    def run_once(self, **_kwargs):
        if self.model.id == "configured":
            raise AgentExecutionError(
                "failed", turns, reason=reason, retryable=retryable,
            )
        return "written"

    monkeypatch.setattr(module.OpenProgramAgent, "_run_once", run_once)
    writer = module.OpenProgramAgent()
    if falls_back:
        assert writer.run(prompt="p", system_prompt="s", cwd=".") == "written"
    else:
        with pytest.raises(AgentExecutionError):
            writer.run(prompt="p", system_prompt="s", cwd=".")
