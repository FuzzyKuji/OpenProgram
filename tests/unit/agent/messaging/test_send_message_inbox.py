"""send_message busy-target inbox — queue, drain, limits.

Covers (design: agent-collaboration.md §5.4):
  * busy target → message queued (not delivered, not dropped)
  * drain at turn end → each entry delivered through run_agent_turn_async
    with the sender receipt header + caller routing
  * queued delivery inherits the spawn depth recorded at enqueue (+1)
  * per-target cap (50): oldest dropped + notice in the sender session
  * duplicate suppression: identical message from the same sender within
    the 60s window is rejected
"""
from __future__ import annotations

import json
import threading

import pytest

from openprogram.runtime.conversation import inbox
from openprogram.programs.tools.agents.send_message.send_message.send_message import (
    _send_message_impl,
)


@pytest.fixture
def two_sessions(tmp_path, monkeypatch):
    """Sender session p1 (bound on the ContextVars) + target session t1."""
    from openprogram.state.store.session.session_store import SessionStore
    from openprogram.runtime.context import session_db as sdb_mod

    s = SessionStore(tmp_path / "sessions-git")
    monkeypatch.setattr(sdb_mod, "default_store", lambda: s)
    monkeypatch.setattr("openprogram.state.store.session.session_store.default_store", lambda: s)
    monkeypatch.setattr("openprogram.state.store.default_store", lambda: s)

    s.create_session("p1", "main", title="sender")
    s.append_message("p1", {"id": "u1", "role": "user", "content": "hi",
                            "timestamp": 0, "predecessor": None})
    s.append_message("p1", {"id": "a1", "role": "assistant", "content": "ok",
                            "timestamp": 0, "predecessor": "u1"})
    s.commit_turn("p1", "init")

    s.create_session("t1", "main", title="target")
    s.append_message("t1", {"id": "u2", "role": "user", "content": "yo",
                            "timestamp": 0, "predecessor": None})
    s.append_message("t1", {"id": "b1", "role": "assistant", "content": "sup",
                            "timestamp": 0, "predecessor": "u2"})
    s.commit_turn("t1", "init")

    from openprogram.runtime.execution.run_control import binding as run_control_binding
    from openprogram.state import store as store_mod
    sid_tok = run_control_binding._current_session_id.set("p1")
    turn_tok = store_mod._current_turn_id.set("a1")
    # Every message is a tracked Job, so a queued one is admitted by the job
    # runner. Build it on the empty store and stop it with the test.
    monkeypatch.setattr("openprogram.runtime.jobs.runner.shared._broadcast", lambda *a, **k: None)
    from openprogram.runtime.jobs import runner as runner_mod
    runner = runner_mod.get_runner()
    yield s
    runner_mod.shutdown_runner()
    for thread in (runner._dispatcher_thread, runner._reconciler_thread, runner._budget_thread):
        thread.join()
    run_control_binding._current_session_id.reset(sid_tok)
    store_mod._current_turn_id.reset(turn_tok)


@pytest.fixture
def busy_target(two_sessions):
    """Mark t1 as running a turn (registered cancel token = busy)."""
    from openprogram.runtime.conversation import run_control
    ev = threading.Event()
    run_control.register_cancel_event("t1", ev)
    yield ev
    run_control.unregister_cancel_event("t1", ev)


def _capture_async(monkeypatch):
    """Patch run_agent_turn_async at its definition site (inbox and
    send_message both import it lazily from there) and capture kwargs."""
    calls: list[dict] = []

    def fake_async(**kw):
        calls.append(kw)
        return "task_fake"

    monkeypatch.setattr(
        "openprogram.runtime.conversation.sub_agent_run.run_agent_turn_async", fake_async)
    return calls


def test_busy_send_enqueues(two_sessions, busy_target, monkeypatch):
    calls = _capture_async(monkeypatch)
    out = _send_message_impl("hello t1", to="t1:b1")
    assert "[queued]" in out
    assert "busy" in out
    assert calls == []                      # nothing delivered yet
    assert inbox.pending_count("t1") == 1


