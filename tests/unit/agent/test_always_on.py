"""Always-on: an Agent configuration whose conversations wake, check in and report."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from openprogram.runtime.conversation.always_on import delivery, runtime, store, ticker
from openprogram.runtime.agent_registry import manager


class FakeDb:
    def __init__(self, root):
        self.root = root
        self.sessions: dict[str, dict] = {}

    def get_session(self, sid):
        return self.sessions.get(sid)

    def create_session(self, sid, agent_id, *, source="", updated_at=0.0, **extra):
        self.sessions[sid] = {"id": sid, "agent_id": agent_id, "source": source,
                              "archived": False, "updated_at": updated_at, **extra}
        (self.root / sid).mkdir(parents=True, exist_ok=True)
        return sid

    def _session_dir(self, sid):
        return self.root / sid

    def list_sessions(self, *, agent_id=None, limit=100, **_):
        return [row for row in self.sessions.values()
                if agent_id in (None, row["agent_id"]) and not row["archived"]][:limit]

    def update_session(self, sid, **fields):
        self.sessions[sid].update(fields)


@pytest.fixture
def agent():
    agent_id = "dot" + uuid.uuid4().hex[:8]
    manager.create(agent_id, name="Scout")
    yield agent_id
    manager.delete(agent_id)


@pytest.fixture
def world(monkeypatch, tmp_path):
    db = FakeDb(tmp_path / "sessions")
    calls = {"turns": [], "goals": [], "started": [], "frames": []}
    goals: dict[str, dict] = {}
    running: set[str] = set()
    monkeypatch.setattr(runtime, "_db", lambda: db)
    monkeypatch.setattr("openprogram.runtime.context.session_db.default_db", lambda: db)
    monkeypatch.setattr(runtime, "_goal", lambda sid: goals.get(sid))
    monkeypatch.setattr(runtime, "_turn_running", lambda sid: sid in running)
    monkeypatch.setattr(runtime, "_broadcast", lambda frame: calls["frames"].append(frame))

    def start_turn(sid, agent_id, text, tools):
        calls["turns"].append({"sid": sid, "agent_id": agent_id, "text": text, "tools": tools})
        return "exec"
    monkeypatch.setattr(runtime, "_start_turn", start_turn)

    from openprogram.programs.tools.planning.goal import chat

    def create(sid, objective, *args, **kwargs):
        goals[sid] = {"text": objective, "status": "active", "goal_id": "g" + str(len(calls["goals"])),
                      "origin": kwargs.get("origin")}
        calls["goals"].append((sid, objective))
        return goals[sid]
    monkeypatch.setattr(chat, "create", create)
    monkeypatch.setattr(chat, "start_from_controls", lambda sid, source="web": calls["started"].append((sid, source)))
    return {"db": db, "goals": goals, "running": running, "calls": calls}


def enable(agent_id, **config):
    return manager.update(agent_id, {"always_on": {"enabled": True, **config}})


def test_configuration_defaults_validation_and_duplicate(agent):
    spec = manager.get(agent)
    assert spec.always_on == {"enabled": False, "goal": "", "wake_minutes": 60,
                              "research": True, "autonomy": "report", "channels": [],
                              "quiet_hours": None, "wake_days": [0, 1, 2, 3, 4, 5, 6]}
    assert manager.validate_always_on({"goal": "  watch CI  "}, partial=True) == {"goal": "watch CI"}
    assert manager.validate_always_on(
        {"quiet_hours": {"start": "22:00", "end": "08:00"}, "wake_days": [4, 0, 0]}, partial=True,
    ) == {"quiet_hours": {"start": "22:00", "end": "08:00"}, "wake_days": [0, 4]}
    for bad in ({"wake_minutes": 1}, {"wake_minutes": True}, {"autonomy": "always"},
                {"enabled": "yes"}, {"goal": "x" * 4001}, {"unknown": 1},
                {"quiet_hours": {"start": "22:00"}}, {"quiet_hours": {"start": "25:00", "end": "08:00"}},
                {"quiet_hours": {"start": "8:00", "end": "09:00"}}, {"quiet_hours": {"start": "08:00", "end": "08:00"}},
                {"wake_days": []}, {"wake_days": [7]}, {"wake_days": [True]}):
        with pytest.raises(ValueError):
            manager.validate_always_on(bad, partial=True)
    enable(agent, goal="Watch CI", wake_minutes=30)
    saved = manager.get(agent).always_on
    assert saved["enabled"] and saved["goal"] == "Watch CI" and saved["wake_minutes"] == 30
    assert saved["research"] is True
    copy = manager.duplicate(agent, name="Scout copy")
    try:
        assert copy.always_on["enabled"] is False
        assert copy.always_on["goal"] == "Watch CI"
    finally:
        manager.delete(copy.id)
    legacy = manager.AgentSpec.from_dict({"id": "legacy"})
    assert legacy.always_on["enabled"] is False


def test_wake_refuses_when_off_and_records_scheduled_skips(agent, world):
    sid = world["db"].create_session("c1", agent)
    with pytest.raises(runtime.WakeRefused):
        runtime.wake(sid, reason="manual")
    result = runtime.wake(sid, reason="schedule")
    assert result["outcome"] == "disabled"
    assert store.load_state(sid)["next_wake_at"] is None
    assert not world["calls"]["turns"]
    with pytest.raises(runtime.WakeRefused):
        runtime.wake("missing")


def test_each_conversation_runs_the_standing_goal_once(agent, world):
    enable(agent, goal="Keep the docs links green")
    sid = world["db"].create_session("c1", agent)
    other = world["db"].create_session("c2", agent)
    first = runtime.wake(sid, reason="schedule")
    assert first["outcome"] == "goal_started" and first["session_id"] == sid
    assert world["calls"]["goals"] == [(sid, "Keep the docs links green")]
    assert world["goals"][sid]["origin"] == "always_on"
    assert world["calls"]["started"] == [(sid, "web")]
    assert runtime.wake(sid)["outcome"] == "goal_in_progress"
    # Another conversation with the same Agent is its own bot.
    assert runtime.wake(other)["outcome"] == "goal_started"
    world["goals"][sid]["status"] = "paused"
    assert runtime.wake(sid)["outcome"] == "goal_paused"
    # An achieved goal is not restarted; the conversation checks in instead.
    world["goals"][sid]["status"] = "achieved"
    assert runtime.wake(sid)["outcome"] == "check_in"
    assert [goal for goal in world["calls"]["goals"] if goal[0] == sid] == [(sid, "Keep the docs links green")]
    # A new standing goal replaces an ended one.
    enable(agent, goal="Triage new issues")
    assert runtime.wake(sid)["outcome"] == "goal_started"
    assert world["calls"]["goals"][-1] == (sid, "Triage new issues")


def test_changed_goal_waits_for_the_unfinished_one(agent, world):
    enable(agent, goal="First")
    sid = world["db"].create_session("c1", agent)
    runtime.wake(sid)
    enable(agent, goal="Second")
    assert runtime.wake(sid)["outcome"] == "goal_in_progress"
    world["goals"][sid]["status"] = "cleared"
    assert runtime.wake(sid)["outcome"] == "goal_started"
    assert world["calls"]["goals"][-1] == (sid, "Second")


def test_busy_idle_and_check_in_tools(agent, world):
    sid = world["db"].create_session("c1", agent)
    enable(agent, research=False)
    assert runtime.wake(sid)["outcome"] == "idle"
    assert not world["calls"]["turns"]
    enable(agent, research=True)
    assert runtime.wake(sid)["outcome"] == "check_in"
    turn = world["calls"]["turns"][-1]
    assert turn["sid"] == sid and turn["agent_id"] == agent
    assert "always_on_report" in turn["tools"] and "open_work" in turn["tools"] and "bash" not in turn["tools"]
    assert "create_goal" not in turn["tools"]
    assert "This is your first check-in." in turn["text"]
    assert "Do not start work yourself" in turn["text"]
    world["running"].add(sid)
    assert runtime.wake(sid)["outcome"] == "busy"
    world["running"].clear()
    enable(agent, autonomy="act")
    runtime.wake(sid)
    turn = world["calls"]["turns"][-1]
    assert "create_goal" in turn["tools"] and "todo_create" in turn["tools"]
    assert "previous check-in was" in turn["text"]


def test_sub_agent_imported_and_archived_conversations_never_wake(agent, world):
    enable(agent)
    db = world["db"]
    for sid, source in (("sub", "agent"), ("imp", "import")):
        db.create_session(sid, agent, source=source)
        with pytest.raises(runtime.WakeRefused):
            runtime.wake(sid)
    db.create_session("arch", agent, archived=True)
    assert runtime.agent_for_session("arch") is None
    db.create_session("tg", agent, source="telegram", channel="telegram")
    assert runtime.agent_for_session("tg") == agent


def test_reports_belong_to_the_conversation(agent, world):
    enable(agent)
    sid = world["db"].create_session("c1", agent)
    other_agent = world["db"].create_session("c2", "main-" + agent)
    with pytest.raises(ValueError):
        runtime.report(other_agent, "Hi", "body")
    row = runtime.report(sid, "  Found a broken link ", "docs/x.md", ["https://example.com", ""])
    assert row["title"] == "Found a broken link" and row["links"] == ["https://example.com"]
    # The sidebar shows the conversation unread as soon as it reports.
    assert world["db"].sessions[sid]["unread"] is True
    frame = world["calls"]["frames"][-1]
    assert frame["type"] == "always_on_report"
    assert frame["data"]["agent_name"] == "Scout" and frame["data"]["session_id"] == sid
    status = runtime.status(sid)
    assert status["enabled"] and status["reports"][0]["id"] == row["id"]
    assert status["agent_name"] == "Scout"
    assert runtime.agent_for_session(sid) == agent
    enable(agent, enabled=False)
    assert runtime.agent_for_session(sid) is None
    assert runtime.status(sid)["enabled"] is False


TELEGRAM = {"channel": "telegram", "account_id": "default", "peer_id": "42", "label": "Bob"}
SLACK = {"channel": "slack", "account_id": "work", "peer_id": "C1_U1", "label": "#ops"}


def test_channel_targets_are_validated_and_deduplicated():
    out = manager.validate_always_on({"channels": [
        {**TELEGRAM, "account_id": " default "}, TELEGRAM, {"channel": "slack", "account_id": "work", "peer_id": "C1_U1"},
    ]}, partial=True)
    assert out["channels"] == [TELEGRAM, {**SLACK, "label": ""}]
    for bad in ([{"channel": "email", "account_id": "a", "peer_id": "b"}],
                [{"channel": "telegram", "account_id": "a"}],
                [{"channel": "telegram", "account_id": "", "peer_id": "b"}],
                [{**TELEGRAM, "extra": 1}],
                [{**TELEGRAM, "peer_id": str(index)} for index in range(11)],
                "telegram"):
        with pytest.raises(ValueError):
            manager.validate_always_on({"channels": bad}, partial=True)


def _capture_deliveries(monkeypatch):
    threads = []
    original = delivery.deliver

    def deliver(*args, **kwargs):
        thread = original(*args, **kwargs)
        threads.append(thread)
        return thread
    monkeypatch.setattr(delivery, "deliver", deliver)
    return threads


def test_report_is_sent_to_picked_channels_and_failures_are_recorded(agent, world, monkeypatch):
    from openprogram.interfaces.channels import outbound
    from openprogram.interfaces.channels._transport import SendResult

    enable(agent, channels=[TELEGRAM, SLACK])
    sid = world["db"].create_session("c1", agent)
    sent = []

    def send_full(channel, account_id, peer_id, text):
        sent.append((channel, account_id, peer_id, text))
        if channel == "slack":
            raise RuntimeError("socket closed")
        return SendResult.success("m1")
    monkeypatch.setattr(outbound, "send_full", send_full)
    threads = _capture_deliveries(monkeypatch)

    row = runtime.report(sid, "CI is red", "main fails on test_x", ["https://ci.example/1"])
    assert [item["status"] for item in row["deliveries"]] == ["sending", "sending"]
    threads[0].join(5)
    assert [item[:3] for item in sent] == [("telegram", "default", "42"), ("slack", "work", "C1_U1")]
    assert sent[0][3] == "**Scout · CI is red**\n\nmain fails on test_x\n\n- https://ci.example/1"
    saved = store.load_reports(sid)[0]["deliveries"]
    assert saved[0] == {**TELEGRAM, "status": "sent"}
    assert saved[1]["status"] == "failed" and saved[1]["error"] == "unknown"
    assert "socket closed" in saved[1]["detail"]
    assert world["calls"]["frames"][-1] == {"type": "always_on_update",
                                            "data": {"session_id": sid, "agent_id": agent}}


def test_report_without_channels_stays_in_the_app(agent, world, monkeypatch):
    from openprogram.interfaces.channels import outbound

    enable(agent)
    sid = world["db"].create_session("c1", agent)
    monkeypatch.setattr(outbound, "send_full", lambda *args: pytest.fail("nothing to send"))
    threads = _capture_deliveries(monkeypatch)
    row = runtime.report(sid, "Quiet", "")
    assert "deliveries" not in row and threads == [None]


def test_channel_targets_come_from_conversations_and_peer_bindings(agent, monkeypatch):
    from openprogram.runtime.context import session_db
    from openprogram.interfaces.channels import bindings

    rows = [
        {"id": "s1", "channel": "telegram", "account_id": "default", "peer_id": "42", "peer_display": "Bob"},
        {"id": "s2", "channel": "telegram", "account_id": "default", "peer_id": "42", "peer_display": "Bob"},
        {"id": "s3", "source": "web"},
        {"id": "s4", "channel": "email", "account_id": "x", "peer_id": "y"},
    ]

    class Db:
        def list_sessions(self, *, agent_id, **_):
            assert agent_id == agent
            return rows
    monkeypatch.setattr(session_db, "default_db", lambda: Db())
    added = [
        bindings.add(agent, {"channel": "slack", "account_id": "work", "peer": {"kind": "group", "id": "C1_U1"}}),
        bindings.add(agent, {"channel": "telegram", "account_id": "default"}),
    ]
    try:
        assert delivery.channel_targets(agent) == [
            {"channel": "telegram", "account_id": "default", "peer_id": "42", "label": "Bob"},
            {"channel": "slack", "account_id": "work", "peer_id": "C1_U1", "label": "C1_U1"},
        ]
    finally:
        for row in added:
            bindings.remove(row["id"])


def test_update_report_merges_into_the_stored_row(world):
    sid = world["db"].create_session("c1", "scout")
    row = store.add_report(sid, title="r", body="")
    assert row["session_id"] == sid
    assert store.update_report(sid, row["id"], deliveries=[{"status": "sent"}])["deliveries"] == [{"status": "sent"}]
    assert store.load_reports(sid)[0]["deliveries"] == [{"status": "sent"}]
    assert store.update_report(sid, "missing", deliveries=[]) is None
    assert store.load_reports("gone") == []
    with pytest.raises(ValueError):
        store.add_report("gone", title="r", body="")


def test_reports_are_trimmed_newest_first(world, monkeypatch):
    sid = world["db"].create_session("c1", "scout")
    monkeypatch.setattr(store, "MAX_REPORTS", 3)
    for index in range(5):
        store.add_report(sid, title=f"r{index}", body="")
    assert [row["title"] for row in store.load_reports(sid)] == ["r4", "r3", "r2"]


def test_a_conversation_joins_when_used_after_always_on_is_turned_on(agent, world):
    db = world["db"]
    db.create_session("old", agent, updated_at=50.0)
    assert ticker.due_sessions(100.0) == []
    enable(agent, research=False, wake_minutes=10)
    # Turned on at 100: the old conversation stays quiet; a new one joins and
    # waits one interval before its first wake.
    assert ticker.due_sessions(100.0) == []
    assert store.load_state("old") == {}
    db.create_session("new", agent, updated_at=150.0)
    assert ticker.due_sessions(200.0) == []
    assert store.load_state("new")["next_wake_at"] == 200.0 + 600
    assert ticker.due_sessions(799.0) == []
    assert ticker.due_sessions(800.0) == ["new"]
    # Using the old conversation again brings it in too.
    db.sessions["old"]["updated_at"] = 900.0
    ticker.due_sessions(900.0)
    assert store.load_state("old")["joined_at"] == 900.0
    # Archiving stops the wakes.
    db.sessions["new"]["archived"] = True
    assert "new" not in ticker.due_sessions(10_000.0)


def test_a_conversation_started_before_the_first_tick_still_joins(agent, world, monkeypatch):
    enable(agent, wake_minutes=10)
    saved_at = manager.get(agent).updated_at
    world["db"].create_session("c1", agent, updated_at=saved_at + 1)
    ticker.due_sessions(saved_at + 20)
    assert store.load_agent_state(agent)["enabled_at"] == saved_at
    assert store.load_state("c1")["joined_at"] == saved_at + 20


def test_tick_wakes_due_conversations_and_reschedules(agent, world, monkeypatch):
    db = world["db"]
    enable(agent, research=False, wake_minutes=10)
    db.create_session("c1", agent, updated_at=1e12)
    ticker.due_sessions(1000.0)
    monkeypatch.setattr(ticker.time, "time", lambda: 1600.0)
    results = ticker.tick()
    assert [(row["session_id"], row["outcome"]) for row in results] == [("c1", "idle")]
    assert store.load_state("c1")["next_wake_at"] >= 1600.0


def test_turning_always_on_off_and_on_again_restarts_the_count(agent, world):
    db = world["db"]
    enable(agent, wake_minutes=10)
    db.create_session("c1", agent, updated_at=1e12)
    ticker.due_sessions(1000.0)
    enable(agent, enabled=False)
    assert ticker.due_sessions(5000.0) == []
    assert store.load_agent_state(agent)["enabled_at"] is None
    enable(agent, wake_minutes=10)
    # Its old next wake is from before the restart: count from now instead.
    assert ticker.due_sessions(9000.0) == []
    assert store.load_state("c1")["next_wake_at"] == 9000.0 + 600


def test_an_older_home_conversation_keeps_its_state(agent, world):
    db = world["db"]
    db.create_session("home", agent, source="always_on", updated_at=1.0)
    store.update_agent_state(agent, home_session_id="home", last_check_in_at=5.0,
                             applied_goal={"text": "Watch CI"}, next_wake_at=20.0)
    enable(agent, goal="Watch CI")
    ticker.due_sessions(100.0)
    state = store.load_state("home")
    assert state["applied_goal"] == {"text": "Watch CI"} and state["last_check_in_at"] == 5.0
    assert runtime.wake("home")["outcome"] == "check_in"


@pytest.mark.parametrize("home,spawned", [(True, False), (False, False), (True, True)])
def test_report_and_handoff_are_offered_only_in_always_on_conversations(monkeypatch, home, spawned):
    from openprogram.runtime.conversation import turn_runtime as dispatcher
    from openprogram.runtime.conversation.turn_runtime import loop_runner
    from openprogram.runtime.agent.turn_request import TurnRequest
    from openprogram.models.providers.types import AgentTool
    from openprogram.models.providers.types import Model

    model = Model(id="fake", name="fake", api="openai-completions", provider="openai",
                  base_url="https://example.invalid/v1")
    tools = [AgentTool(name=name, label=name, description=name,
                       parameters={"type": "object"}, execute=lambda *args: None)
             for name in ("read", "always_on_report", "handoff")]
    monkeypatch.setattr(dispatcher, "_load_agent_profile", lambda *a: {})
    monkeypatch.setattr(dispatcher, "_resolve_model", lambda *a: model)
    monkeypatch.setattr(loop_runner, "_resolve_tools", lambda *a, **k: list(tools))
    monkeypatch.setattr(loop_runner, "_wrap_with_approval", lambda tool, *a: tool)
    monkeypatch.setattr("openprogram.runtime.context.components.build_system_prompt", lambda *a, **k: "system")
    monkeypatch.setattr("openprogram.programs.tools.planning.goal.chat.instructions", lambda *a: "")
    monkeypatch.setattr("openprogram.runtime.conversation.always_on.agent_for_session",
                        lambda sid: "scout" if home else None)
    request = TurnRequest("home", "check in", "scout", "web", advance_head=not spawned)
    request._execution_revision_id = "test-revision"
    names = {tool["name"] for tool in loop_runner.resolve_agent_runtime(request)[-1]["tools"]}
    assert ("always_on_report" in names) is home
    # A sub-agent's turn in the conversation does not hand work over.
    assert ("handoff" in names) is (home and not spawned)
    assert "read" in names


def test_report_tool_is_registered_outside_the_default_set():
    import openprogram.programs.tools  # noqa: F401
    from openprogram.programs import DEFAULT_TOOLS, agent_tools
    assert "always_on_report" not in DEFAULT_TOOLS
    assert [tool.name for tool in agent_tools(names=["always_on_report"])] == ["always_on_report"]


def _local(day: int, hour: int, minute: int = 0) -> float:
    """A local time on the given weekday (Monday 0) of a fixed week."""
    from datetime import datetime, timedelta
    monday = datetime(2026, 11, 2)
    assert monday.weekday() == 0
    return (monday + timedelta(days=day, hours=hour, minutes=minute)).timestamp()


def test_quiet_hours_and_wake_days_move_the_next_wake():
    from openprogram.runtime.conversation.always_on import schedule
    night = {"quiet_hours": {"start": "22:00", "end": "08:00"}, "wake_days": list(schedule.ALL_DAYS)}
    assert not schedule.is_quiet(_local(0, 12), night)
    assert schedule.is_quiet(_local(0, 23), night) and schedule.is_quiet(_local(1, 7, 59), night)
    assert not schedule.is_quiet(_local(1, 8), night)
    assert schedule.next_allowed(_local(0, 12), night) == _local(0, 12)
    assert schedule.next_allowed(_local(0, 23, 30), night) == _local(1, 8)
    assert schedule.next_allowed(_local(1, 3), night) == _local(1, 8)
    lunch = {"quiet_hours": {"start": "12:00", "end": "13:30"}}
    assert schedule.next_allowed(_local(2, 12, 15), lunch) == _local(2, 13, 30)
    # Weekdays only, quiet at night: Friday night waits until Monday 08:00.
    workweek = {**night, "wake_days": [0, 1, 2, 3, 4]}
    assert schedule.is_quiet(_local(5, 12), workweek)
    assert schedule.next_allowed(_local(4, 22, 30), workweek) == _local(7, 8)
    # Weekends only, no quiet hours: Monday morning waits until Saturday 00:00.
    weekend = {"wake_days": [5, 6]}
    assert schedule.next_allowed(_local(0, 9), weekend) == _local(5, 0)


def test_scheduled_wakes_skip_quiet_hours_and_wake_now_does_not(agent, world):
    enable(agent, wake_minutes=60, quiet_hours={"start": "22:00", "end": "08:00"})
    sid = world["db"].create_session("c1", agent)
    # One interval after 21:30 lands in quiet hours: the next wake is 08:00.
    runtime.join(sid, now=_local(0, 21, 30))
    assert store.load_state(sid)["next_wake_at"] == _local(1, 8)
    # A wake saved before quiet hours were set is skipped to their end.
    result = runtime.wake(sid, reason="schedule", now=_local(0, 23))
    assert result["outcome"] == "quiet" and result["next_wake_at"] == _local(1, 8)
    assert not world["calls"]["turns"]
    store.update_state(sid, next_wake_at=_local(0, 23))
    assert runtime.status(sid)["next_wake_at"] == _local(1, 8)
    assert runtime.status(sid)["config"]["quiet_hours"] == {"start": "22:00", "end": "08:00"}
    # Wake now runs whatever the time.
    assert runtime.wake(sid, reason="manual", now=_local(0, 23))["outcome"] == "check_in"
    assert runtime.wake(sid, reason="schedule", now=_local(1, 9))["outcome"] == "check_in"


def test_ticker_skips_a_quiet_wake(agent, world):
    db = world["db"]
    enable(agent, research=False, wake_minutes=10, wake_days=[0, 1, 2, 3, 4])
    db.create_session("c1", agent, updated_at=1e12)
    ticker.due_sessions(_local(4, 23, 55))
    # Friday 23:55 + 10 minutes: no wakes on the weekend, so Monday 00:00.
    assert store.load_state("c1")["next_wake_at"] == _local(7, 0)
    store.update_state("c1", next_wake_at=_local(5, 1))
    results = ticker.tick(_local(5, 2))
    assert [row["outcome"] for row in results] == ["quiet"]
    assert store.load_state("c1")["next_wake_at"] == _local(7, 0)


@pytest.fixture
def handoffs(monkeypatch, world):
    """Handoff delivery with wake turns recorded instead of run."""
    from types import SimpleNamespace
    from openprogram.runtime.conversation import owner_turn
    from openprogram.runtime.conversation.always_on import handoff

    turns: list[dict] = []
    busy: set[str] = set()
    # Conversations whose turns keep running: their on_done waits here.
    held: dict[str, list] = {}

    def start(session_id, agent_id, text, *, msg_id=None, on_done=None, **_kw):
        if session_id in busy:
            return None
        turns.append({"sid": session_id, "agent_id": agent_id, "text": text, "msg_id": msg_id})
        if session_id in held:
            held[session_id].append(on_done)
        elif on_done is not None:
            on_done(SimpleNamespace(final_text=f"done in {session_id}"))
        return "exec-" + session_id

    monkeypatch.setattr(owner_turn, "start_owner_turn_when_free", start)
    monkeypatch.setattr(handoff, "_spawn", handoff._deliver)
    monkeypatch.setattr(handoff, "_spawn_reply", handoff._reply_after_restart)
    path = world["db"].root.parent / "handoffs.json"
    monkeypatch.setattr(store, "_handoffs_path", lambda: path)
    monkeypatch.setattr(handoff, "_CHAINS", {})
    monkeypatch.setattr(handoff, "_loaded", False)
    return SimpleNamespace(module=handoff, turns=turns, busy=busy, held=held, path=path)


def _restart_worker(handoffs, monkeypatch):
    """A new worker process: memory is gone, the saved chains are loaded."""
    monkeypatch.setattr(handoffs.module, "_CHAINS", {})
    monkeypatch.setattr(handoffs.module, "_BOOT", "next-boot")
    handoffs.module.restore()


def test_handoff_wakes_the_target_and_brings_the_answer_back(agent, world, handoffs):
    enable(agent)
    db = world["db"]
    db.create_session("planner", agent, title="Planner")
    db.create_session("docs", "main-" + agent, title="Docs bot")
    sent = handoffs.module.send("planner", "DOCS BOT", "Check the links")
    assert (sent["target_id"], sent["hop"]) == ("docs", 1)
    to_docs, back = handoffs.turns
    assert to_docs["sid"] == "docs" and to_docs["agent_id"] == "main-" + agent
    assert to_docs["text"].startswith("📨 Message from “Planner” (planner):\n\nCheck the links")
    assert back["sid"] == "planner" and back["agent_id"] == agent
    assert back["text"].startswith("↩️ Reply from “Docs bot” (docs)") and "done in docs" in back["text"]
    # Both turns belong to the chain, one hop in.
    assert handoffs.module.chain_of(to_docs["msg_id"])["hop"] == 1
    assert handoffs.module.chain_of(back["msg_id"]) == handoffs.module.chain_of(to_docs["msg_id"])
    # By id works too.
    assert handoffs.module.send("planner", "docs", "Again")["target_id"] == "docs"


def test_handoff_loop_guard(agent, world, handoffs):
    enable(agent)
    db = world["db"]
    db.create_session("a", agent, title="A")
    db.create_session("b", agent, title="B")
    refused = handoffs.module.HandoffRefused
    with pytest.raises(refused, match="itself"):
        handoffs.module.send("a", "A", "hello me")
    with pytest.raises(refused, match="empty"):
        handoffs.module.send("a", "B", "  ")
    # Each handoff from a handoff or reply turn is one more hop, up to the limit.
    msg_id = None
    for hop in range(1, handoffs.module.MAX_HOPS + 1):
        sender = "a" if hop % 2 else "b"
        assert handoffs.module.send(sender, "B" if sender == "a" else "A", "pass", msg_id=msg_id)["hop"] == hop
        msg_id = handoffs.turns[-1]["msg_id"]
    with pytest.raises(refused, match="hops"):
        handoffs.module.send("a", "B", "once more", msg_id=msg_id)
    # A turn outside any chain starts a new one.
    assert handoffs.module.send("a", "B", "fresh", msg_id="typed-by-owner")["hop"] == 1


def test_handoff_only_between_owner_conversations(agent, world, handoffs):
    enable(agent)
    db = world["db"]
    db.create_session("a", agent, title="A")
    db.create_session("sub", agent, source="agent", title="Helper")
    db.create_session("imp", agent, source="import", title="Imported")
    db.create_session("x", agent, title="Twin")
    db.create_session("y", agent, title="twin")
    db.create_session("plain", "main-" + agent, title="Plain")
    refused = handoffs.module.HandoffRefused
    for target in ("sub", "imp"):
        with pytest.raises(refused, match="cannot take handoffs"):
            handoffs.module.send("a", target, "work")
    with pytest.raises(refused, match="No conversation is titled 'Helper'"):
        handoffs.module.send("a", "Helper", "work")
    with pytest.raises(refused, match="Several conversations"):
        handoffs.module.send("a", "TWIN", "work")
    with pytest.raises(refused, match="sub-agents"):
        handoffs.module.send("sub", "A", "work")
    with pytest.raises(refused, match="sub-agents"):
        handoffs.module.send("a", "Plain", "work", advance_head=False)
    # A conversation whose Agent is not always-on does not hand work over.
    with pytest.raises(refused, match="always-on"):
        handoffs.module.send("plain", "A", "work")
    assert handoffs.turns == []


def test_a_busy_target_hands_the_message_back(agent, world, handoffs):
    enable(agent)
    db = world["db"]
    db.create_session("a", agent, title="A")
    db.create_session("b", agent, title="B")
    handoffs.busy.add("b")
    handoffs.module.send("a", "B", "urgent thing")
    assert [(turn["sid"], turn["text"].split("\n")[0]) for turn in handoffs.turns] == [
        ("a", "↩️ “B” (b) stayed busy for ten minutes, so the message you sent it was not delivered:")]


def test_handoff_tool_reports_refusals(agent, world, handoffs, monkeypatch):
    from openprogram.programs.tools.interaction.handoff import _handoff_impl as tool
    enable(agent)
    world["db"].create_session("a", agent, title="A")
    world["db"].create_session("b", agent, title="B")
    monkeypatch.setattr("openprogram.runtime.execution.run_control.get_current_session_id", lambda: "a")
    assert tool("A", "me").startswith("[handoff refused]")
    assert tool("B", "you").startswith("Sent to “B” (b), hop 1 of")


def test_hop_count_survives_a_worker_restart(agent, world, handoffs, monkeypatch):
    enable(agent)
    db = world["db"]
    db.create_session("a", agent, title="A")
    db.create_session("b", agent, title="B")
    msg_id = None
    for hop in range(1, handoffs.module.MAX_HOPS):
        sender = "a" if hop % 2 else "b"
        handoffs.module.send(sender, "B" if sender == "a" else "A", "pass", msg_id=msg_id)
        msg_id = handoffs.turns[-1]["msg_id"]
    saved = handoffs.module.chain_of(msg_id)
    _restart_worker(handoffs, monkeypatch)
    assert handoffs.module.chain_of(msg_id) == saved and saved["origin"] == "a"
    assert handoffs.module.send("b", "A", "last", msg_id=msg_id)["hop"] == handoffs.module.MAX_HOPS
    with pytest.raises(handoffs.module.HandoffRefused, match="hops"):
        handoffs.module.send("a", "B", "once more", msg_id=handoffs.turns[-1]["msg_id"])


def test_a_turn_cut_off_by_a_restart_replies_once_when_its_continuation_ends(
        agent, world, handoffs, monkeypatch):
    enable(agent)
    db = world["db"]
    db.create_session("a", agent, title="A")
    db.create_session("b", agent, title="B")
    handoffs.held["b"] = []
    handoffs.module.send("a", "B", "Check the links")
    assert [turn["sid"] for turn in handoffs.turns] == ["b"]
    old_on_done = handoffs.held["b"][0]

    _restart_worker(handoffs, monkeypatch)
    # The continuation has a new message id and keeps the chain's hop.
    assert handoffs.module.send("b", "A", "Question", msg_id="resumed-turn", resumed=True)["hop"] == 2
    del handoffs.turns[1:]
    # An ordinary turn ending in b owes nothing.
    handoffs.module.resumed_turn_ended("a", "unrelated")
    assert len(handoffs.turns) == 1

    handoffs.module.resumed_turn_ended("b", "All 12 links work.")
    reply = handoffs.turns[-1]
    assert reply["sid"] == "a" and reply["text"].startswith("↩️ Reply from “B” (b)")
    assert "All 12 links work." in reply["text"]
    assert handoffs.module.chain_of(reply["msg_id"])["hop"] == 1
    # Never twice: not on another end, nor from the old worker's callback.
    handoffs.module.resumed_turn_ended("b", "again")
    old_on_done(SimpleNamespace(final_text="late"))
    _restart_worker(handoffs, monkeypatch)
    handoffs.module.resumed_turn_ended("b", "after another restart")
    assert len(handoffs.turns) == 2


def test_a_failed_continuation_still_answers_and_old_chains_expire(agent, world, handoffs, monkeypatch):
    import json
    import time
    enable(agent)
    db = world["db"]
    db.create_session("a", agent, title="A")
    db.create_session("b", agent, title="B")
    handoffs.held["b"] = []
    handoffs.module.send("a", "B", "Check the links")
    _restart_worker(handoffs, monkeypatch)
    handoffs.module.resumed_turn_ended("b", None)
    assert "could not run a turn" in handoffs.turns[-1]["text"]

    chains = json.loads(handoffs.path.read_text())
    for entry in chains.values():
        entry["at"] = time.time() - handoffs.module.CHAIN_TTL_S - 1
    handoffs.path.write_text(json.dumps(chains))
    _restart_worker(handoffs, monkeypatch)
    assert json.loads(handoffs.path.read_text()) == {}
