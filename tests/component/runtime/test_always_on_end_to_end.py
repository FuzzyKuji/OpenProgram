"""Always-on end to end: a real conversation joins, wakes, checks in through
the production turn path with a scripted model, reports, and the report
reaches a channel conversation."""
from __future__ import annotations

from types import SimpleNamespace
import uuid

import pytest

from tests.support.waiting import wait_until

_API = "always-on-e2e-api"


@pytest.fixture
def world(tmp_path, monkeypatch):
    import openprogram.state.paths as paths
    from openprogram.models.providers.catalog import api_registry
    from openprogram.models.providers.types import Model
    from openprogram.runtime import channel_link, interface_link
    from openprogram.runtime.conversation import turn_runtime as D
    from openprogram.runtime.permissions import authority
    from openprogram.state.store.session import session_store
    from tests.component.providers.scripted_provider import ScriptedProvider

    monkeypatch.setattr(paths, "get_state_dir", lambda: tmp_path / "state")
    authority._reset_owner_cache_for_tests()
    session_store.shared._default_store = None

    provider = ScriptedProvider()
    previous = api_registry._registry.get(_API)
    api_registry.register_api_provider(_API, provider)
    model = Model(id="scripted", name="scripted", api=_API, provider="scripted-e2e",
                  base_url="http://scripted.invalid")
    monkeypatch.setattr(D, "_resolve_model", lambda *a, **kw: model)

    # The server registers its interface link on import; import it before
    # the patch below so undoing the patch leaves that link in place.
    from openprogram.interfaces.server import server as _server  # noqa: F401

    frames: list[dict] = []

    class Link:
        def broadcast(self, frame):
            frames.append(frame)

        def __getattr__(self, _name):
            return lambda *a, **kw: None
    monkeypatch.setattr(interface_link, "_link", Link())

    sent: list[tuple] = []

    class Channels:
        def send_message(self, channel, account_id, peer_id, text):
            sent.append((channel, account_id, peer_id, text))
            return SimpleNamespace(ok=True, error_kind=None, error_detail=None)

        def peer_bindings(self, _agent_id):
            return []

        def account_ids(self, _channel):
            return []
    monkeypatch.setattr(channel_link, "require", lambda: Channels())
    monkeypatch.setattr(channel_link, "peer_bindings", lambda agent_id: [], raising=False)

    from openprogram.runtime.agent_registry import manager
    agent_id = "e2e" + uuid.uuid4().hex[:8]
    manager.create(agent_id, name="Scout")
    try:
        yield SimpleNamespace(agent_id=agent_id, provider=provider, frames=frames, sent=sent,
                              manager=manager)
    finally:
        manager.delete(agent_id)
        if previous is None:
            api_registry._registry.pop(_API, None)
        else:
            api_registry.register_api_provider(_API, previous)


def _idle(session_id):
    from openprogram.interfaces.server import server as _s
    from openprogram.runtime.conversation.run_control import is_turn_running
    return not is_turn_running(session_id) and not _s._is_run_active(session_id)