def test_drain_delivers_then_removes(two_sessions, busy_target, monkeypatch):
    calls = _capture_async(monkeypatch)
    _send_message_impl("hello t1", to="t1:b1")
    assert inbox.pending_count("t1") == 1

    # Release the busy state before draining (turn ended).
    from openprogram.runtime.conversation import run_control
    run_control.unregister_cancel_event("t1", busy_target)

    delivered = inbox.drain("t1")
    assert delivered == 1
    assert inbox.pending_count("t1") == 0
    kw = calls[0]
    assert kw["session_id"] == "t1"
    assert kw["caller_session_id"] == "p1"   # reply routes back to sender
    assert kw["caller_msg_id"] == "a1"
    assert kw["prompt"].startswith("[message from p1:a1 (sender)]")
    assert "hello t1" in kw["prompt"]
    # Delivered onto the target's current head.
    head = (two_sessions.get_session("t1") or {}).get("head_id")
    assert kw["branch_from"] == head


def test_drain_leaves_entry_on_failed_delivery(two_sessions, busy_target, monkeypatch):
    """Deliver-then-delete: a failed submission keeps the entry queued."""
    _send_message_impl("keep me", to="t1:b1")

    def boom(**kw):
        raise RuntimeError("runner down")
    monkeypatch.setattr(
        "openprogram.runtime.conversation.sub_agent_run.run_agent_turn_async", boom)
    assert inbox.drain("t1") == 0
    assert inbox.pending_count("t1") == 1


def test_queued_delivery_inherits_both_chain_counts(two_sessions, busy_target, monkeypatch):
    """A queued hop spends a message like a direct one, and creates no
    agent, so the generation count crosses the queue unchanged."""
    from openprogram.programs.tools.agents.send_message.send_message.depth import (
        set_chain_generations, set_chain_messages,
    )
    calls = _capture_async(monkeypatch)
    tokens = [set_chain_messages(3), set_chain_generations(1)]
    try:
        _send_message_impl("deep hello", to="t1:b1")
    finally:
        for tok in tokens:
            tok.var.reset(tok)
    assert inbox.drain("t1") == 0  # the target's turn is still running
    from openprogram.runtime.conversation import run_control
    run_control.unregister_cancel_event("t1", busy_target)
    delivered = inbox.drain("t1")
    assert delivered == 1
    assert calls[0]["chain_messages"] == 4      # recorded 3 messages, +1
    assert calls[0]["chain_generations"] == 1
    assert calls[0]["caller_chain_generations"] == 1


def test_drain_reads_legacy_spawn_depth_key(two_sessions, monkeypatch):
    """An inbox.json written before the rename stores the count under
    ``spawn_depth``; drain still honours it."""
    calls = _capture_async(monkeypatch)
    inbox.enqueue(
        "t1", message="old entry", sender_session_id="p1",
        sender_msg_id="a1", sender_agent_id="main", agent_id="main",
        chain_messages=0, target_head_id="b1",
    )
    path = inbox._inbox_path("t1")
    blob = json.loads(path.read_text(encoding="utf-8"))
    entry = blob["entries"][0]
    entry.pop("chain_messages")
    entry["spawn_depth"] = 5
    path.write_text(json.dumps(blob), encoding="utf-8")

    assert inbox.drain("t1") == 1
    assert calls[0]["chain_messages"] == 6      # legacy 5, child +1


