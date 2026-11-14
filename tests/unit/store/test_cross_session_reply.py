"""C4 — cross-session send_message reply routing.

When agent A (session A) messages a branch in session B, B's reply must be
delivered back to A's session, not B's. This is carried by the Job's
``caller_session_id`` and used by ``_dispatch_followup``.

The follow-up turn is admitted through the canonical Agent adapter, which
freezes the request against the session store and records it as a durable
execution. These tests run that admission for real against a session store
and an execution store in the test's own folders, and read back the input
that was admitted. Only the activation that would call a model is replaced:
it records what was admitted instead of running the turn.

See docs/reference/design/runtime/collaboration/agent-collaboration.html (C4).
"""
from __future__ import annotations

import threading

import pytest

from openprogram.runtime.jobs.types import Job, JobStatus


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    """A real session store in this test's folder, with sessions A and B."""
    from openprogram.runtime.context.session_db import SessionDB

    db = SessionDB(tmp_path / "sessions-git")
    monkeypatch.setattr("openprogram.runtime.context.session_db.default_db", lambda: db)
    monkeypatch.setattr("openprogram.state.store.session.session_store.default_store", lambda: db)
    monkeypatch.setattr("openprogram.state.store.default_store", lambda: db)
    db.create_session("A", "main", title="sender")
    db.create_session("B", "main", title="target")
    return db


def _make_job(**kw):
    base = dict(
        id="t_x",
        parent_session_id="B",   # the job ran in session B (target)
        prompt="do thing",
        agent_id="main",
        status=JobStatus.COMPLETED,
        head_id="head_b",
        result_text="B's answer",
    )
    base.update(kw)
    return Job(**base)


def _admitted_followup(monkeypatch, job) -> dict:
    """Fire ``_dispatch_followup`` and return the chat request the canonical
    adapter admitted for the notice turn, read back from the execution store."""
    from openprogram.runtime.conversation.production_driver import CanonicalAgentAdapter
    from openprogram.runtime.jobs.runner import JobRunner

    admitted: dict = {}
    done = threading.Event()

    async def record_admission(self, admission):
        stored = self.store.get_agent_turn_input(admission.execution_id)
        admitted["execution_session"] = admission.session_id
        admitted["request"] = dict(stored["request"])
        done.set()
        return None

    monkeypatch.setattr(CanonicalAgentAdapter, "activate", record_admission)
    monkeypatch.setattr("openprogram.runtime.jobs.runner.shared._broadcast", lambda *a, **k: None)
    runner = JobRunner(max_workers=1)
    try:
        runner._dispatch_followup(job)
        assert done.wait(timeout=30), "the notice turn was never admitted"
    finally:
        runner.shutdown(wait=False)
    return admitted


def test_followup_delivers_to_caller_session_when_cross(sessions, monkeypatch):
    """Cross-session delivery to an existing branch: the notice turn runs in
    caller_session_id (A), not B, and carries B's reply inline."""
    seen = _admitted_followup(monkeypatch, _make_job(caller_session_id="A"))
    assert seen["execution_session"] == "A"    # delivered to the sender
    assert seen["request"]["session_id"] == "A"
    assert seen["request"]["source"] == "job_followup"
    text = seen["request"]["user_text"]
    assert "B's answer" in text                # reply text carried inline
    assert "Reply from branch B:head_b" in text


def test_followup_same_session_spawn_uses_attach(sessions, monkeypatch):
    """Same-session SPAWN (attach pointer written): delivered to
    parent_session_id, and the notice points at the attach expansion
    rather than repeating the reply."""
    job = _make_job(caller_session_id=None, caller_msg_id="cm1", attach_pointer_id="ap1", wait=False)
    seen = _admitted_followup(monkeypatch, job)
    assert seen["execution_session"] == "B"    # same session as it ran in
    text = seen["request"]["user_text"]
    assert "attached above" in text            # same-session attach wording
    assert "B's answer" not in text            # context carries it, not the notice


def test_followup_cross_session_spawn_uses_source_attach(sessions, monkeypatch):
    """A cross-session spawn writes its pointer in the caller session.

    The target commit is resolved through the pointer, so carrying the same
    result inline would duplicate the child transcript in the next request.
    """
    job = _make_job(caller_session_id="A", caller_msg_id="cm1", attach_pointer_id="ap1", wait=False)
    seen = _admitted_followup(monkeypatch, job)
    assert seen["execution_session"] == "A"
    text = seen["request"]["user_text"]
    assert "attached above" in text
    assert "B's answer" not in text


def test_followup_same_session_delivery_carries_reply_inline(sessions, monkeypatch):
    """Same-session delivery to an EXISTING branch (agent(to=…) /
    send_message) writes no attach pointer, so the reply must travel
    inline — otherwise the initiator is told the transcript is attached
    above and nothing is."""
    job = _make_job(caller_session_id="B", caller_msg_id="cm1")  # ran where it was sent
    seen = _admitted_followup(monkeypatch, job)
    assert seen["execution_session"] == "B"
    text = seen["request"]["user_text"]
    assert "B's answer" in text                # the result actually arrives
    assert "Reply from branch B:head_b" in text
    assert "attached above" not in text
