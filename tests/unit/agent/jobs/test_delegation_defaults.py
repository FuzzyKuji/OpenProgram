"""The default bounds on delegated agents and the one result shape.

All fake: Jobs are built in memory, the ledger is a stub, the clock is a
number. See docs/reference/design/runtime/collaboration/agent-collaboration.html.
"""
from __future__ import annotations


import pytest

from openprogram.runtime.jobs import agent_result, delegation_watch
from openprogram.runtime.jobs.types import Job, JobStatus


def _job(job_id: str, **kw) -> Job:
    base = dict(id=job_id, parent_session_id="p1", prompt="task", agent_id="main",
                status=JobStatus.RUNNING, caller_session_id="p1", caller_msg_id="a1",
                origin_turn_id="a1")
    base.update(kw)
    return Job(**base)


class _Ledger:
    def __init__(self, costs: dict[str, list[str]], unknown: set[str] = frozenset()):
        self.costs, self.unknown = costs, unknown

    def job_resource_usage(self, job_id):
        return {"cost_values": self.costs.get(job_id, []), "total_tokens": 1200,
                "unknown_cost_events": 1 if job_id in self.unknown else 0}


@pytest.fixture
def config(monkeypatch):
    values: dict = {}
    monkeypatch.setattr("openprogram.state.config.read_config", lambda: {"agent": values})
    return values


def _check(jobs, *, now, ledger=None, entries=None, already=None):
    by_id = {j.id: j for j in jobs}
    cancelled, stalled = [], []
    delegation_watch.check_running(
        entries if entries is not None else [(j.id, j.parent_session_id, 0.0, 0.0) for j in jobs],
        now=now, load=lambda _sid, jid: by_id.get(jid), ledger=ledger or _Ledger({}),
        cancel=lambda jid, reason: cancelled.append((jid, reason)),
        stalled=lambda job: stalled.append(job.id),
        already=already if already is not None else {},
    )
    return cancelled, stalled


def test_defaults_are_the_documented_ones(config):
    from openprogram.programs.tools.agents.send_message.send_message import depth
    from openprogram.runtime.jobs.resource_governance.limits import running_agents_default

    assert delegation_watch.tree_cap_usd() == 2.0
    assert delegation_watch.stall_seconds() == 600
    assert delegation_watch.max_run_seconds() == 7200
    assert depth.max_spawn_depth() == 1
    assert depth.max_hops() == 4 and depth.max_sends_per_hour() == 20
    assert running_agents_default() == 6


def test_a_quiet_helper_is_reported_stalled_once_and_keeps_running(config):
    helper = _job("j1")
    already: dict = {}
    cancelled, stalled = _check([helper], now=601, already=already)
    assert stalled == ["j1"] and cancelled == []
    _, again = _check([helper], now=1200, already=already)
    assert again == []


def test_a_helper_past_the_hard_stop_is_stopped(config):
    cancelled, _ = _check([_job("j1")], now=7200)
    assert cancelled == [("j1", delegation_watch.RUNTIME_REASON)]


def test_settings_change_the_bounds_and_zero_turns_one_off(config):
    config.update(max_agent_hours=0, stall_minutes=1)
    cancelled, stalled = _check([_job("j1")], now=10 * 3600)
    assert cancelled == [] and stalled == ["j1"]


def test_a_tree_past_its_spend_stops_its_running_helpers(config, monkeypatch):
    jobs = [_job("j1"), _job("j2")]
    monkeypatch.setattr(delegation_watch, "tree_jobs", lambda sid, turn: jobs)
    ledger = _Ledger({"j1": ["1.50"], "j2": ["0.60"]})
    entries = [(j.id, "p1", 0.0, 100.0) for j in jobs]
    cancelled, _ = _check(jobs, now=101, ledger=ledger, entries=entries)
    assert sorted(cancelled) == [("j1", delegation_watch.TREE_COST_REASON),
                                 ("j2", delegation_watch.TREE_COST_REASON)]


def test_a_tree_under_its_spend_keeps_running(config, monkeypatch):
    jobs = [_job("j1")]
    monkeypatch.setattr(delegation_watch, "tree_jobs", lambda sid, turn: jobs)
    cancelled, _ = _check(jobs, now=1, ledger=_Ledger({"j1": ["1.99"]}),
                          entries=[("j1", "p1", 0.0, 1.0)])
    assert cancelled == []