def test_cap_drops_oldest_and_notifies_sender(two_sessions):
    for i in range(inbox.MAX_PENDING):
        assert inbox.enqueue(
            "t1", message=f"msg {i}", sender_session_id="p1",
            sender_msg_id="a1", sender_agent_id="main", agent_id="main",
            chain_messages=0, target_head_id="b1",
        ) == "queued"
    assert inbox.pending_count("t1") == inbox.MAX_PENDING

    assert inbox.enqueue(
        "t1", message="one too many", sender_session_id="p1",
        sender_msg_id="a1", sender_agent_id="main", agent_id="main",
        chain_messages=0, target_head_id="b1",
    ) == "queued"
    assert inbox.pending_count("t1") == inbox.MAX_PENDING
    path = inbox._inbox_path("t1")
    entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
    messages = [e["message"] for e in entries]
    assert "msg 0" not in messages           # oldest dropped
    assert "one too many" in messages
    # The dropped message's sender got a system notice.
    notes = [m for m in (two_sessions.get_messages("p1") or [])
             if "inbox is full" in str(m.get("content") or "")]
    assert notes
    assert "msg 0" in notes[0]["content"]


def test_duplicate_within_window_rejected(two_sessions, busy_target, monkeypatch):
    _capture_async(monkeypatch)
    out1 = _send_message_impl("same words", to="t1:b1")
    out2 = _send_message_impl("same words", to="t1:b1")
    assert "[queued]" in out1
    assert "duplicate message ignored" in out2
    assert inbox.pending_count("t1") == 1


def test_duplicate_outside_window_accepted(two_sessions):
    assert inbox.enqueue(
        "t1", message="same words", sender_session_id="p1",
        sender_msg_id="a1", sender_agent_id="main", agent_id="main",
        chain_messages=0, target_head_id="b1",
    ) == "queued"
    # Age the queued copy past the dedup window.
    path = inbox._inbox_path("t1")
    blob = json.loads(path.read_text(encoding="utf-8"))
    blob["entries"][0]["enqueued_at"] -= inbox.DEDUP_WINDOW_SECS + 1
    path.write_text(json.dumps(blob), encoding="utf-8")
    assert inbox.enqueue(
        "t1", message="same words", sender_session_id="p1",
        sender_msg_id="a1", sender_agent_id="main", agent_id="main",
        chain_messages=0, target_head_id="b1",
    ) == "queued"
    assert inbox.pending_count("t1") == 2


def test_sweep_delivers_once_the_target_goes_quiet(two_sessions, busy_target, monkeypatch):
    """A turn that ends without draining (cancelled, crashed) does not
    strand the message: the worker sweep delivers it once the target
    is free."""
    calls = _capture_async(monkeypatch)
    _send_message_impl("later", to="t1:b1")
    inbox.sweep()
    assert calls == [] and inbox.pending_count("t1") == 1
    from openprogram.runtime.conversation import run_control
    run_control.unregister_cancel_event("t1", busy_target)
    inbox.sweep()
    assert len(calls) == 1 and inbox.pending_count("t1") == 0


def test_same_session_send_waits_for_a_busy_branch(two_sessions, monkeypatch):
    """Inside the sender's own session only the addressed branch counts:
    a sub-agent still extending it holds the message; once it ends the
    message continues that branch's new tip, not the session head."""
    from openprogram.runtime.jobs.store import save_job
    from openprogram.runtime.jobs.types import Job, JobStatus
    s = two_sessions
    s.append_message("p1", {"id": "x1", "role": "user", "content": "side",
                            "timestamp": 0, "predecessor": "u1"})
    s.append_message("p1", {"id": "x2", "role": "assistant", "content": "side reply",
                            "timestamp": 0, "predecessor": "x1"})
    s.set_head("p1", "a1")
    s.commit_turn("p1", "side branch")
    worker = Job(id="w1", parent_session_id="p1", prompt="work", agent_id="main",
                 status=JobStatus.RUNNING, target_branch_head_id="x2")
    save_job("p1", worker)
    calls = _capture_async(monkeypatch)
    out = _send_message_impl("ping", to="p1:x2")
    assert out.startswith("[queued]")
    assert inbox.drain("p1") == 0
    s.append_message("p1", {"id": "x3", "role": "user", "content": "more",
                            "timestamp": 0, "predecessor": "x2"})
    s.append_message("p1", {"id": "x4", "role": "assistant", "content": "done",
                            "timestamp": 0, "predecessor": "x3"})
    s.set_head("p1", "a1")
    s.commit_turn("p1", "worker done")
    worker.status, worker.head_id = JobStatus.COMPLETED, "x4"
    save_job("p1", worker)
    assert inbox.drain("p1") == 1
    assert calls[0]["branch_from"] == "x4"


