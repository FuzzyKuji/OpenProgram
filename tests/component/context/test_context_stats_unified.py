"""One context number, two readers.

The composer ring (WS ``context_stats``) and the ``/context`` panel
(``GET /api/sessions/{id}/context``) both take their headline total from
``openprogram.runtime.context.session_stats``, so they can never disagree.

Covered here:
- ``measured`` after a real request, ``estimated`` once the graph moves;
- the calibration ratio a measured reading leaves behind;
- ``/context`` returning the same ``total_used`` the ring broadcast;
- the four graph-change triggers each broadcasting a fresh estimate.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openprogram.runtime.context import session_stats as cs
from openprogram.interfaces.server import server as srv


class _FakeDB:
    """Two-message branch carrying recorded tools + system prompt."""

    def get_branch(self, session_id, head_id=None):
        return [
            {"role": "user", "content": "hello " * 200, "extra": None},
            {
                "role": "llm",
                "content": "hi " * 200,
                "extra": json.dumps({
                    "tools_available": ["bash", "read"],
                    "system_prompt": "You are a helpful agent. " * 20,
                }),
            },
        ]

    def get_session(self, session_id):
        return {"model": ""}


@pytest.fixture
def fake_db(monkeypatch):
    import openprogram.runtime.context.session_db as _sdb
    monkeypatch.setattr(_sdb, "default_db", lambda: _FakeDB())
    return _FakeDB()


@pytest.fixture
def session(monkeypatch, fake_db):
    """A registered in-memory conversation plus a broadcast recorder."""
    sent: list[dict] = []
    monkeypatch.setattr(
        srv, "_broadcast_chat_response",
        lambda sid, mid, resp: sent.append(resp),
    )
    conv = {"provider_name": "anthropic", "head_id": None}
    srv._sessions["ctx-test"] = conv
    yield conv, sent
    srv._sessions.pop("ctx-test", None)


# --- basis selection -------------------------------------------------

def test_no_measurement_yields_estimated(fake_db):
    stats = cs.build_stats("s1")
    assert stats["basis"] == "estimated"
    assert stats["total_used"] == stats["estimated"] > 0
    assert "calibration" not in stats


def test_measurement_yields_measured_plus_calibration(fake_db):
    stats = cs.build_stats("s1", measured_total=12345, window=200_000)
    assert stats["basis"] == "measured"
    assert stats["total_used"] == 12345
    assert stats["window"] == 200_000
    # The estimate is still computed so the drift is reportable.
    assert stats["estimated"] > 0
    assert stats["calibration"] == pytest.approx(12345 / stats["estimated"], rel=1e-3)


def test_calibration_pairs_provider_usage_with_dispatched_request(fake_db):
    measured = cs.build_stats(
        "s1", measured_total=120_000, request_input_estimate=60_000,
    )
    assert measured["calibration"] == 2.0
    assert measured["calibration_source"] == "request"
    after_compaction = cs.build_stats("s1", estimated_total=30_000, calibration=2.0)
    assert after_compaction["basis"] == "estimated"
    assert after_compaction["total_used"] == 60_000


def test_refresh_reuses_only_same_model_request_calibration(monkeypatch, session):
    conv, sent = session
    conv["runtime"] = type("Runtime", (), {"model": "m1"})()
    conv["_last_context_stats"] = {
        "basis": "measured", "total_used": 120_000,
        "calibration": 2.0, "calibration_source": "request",
        "context_usage_version": 2,
        "provider": "anthropic", "model": "m1", "window": 200_000,
    }
    srv.refresh_context_stats("ctx-test")
    assert sent[-1]["total_used"] == 2 * sent[-1]["estimated"]
    assert srv.session_context_stats("ctx-test")["total_used"] == sent[-1]["total_used"]
    conv["model_override"] = "m2"
    srv.refresh_context_stats("ctx-test")
    assert sent[-1]["total_used"] == sent[-1]["estimated"]


def test_websocket_usage_carries_paired_request_estimate(monkeypatch, session):
    from openprogram.interfaces.server.ws_actions.chat import _record_context_usage
    conv, sent = session
    conv["runtime"] = type("Runtime", (), {"model": "m1"})()
    monkeypatch.setattr(srv, "_save_session", lambda _sid: None)
    _record_context_usage("ctx-test", "msg", conv, {
        "input_tokens": 120_000, "output_tokens": 10,
        "request_input_estimate": 60_000,
    })
    assert sent[-1]["basis"] == "measured"
    assert sent[-1]["total_used"] == 120_000
    assert sent[-1]["calibration"] == 2.0
    assert sent[-1]["calibration_source"] == "request"


def test_explicit_window_overrides_the_registry_lookup(fake_db):
    assert cs.build_stats("s1", window=1_000_000)["window"] == 1_000_000


# --- ring and panel agree --------------------------------------------

def test_panel_total_matches_the_ring_total(monkeypatch, session):
    conv, _sent = session
    srv.refresh_context_stats("ctx-test")
    ring_total = conv["_last_context_stats"]["total_used"]

    app = FastAPI()
    from openprogram.interfaces.server.routes.files import tree as _tree
    _tree.register(app)
    panel = TestClient(app).get("/api/sessions/ctx-test/context").json()

    assert panel["total_used"] == ring_total
    assert panel["window"] == conv["_last_context_stats"]["window"]
    assert panel["basis"] == "estimated"


def test_panel_reuses_the_measurement_while_the_graph_holds(session):
    conv, _sent = session
    conv["_last_context_stats"] = {
        "context_usage_version": 2,
        "window": 200_000, "total_used": 77_777,
        "basis": "measured", "estimated": 60_000, "calibration": 1.3,
    }
    stats = srv.session_context_stats("ctx-test")
    assert stats["basis"] == "measured"
    assert stats["total_used"] == 77_777


def test_panel_drops_stale_breakdown_after_refresh_without_head_move(session):
    """Compact does not move HEAD. Refresh must still replace the
    pre-compact stored categories so /context does not keep 125k
    Messages next to a 40k rendered report."""
    conv, _sent = session
    conv["_last_context_stats"] = {
        "window": 200_000, "total_used": 137_000,
        "basis": "measured", "estimated": 60_000, "_context_rev": 0,
    }
    conv["_last_context_breakdown"] = {
        "messages": 125_400, "input_used": 137_000, "head_id": None,
        "system_prompt": 0, "tools_schema": 0, "tools_deferred_catalog": 0,
        "mcp_tools": 0, "mcp_tools_deferred": 0, "memory": 0, "skills": 0,
        "unclassified": 0, "window": 200_000, "_context_rev": 0,
    }
    srv.refresh_context_stats("ctx-test")

    app = FastAPI()
    from openprogram.interfaces.server.routes.files import tree as _tree
    _tree.register(app)
    panel = TestClient(app).get("/api/sessions/ctx-test/context").json()

    assert panel["basis"] == "estimated"
    assert panel["total_used"] != 137_000
    assert panel.get("messages", 0) != 125_400


def test_panel_re_estimates_for_a_different_branch(session):
    """A measurement belongs to the branch it was taken on, not to another."""
    conv, _sent = session
    conv["head_id"] = "head-a"
    conv["_last_context_stats"] = {
        "context_usage_version": 2,
        "window": 200_000, "total_used": 77_777, "basis": "measured",
    }
    stats = srv.session_context_stats("ctx-test", head_id="head-b")
    assert stats["basis"] == "estimated"
    assert stats["total_used"] != 77_777


# --- graph-change refresh --------------------------------------------

def test_refresh_broadcasts_a_fresh_estimate(session):
    conv, sent = session
    conv["_last_context_stats"] = {
        "type": "context_stats", "window": 200_000,
        "total_used": 190_000, "basis": "measured", "calibration": 2.0,
    }
    srv.refresh_context_stats("ctx-test")

    assert len(sent) == 1
    out = sent[0]
    assert out["type"] == "context_stats"
    assert out["basis"] == "estimated"
    assert out["total_used"] < 190_000        # compaction-shaped drop
    # A stale calibration must not survive into an estimated reading.
    assert "calibration" not in out
    assert conv["_last_context_stats"] is out
    assert out.get("breakdown")
    assert out["breakdown"]["messages"] >= 0


def test_refresh_tracks_a_model_switch_window(monkeypatch, session):
    """Switching model changes the denominator without any request running."""
    conv, sent = session
    conv["_last_context_stats"] = {
        "basis": "measured", "total_used": 99_999,
        "window": 200_000, "calibration": 2.0,
    }
    monkeypatch.setattr(
        srv, "_resolve_context_window",
        lambda provider, model: 1_000_000 if model == "big" else 200_000,
    )
    conv["model_override"] = "big"
    srv.refresh_context_stats("ctx-test")
    assert sent[-1]["window"] == 1_000_000
    assert sent[-1]["context_window"] == 1_000_000
    assert sent[-1]["basis"] == "estimated"
    assert sent[-1]["total_used"] != 99_999
    assert "calibration" not in sent[-1]


def test_refresh_recovers_provider_usage_newer_than_stale_badge(monkeypatch, session):
    conv, sent = session
    conv["_last_context_stats"] = {
        "basis": "estimated", "total_used": 38_000,
        "window": 1_000_000, "timestamp": 100.0,
    }
    import openprogram.runtime.context.session_db as session_db
    monkeypatch.setattr(session_db, "default_db", lambda: type("DB", (), {
        "get_session": lambda self, _sid: {
            "updated_at": 150.0,
            "_usage": json.dumps({"context_usage_version": 2, "last_updated_at": 200.0,
                                  "last_prompt_tokens": 99_000,
                                  "last_cache_read_tokens": 3_000}),
        },
        "get_branch": lambda self, _sid, head_id=None: _FakeDB().get_branch(_sid),
    })())
    srv.refresh_context_stats("ctx-test")
    assert sent[-1]["basis"] == "measured"
    assert sent[-1]["total_used"] == 102_000


def test_refresh_does_not_reuse_usage_after_later_branch_change(monkeypatch, session):
    conv, sent = session
    conv["_last_context_stats"] = {
        "basis": "estimated", "total_used": 38_000,
        "window": 1_000_000, "timestamp": 100.0,
    }
    import openprogram.runtime.context.session_db as session_db
    monkeypatch.setattr(session_db, "default_db", lambda: type("DB", (), {
        "get_session": lambda self, _sid: {
            "updated_at": 250.0,
            "_usage": {"last_updated_at": 200.0,
                       "last_prompt_tokens": 99_000},
        },
        "get_branch": lambda self, _sid, head_id=None: _FakeDB().get_branch(_sid),
    })())
    srv.refresh_context_stats("ctx-test")
    assert sent[-1]["basis"] == "estimated"


def test_refresh_on_an_unknown_session_is_a_no_op(session):
    _conv, sent = session
    srv.refresh_context_stats("no-such-session")
    assert sent == []


def test_refresh_survives_an_estimator_failure(monkeypatch, session):
    """A transient DB error must not blank the ring."""
    conv, sent = session
    conv["_last_context_stats"] = {
        "context_usage_version": 2,
        "window": 200_000, "total_used": 50_000, "basis": "measured",
    }
    monkeypatch.setattr(
        cs, "build_stats",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    srv.refresh_context_stats("ctx-test")
    assert sent[-1]["total_used"] == 50_000


# --- the four triggers are wired ------------------------------------

def test_every_graph_change_calls_refresh(monkeypatch):
    """Compaction, model switch, checkout and delete all re-broadcast.

    Each site is grepped rather than driven end-to-end: the point is that
    no trigger is missing, and a dropped call would silently reintroduce
    the "compaction landed but the ring didn't move" bug.
    """
    import pathlib
    root = (
        pathlib.Path(__file__).resolve().parents[3]
        / "openprogram/interfaces/server"
    )
    wired = {
        "ws_actions/chat/context_usage.py": "in-flight context usage",
        "ws_actions/chat/commands.py": "manual /compact",
        "routes/execution/runtime.py": "model switch (REST)",
        "ws_actions/runtime.py": "model switch (WS)",
        "ws_actions/branch.py": "branch checkout / delete",
        "context_git_routes.py": "sibling checkout",
    }
    for rel, what in wired.items():
        text = (root / rel).read_text(encoding="utf-8")
        assert "refresh_context_stats" in text, f"{what} lost its refresh"
    # branch.py holds two separate call sites (checkout and delete).
    assert (root / "ws_actions/branch.py").read_text(
        encoding="utf-8").count("refresh_context_stats") == 2


def test_missing_last_request_does_not_display_turn_billing(monkeypatch, session):
    from openprogram.interfaces.server.ws_actions.chat import _record_context_usage
    conv, sent = session
    conv["_last_context_stats"] = {
        "total_used": 2404285, "basis": "measured",
        "calibration": 24.6101, "calibration_source": "request",
    }
    _record_context_usage("ctx-test", "msg", conv, {
        "input_tokens": 2254931, "cache_read_tokens": 149354,
        "context_tokens": 0, "request_input_estimate": 97695,
    })
    assert sent[-1]["basis"] == "estimated"
    assert sent[-1]["total_used"] == sent[-1]["estimated"]
    assert sent[-1]["total_used"] < 100000
    assert "calibration" not in sent[-1]


def test_usage_tracker_separates_billing_from_occupancy():
    from openprogram.runtime.context.usage import UsageTracker
    from openprogram.runtime.context.types import UsageState
    tracker = UsageTracker()
    tracker._cache["s"] = UsageState()
    state = tracker.record_turn("s", usage={
        "input_tokens": 2254931, "cache_read_tokens": 149354,
        "context_tokens": 100000,
    }, persist=False)
    assert state.last_prompt_tokens == 100000
    assert state.last_cache_read_tokens == 0
    assert state.cumulative_prompt_tokens == 2254931
    assert state.cumulative_cache_read_tokens == 149354
    state = tracker.record_turn("s", usage={
        "input_tokens": 2000000, "context_tokens": 0,
    }, persist=False)
    assert state.last_prompt_tokens == 0
    assert state.source == "estimate"