def test_a_spawn_past_the_tree_spend_is_refused(config, monkeypatch):
    monkeypatch.setattr(delegation_watch, "tree_jobs", lambda sid, turn: [_job("j1")])
    assert delegation_watch.spawn_refusal("p1", "a1", ledger=_Ledger({"j1": ["2.00"]})) is not None
    assert delegation_watch.spawn_refusal("p1", "a1", ledger=_Ledger({"j1": ["0.10"]})) is None


def test_only_agent_jobs_are_watched():
    assert delegation_watch.watched(_job("j1"))
    assert not delegation_watch.watched(_job("j2", source="self_update"))


# ---- the one result shape -------------------------------------------------

def test_every_result_has_reply_and_usage(monkeypatch):
    monkeypatch.setattr(agent_result, "_tool_calls", lambda job: 3)
    job = _job("j1", status=JobStatus.COMPLETED, label="scout", result_text="found it",
               started_at=100.0, completed_at=142.0)
    out = agent_result.render(job, usage=agent_result.usage_of(job, ledger=_Ledger({"j1": ["0.012"]})))
    assert out.splitlines()[0] == '<agent name="scout" id="j1" status="completed">'
    assert "found it" in out
    assert "42 s" in out and "3 tool calls" in out and "1.2k tokens" in out and "$0.012" in out
    assert out.endswith("</agent>")


def test_an_unknown_price_shows_no_made_up_cost():
    job = _job("j1", status=JobStatus.COMPLETED, started_at=0.0, completed_at=1.0)
    usage = agent_result.usage_of(job, ledger=_Ledger({}, unknown={"j1"}))
    assert usage["cost_usd"] is None


def test_a_limit_stop_names_its_reason():
    job = _job("j1", status=JobStatus.CANCELLED, label="scout",
               reason_code=delegation_watch.TREE_COST_REASON)
    first = agent_result.render(job, reply="", usage={}).splitlines()[0]
    assert 'status="stopped" reason="spend cap"' in first


def test_a_long_reply_is_clipped_with_a_pointer():
    text = agent_result.clip_reply("x" * 30000, "j1")
    assert len(text) < 30000 and "read_conversation" in text and "j1" in text


# ---- saved Agent settings ---------------------------------------------------

def _spec(**kw):
    from openprogram.runtime.agent_registry.manager import AgentSpec
    base = dict(id="a", name="A", description="does a")
    base.update(kw)
    return AgentSpec(**base)


def test_delegation_defaults_follow_tools():
    from openprogram.runtime.agent_registry import delegation
    assert delegation.delegation_enabled(_spec())
    assert not delegation.delegation_enabled(_spec(tools={"mode": "none"}))
    assert not delegation.delegation_enabled(_spec(delegation="off"))
    assert delegation.delegation_enabled(_spec(tools={"mode": "none"}, delegation="on"))


def test_isolation_rule():
    from openprogram.runtime.agent_registry import delegation
    writer = _spec()
    reader = _spec(tools={"mode": "selected", "allowed": ["read", "grep"]})
    assert delegation.isolation_for(writer, requested="", background=True) == ("worktree", True)
    assert delegation.isolation_for(writer, requested="", background=False) == ("", False)
    assert delegation.isolation_for(reader, requested="", background=True) == ("", False)
    assert delegation.isolation_for(_spec(isolation="none"), requested="", background=True) == ("", False)
    assert delegation.isolation_for(reader, requested="worktree", background=False) == ("worktree", False)


def test_roster_lists_only_callable_agents_by_id():
    from openprogram.programs.tools.agents.agent.agent.prompt import roster_text
    from openprogram.runtime.agent_registry import delegation
    rows = delegation.roster([_spec(id="z", name="Zed"), _spec(id="b", name="Bee"),
                              _spec(id="off", delegation="off")])
    assert [r[0] for r in rows] == ["b", "z"]
    text = roster_text(rows)
    assert "- Bee (b) — does a" in text and "off" not in text


def test_find_by_name_or_id():
    from openprogram.runtime.agent_registry import delegation
    rows = [_spec(id="explorer", name="Explorer")]
    assert delegation.find("explorer", rows).id == "explorer"
    assert delegation.find("EXPLORER", rows).id == "explorer"
    assert delegation.find("nobody", rows) is None


def test_explorer_is_read_only():
    from openprogram.runtime.agent_registry import builtin_agents, delegation
    explorer = builtin_agents.builtin("explorer")
    allowed = set(explorer["tools"]["allowed"])
    assert not allowed & delegation.WRITE_TOOLS