def test_notify_when_idle_answers_at_once_for_an_idle_target(two_sessions):
    out = _send_message_impl("", to="t1:b1", notify_when_idle=True)
    assert out.startswith("[idle] t1:b1") and "sup" in out


def test_an_idle_watch_drops_the_notice_of_the_reply_it_hands_back(two_sessions, monkeypatch):
    from openprogram.runtime.jobs import notices
    read = []
    monkeypatch.setattr(notices, "consume_reply", lambda *a: read.append(a))
    _send_message_impl("", to="t1:b1", notify_when_idle=True)
    assert read and read[0][1:] == ("t1", "b1")


def test_notify_when_idle_sends_one_notice_when_the_target_goes_quiet(
        two_sessions, busy_target, monkeypatch):
    from types import SimpleNamespace
    from openprogram.runtime.jobs import notices
    monkeypatch.setattr(notices, "_due", set())
    monkeypatch.setattr(notices, "_seeded", True)
    calls = _capture_async(monkeypatch)
    sent: list = []
    runner = SimpleNamespace(_dispatch_followup=lambda *jobs: sent.append(jobs))
    monkeypatch.setattr("openprogram.runtime.jobs.get_runner", lambda: runner)

    out = _send_message_impl("", to="t1:b1", notify_when_idle=True)
    assert out.startswith("[watching]")
    assert calls == []  # nothing was delivered to the target
    notices.sweep()
    assert sent == []
    from openprogram.runtime.conversation import run_control
    run_control.unregister_cancel_event("t1", busy_target)
    notices.sweep()
    notices.sweep()
    (jobs,) = sent
    (job,) = jobs
    assert job.source == "idle_watch" and job.caller_session_id == "p1"
    text = notices.notice_text(list(jobs))
    assert "t1:b1" in text and "is idle now" in text and "sup" in text



def test_a_message_from_another_conversation_is_marked_and_still_returns(two_sessions, monkeypatch):
    """The receipt says the message is another agent's input, not the
    receiver's user, and its reply still comes back to the sender."""
    calls = _capture_async(monkeypatch)
    out = _send_message_impl("hello t1", to="t1:b1")
    assert "comes back to you automatically" in out
    kw = calls[-1]
    assert kw["caller_session_id"] == "p1"
    assert "not from your user" in kw["prompt"]
    assert "returned to the sender automatically" in kw["prompt"]


def test_a_queued_message_from_another_conversation_is_marked(two_sessions, busy_target, monkeypatch):
    calls = _capture_async(monkeypatch)
    _send_message_impl("hello t1", to="t1:b1")
    from openprogram.runtime.conversation import run_control
    run_control.unregister_cancel_event("t1", busy_target)
    inbox.drain("t1")
    assert "not from your user" in calls[0]["prompt"]


def test_a_queued_cross_session_message_continues_the_branch_it_was_sent_to(
    two_sessions, busy_target, monkeypatch,
):
    """The target may select another branch while the message waits; the
    message still continues the branch it addressed, from that branch's tip."""
    s = two_sessions
    calls = _capture_async(monkeypatch)
    _send_message_impl("hello t1", to="t1:b1")
    s.append_message("t1", {"id": "b9", "role": "assistant", "content": "another version",
                            "timestamp": 0, "predecessor": "u2"})
    s.set_head("t1", "b9")
    s.commit_turn("t1", "another branch selected")
    from openprogram.runtime.conversation import run_control
    run_control.unregister_cancel_event("t1", busy_target)
    assert inbox.drain("t1") == 1
    assert calls[0]["branch_from"] == "b1"