def test_check_in_reports_and_delivers_to_a_channel(world):
    from openprogram.runtime.context.session_db import default_db
    from openprogram.runtime.conversation import always_on
    from openprogram.runtime.conversation.always_on import store
    from tests.component.providers.scripted_provider import ScriptedText, ScriptedToolCall

    target = {"channel": "telegram", "account_id": "bot", "peer_id": "42", "label": "Me"}
    world.manager.update(world.agent_id, {"always_on": {
        "enabled": True, "research": True, "channels": [target]}})
    sid = "ao-" + uuid.uuid4().hex[:8]
    default_db().create_session(sid, world.agent_id)
    joined = always_on.join(sid)
    assert joined["next_wake_at"] > joined["joined_at"]
    assert always_on.agent_for_session(sid) == world.agent_id

    world.provider.add_response(ScriptedToolCall(
        "always_on_report", {"title": "CI is red", "body": "main fails since 10:00",
                             "links": ["https://ci.invalid/1"]}, "call-1"))
    world.provider.add_response(ScriptedText("Reported the CI failure."))

    result = always_on.wake(sid, reason="manual")
    assert result["outcome"] == "check_in"
    wait_until(lambda: world.provider.call_count >= 2 and _idle(sid), timeout=20)

    # The check-in turn ran with the read-only tool list.
    tools = {tool.name for tool in world.provider.calls[0].context.tools or []}
    assert "always_on_report" in tools and "bash" not in tools and "write" not in tools
    assert "Always-on check-in" in str(world.provider.calls[0].context.messages)

    reports = store.load_reports(sid, 10)
    assert [r["title"] for r in reports] == ["CI is red"]
    wait_until(lambda: (store.load_reports(sid, 10)[0].get("deliveries") or [{}])[0].get("status") == "sent",
               timeout=10)
    assert world.sent and world.sent[0][:3] == ("telegram", "bot", "42")
    assert "Scout · CI is red" in world.sent[0][3]
    kinds = [frame["type"] for frame in world.frames]
    assert "always_on_report" in kinds
    # The report itself gives the conversation the sidebar's unread dot,
    # before its turn ends.
    after = world.frames[kinds.index("always_on_report") + 1]
    assert after == {"type": "session_updated", "data": {"id": sid, "unread": True}}
    assert default_db().get_session(sid)["unread"]
    status = always_on.status(sid)
    assert status["last_wake"]["outcome"] == "check_in" and status["reports"]
    # The turn's end keeps it.
    wait_until(lambda: default_db().get_session(sid).get("status") == "done", timeout=10)
    assert default_db().get_session(sid)["unread"]


def test_a_check_in_that_finds_nothing_leaves_no_unread_dot(world):
    from openprogram.runtime.context.session_db import default_db
    from openprogram.runtime.conversation import always_on
    from openprogram.runtime.conversation.owner_turn import start_owner_turn
    from tests.component.providers.scripted_provider import ScriptedText

    world.manager.update(world.agent_id, {"always_on": {"enabled": True, "research": True}})
    sid = "ao-" + uuid.uuid4().hex[:8]
    default_db().create_session(sid, world.agent_id)
    always_on.join(sid)
    world.provider.add_response(ScriptedText("Nothing new since the last check-in."))

    assert always_on.wake(sid, reason="schedule")["outcome"] == "check_in"
    wait_until(lambda: world.provider.call_count >= 1 and _idle(sid), timeout=20)
    wait_until(lambda: default_db().get_session(sid).get("status") == "done", timeout=10)
    assert not default_db().get_session(sid).get("unread")
    assert not any(frame["type"] == "session_updated" and frame["data"].get("unread")
                   for frame in world.frames)
    # The Activity panel still has the wake.
    assert always_on.status(sid)["last_wake"]["outcome"] == "check_in"

    # An ordinary turn in the same conversation still marks it unread.
    world.provider.add_response(ScriptedText("Hi."))
    start_owner_turn(sid, world.agent_id, "hello")
    wait_until(lambda: world.provider.call_count >= 2 and _idle(sid), timeout=20)
    wait_until(lambda: default_db().get_session(sid).get("unread"), timeout=10)


def test_standing_goal_starts_once_as_a_goal(world):
    from openprogram.runtime.context.session_db import default_db
    from openprogram.runtime.conversation import always_on
    from openprogram.runtime.conversation.always_on import store
    import openprogram.programs.tools.planning.goal as goals
    from tests.component.providers.scripted_provider import ScriptedText

    world.manager.update(world.agent_id, {"always_on": {"enabled": True, "goal": "Watch the docs"}})
    sid = "ao-" + uuid.uuid4().hex[:8]
    default_db().create_session(sid, world.agent_id)
    always_on.join(sid)
    for _ in range(8):
        world.provider.add_response(ScriptedText("Working on it."))

    assert always_on.wake(sid, reason="manual")["outcome"] == "goal_started"
    goal = goals.load_goal(sid)
    assert goal and goal["text"] == "Watch the docs" and goal["origin"] == "always_on"
    assert store.load_state(sid)["applied_goal"]["text"] == "Watch the docs"
    wait_until(lambda: world.provider.call_count >= 1, timeout=20)
    wait_until(lambda: _idle(sid), timeout=30)
    # The goal is not started twice.
    assert always_on.wake(sid, reason="manual")["outcome"] in {"goal_in_progress", "goal_paused", "check_in"}
    assert store.load_state(sid)["applied_goal"]["text"] == "Watch the docs"


