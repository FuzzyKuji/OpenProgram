"""GET /api/providers/status and its Refresh, read from a temp ledger and fake providers."""
from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openprogram.models.usage import provider_status, quota, quota_fetchers
from openprogram.models.usage.event import UsageEvent
from openprogram.models.usage.ledger import UsageLedger
from openprogram.models.usage.quota import QuotaLimit

ROWS = [{"id": "openrouter", "label": "OpenRouter", "enabled": True},
        {"id": "openai-codex", "label": "OpenAI Codex", "enabled": True}]


@pytest.fixture
def client(tmp_path, monkeypatch):
    ledger = UsageLedger(db_path=tmp_path / "usage.db")
    import openprogram.models.usage.ledger as ledger_module
    monkeypatch.setattr(ledger_module, "default_ledger", ledger)
    store = quota.QuotaStore(ledger)
    monkeypatch.setattr(quota, "default_store", store)
    monkeypatch.setattr(provider_status, "default_store", store)
    monkeypatch.setattr(provider_status, "connected_providers", lambda: list(ROWS))
    monkeypatch.setattr(provider_status, "keys_of", lambda provider: [])
    reads: list[tuple] = []

    def fake_refresh(providers=None, *, reason="open", **_):
        reads.append((tuple(providers or ()), reason))
        store.observe("openrouter", "", [QuotaLimit(
            limit_key="key_limit", label="Key limit", unit="usd", source="endpoint",
            fetched_at=time.time(), limit=10, remaining=7)], force_write=True)
        return {"openrouter": 1}

    monkeypatch.setattr(quota_fetchers, "refresh", fake_refresh)
    ledger.append(UsageEvent(ts=time.time(), session_id="s", call_kind="chat", provider="openai-codex",
                             model_id="gpt-6.1-sol", input_tokens=100, output_tokens=10, cache_read_tokens=900,
                             total_tokens=1010, cost_total=2.0, cost_source="model_catalog"))
    app = FastAPI()
    from openprogram.interfaces.server.routes.identity import providers as routes
    routes.register(app)
    c = TestClient(app)
    c.reads = reads  # type: ignore[attr-defined]
    yield c
    ledger.close()


def test_status_lists_every_connected_provider(client):
    payload = client.get("/api/providers/status").json()
    by_id = {p["id"]: p for p in payload["providers"]}
    codex = by_id["openai-codex"]
    assert codex["billing"] == "subscription"
    assert codex["spend"]["included"] is True and codex["spend"]["cost_usd"] is None
    assert codex["spend"]["cache_share"] == pytest.approx(0.9)
    assert codex["default_model"] == "gpt-6.1-sol"
    assert by_id["openrouter"]["quota"]["kind"] == "none"
    assert set(codex) == set(provider_status.ProviderStatus.__annotations__)
    # A page opening reads endpoints older than ten minutes, after answering.
    deadline = time.time() + 2
    while not client.reads and time.time() < deadline:
        time.sleep(0.01)
    assert client.reads == [(("openrouter", "openai-codex"), "open")]


def test_refresh_reads_now_and_answers_with_the_new_values(client):
    payload = client.post("/api/providers/status/refresh", json={"providers": ["openrouter"]}).json()
    assert [p["id"] for p in payload["providers"]] == ["openrouter"]
    assert payload["providers"][0]["quota"]["limits"][0]["remaining"] == 7
    assert client.reads == [(("openrouter",), "manual")]


def test_refresh_refuses_a_bad_body(client):
    assert client.post("/api/providers/status/refresh", json={"providers": "openrouter"}).status_code == 400
    assert client.post("/api/providers/status/refresh", json={"other": 1}).status_code == 400