def test_model_facing_collaboration_tools_are_five():
    from openprogram.programs import get_agent_tool
    for name in ("agent", "send_message", "list_agents", "read_conversation", "close_agent"):
        assert get_agent_tool(name) is not None, name
    for name in ("handoff", "job_output", "list_jobs", "archive_agent"):
        assert get_agent_tool(name) is None, name


def test_agent_tool_has_no_model_override():
    from openprogram.programs import get_agent_tool
    tool = get_agent_tool("agent")
    props = (getattr(tool, "parameters", None) or {}).get("properties", {})
    assert "model" not in props and "to" not in props
    assert props["start_from"]


# ---- close_agent ------------------------------------------------------------

def test_close_agent_stops_then_archives_its_own_helper(monkeypatch):
    import importlib
    module = importlib.import_module(
        "openprogram.programs.tools.agents.send_message.close_agent.close_agent")

    running = _job("j1", label="scout", head_id="h1")
    calls: list = []

    class _Runner:
        def get_job(self, job_id):
            return running if job_id == "j1" else None

        def _cancel_cascade(self, job_id, *, reason, root_reason_code):
            calls.append(("cancel", job_id, root_reason_code))
            running.status = JobStatus.CANCELLED

    monkeypatch.setattr("openprogram.runtime.jobs.get_runner", lambda: _Runner())
    monkeypatch.setattr("openprogram.programs.tools.agents.agent._ownership.check_job_ownership",
                        lambda job_id, tool: None)
    archive = importlib.import_module(
        "openprogram.programs.tools.agents.send_message.archive_agent.archive_agent")
    monkeypatch.setattr(archive, "_archive_agent_impl",
                        lambda address, reason="": calls.append(("archive", address)) or "[archive_agent] done")
    monkeypatch.setattr("openprogram.runtime.jobs.notices.consume", lambda job: calls.append(("consume", job.id)))

    out = module._close_agent_impl("j1")
    assert calls == [("cancel", "j1", "cancel.parent"), ("archive", "p1:h1"), ("consume", "j1")]
    assert out.startswith("[close_agent] scout: stopped and archived.")


def test_close_agent_refuses_work_it_did_not_start(monkeypatch):
    import importlib
    module = importlib.import_module(
        "openprogram.programs.tools.agents.send_message.close_agent.close_agent")

    class _Runner:
        def get_job(self, job_id):
            return _job("j1")

        def _cancel_cascade(self, *a, **k):
            raise AssertionError("must not stop another conversation's work")

    monkeypatch.setattr("openprogram.runtime.jobs.get_runner", lambda: _Runner())
    monkeypatch.setattr("openprogram.programs.tools.agents.agent._ownership.check_job_ownership",
                        lambda job_id, tool: "[close_agent refused] not yours")
    assert module._close_agent_impl("j1") == "[close_agent refused] not yours"


def test_close_agent_archives_a_helper_stopped_mid_turn(monkeypatch):
    """A job stopped mid-turn has no head_id yet; its branch ends at the
    reply admission named for it, and that tip is what gets archived."""
    import importlib
    from types import SimpleNamespace
    module = importlib.import_module(
        "openprogram.programs.tools.agents.send_message.close_agent.close_agent")

    running = _job("j1", label="scout", head_id=None)
    calls: list = []

    class _Store:
        def get_execution_input(self, job_id):
            return SimpleNamespace(assistant_message_id=f"{job_id}_user_reply")

    class _Runner:
        _execution_store = _Store()

        def get_job(self, job_id):
            return running if job_id == "j1" else None

        def _cancel_cascade(self, job_id, *, reason, root_reason_code):
            running.status = JobStatus.CANCELLED

    monkeypatch.setattr("openprogram.runtime.jobs.get_runner", lambda: _Runner())
    monkeypatch.setattr("openprogram.programs.tools.agents.agent._ownership.check_job_ownership",
                        lambda job_id, tool: None)
    archive = importlib.import_module(
        "openprogram.programs.tools.agents.send_message.archive_agent.archive_agent")
    monkeypatch.setattr(archive, "_archive_agent_impl",
                        lambda address, reason="": calls.append(address) or "[archive_agent] done")
    monkeypatch.setattr("openprogram.runtime.jobs.notices.consume", lambda job: None)

    out = module._close_agent_impl("j1")
    assert calls == ["p1:j1_user_reply"]
    assert out.startswith("[close_agent] scout: stopped and archived.")