class _RoutedProvider:
    """Answers by what the conversation was last told, so turns of two
    conversations may interleave."""

    def __init__(self, route):
        self.route = route
        self.seen: list[str] = []
        self.tool_results: list[str] = []

    def stream(self, model, context, options=None):
        return self.stream_simple(model, context, options)

    async def stream_simple(self, model, context, options=None):
        from tests.component.providers.scripted_provider import ScriptedProvider, ScriptedText
        last = context.messages[-1]
        users = [m for m in context.messages if getattr(m, "role", "") == "user"]
        told = str(getattr(users[-1], "content", "")) if users else ""
        self.seen.append(told)
        scripted = ScriptedProvider()
        if getattr(last, "role", "") == "toolResult":
            self.tool_results.append(last.content[0].text)
            scripted.add_response(ScriptedText(f"tool said: {last.content[0].text}"))
        else:
            scripted.add_response(*self.route(told))
        async for event in scripted.stream_simple(model, context, options):
            yield event


def test_handoff_runs_in_the_other_conversation_and_the_answer_comes_back(world, monkeypatch):
    from openprogram.models.providers.catalog import api_registry
    from openprogram.runtime.permissions import classifier

    async def allow(*_a, **_kw):
        # Auto mode reviews a handoff like any action; the reviewer approves here.
        return classifier.ReviewResult(False, "", "")
    monkeypatch.setattr(classifier, "auto_classify_tool", allow)
    from openprogram.runtime.context.session_db import default_db
    from openprogram.runtime.conversation.owner_turn import start_owner_turn
    from tests.component.providers.scripted_provider import ScriptedText, ScriptedToolCall

    planner, docs = "ao-" + uuid.uuid4().hex[:8], "ao-" + uuid.uuid4().hex[:8]

    def route(told):
        if "📨 Message from" in told:
            return (ScriptedText("All 12 links work."),)
        if "↩️ Reply from" in told:
            return (ScriptedText("Noted."),)
        if "LOOP" in told:
            return (ScriptedToolCall("handoff", {"to": planner, "message": "me again"}, "self-1"),)
        return (ScriptedToolCall("handoff", {"to": "docs bot", "message": "Check the links"}, "h-1"),)
    provider = _RoutedProvider(route)
    api_registry.register_api_provider(_API, provider)
    world.manager.update(world.agent_id, {"always_on": {"enabled": True}})
    default_db().create_session(planner, world.agent_id, title="Planner")
    default_db().create_session(docs, "main", title="Docs bot")

    start_owner_turn(planner, world.agent_id, "PING: ask the docs bot")
    wait_until(lambda: any("↩️ Reply from" in told for told in provider.seen), timeout=30)
    wait_until(lambda: _idle(planner) and _idle(docs), timeout=30)

    assert provider.tool_results[0].startswith(f"Sent to “Docs bot” ({docs}), hop 1 of 4.")
    handed = next(told for told in provider.seen if "📨 Message from" in told)
    assert f"“Planner” ({planner})" in handed and "Check the links" in handed
    reply = next(told for told in provider.seen if "↩️ Reply from" in told)
    assert f"“Docs bot” ({docs})" in reply and "All 12 links work." in reply

    # A conversation cannot message itself.
    provider.seen.clear()
    provider.tool_results.clear()
    start_owner_turn(planner, world.agent_id, "LOOP")
    wait_until(lambda: _idle(planner) and provider.tool_results, timeout=30)
    assert provider.tool_results == ["[handoff refused] A conversation cannot hand work to itself."]
    assert not any("📨 Message from" in told for told in provider.seen)
