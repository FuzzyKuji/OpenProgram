"""``openprogram providers status``: every connected provider on one screen, or the route's JSON."""
from __future__ import annotations

import json

from openprogram.interfaces.cli.commands.providers import quota_status
from openprogram.interfaces.cli.parser import build_parser

NOW = 1_800_000_000.0


def _spend(**extra) -> dict:
    spend = {"days": 30, "calls": 12, "cost_usd": 4.2, "list_price_usd": 4.2, "included": False,
             "unpriced_calls": 0, "input_tokens": 1000, "output_tokens": 200, "cache_read_tokens": 3000,
             "cache_write_tokens": 0, "total_tokens": 4200, "cache_share": 0.75, "series": []}
    spend.update(extra)
    return spend


def _limit(**extra) -> dict:
    limit = {"limit_key": "primary", "label": "5h", "unit": "percent", "source": "headers", "fetched_at": NOW,
             "used": 60.0, "limit": 100.0, "remaining": 40.0, "used_fraction": 0.6, "left_fraction": 0.4,
             "window_minutes": 300, "resets_at": None, "status": "ok", "stale": False}
    limit.update(extra)
    return limit


PAYLOAD = {
    "generated_at": NOW, "stale_after_s": 900,
    "providers": [
        {"id": "openai-codex", "label": "OpenAI Codex", "billing": "subscription", "enabled": True,
         "health": {"state": "ready", "until": None, "detail": None},
         "quota": {"kind": "windowed", "account": "c", "fetched_at": NOW, "stale": False,
                   "limits": [_limit(), _limit(limit_key="secondary", label="Weekly", left_fraction=0.65)]},
         "spend": _spend(cost_usd=None, included=True), "default_model": "gpt-6.1-sol", "keys": []},
        {"id": "openrouter", "label": "OpenRouter", "billing": "api_key", "enabled": True,
         "health": {"state": "no_credit", "until": None, "detail": "Key limit"},
         "quota": {"kind": "balance", "account": "c", "fetched_at": NOW, "stale": False,
                   "limits": [_limit(limit_key="key_limit", label="Key limit", unit="usd", remaining=0.0,
                                     limit=5.0, left_fraction=0.0, window_minutes=None)]},
         "spend": _spend(unpriced_calls=2), "default_model": None, "keys": []},
        {"id": "openai", "label": "OpenAI", "billing": "api_key", "enabled": True,
         "health": {"state": "unknown", "until": None, "detail": None},
         "quota": {"kind": "rate_limit", "account": None, "fetched_at": NOW - 3600, "stale": True,
                   "limits": [_limit(limit_key="rpm", label="Req/min", unit="requests", remaining=499.0,
                                     limit=500.0, left_fraction=0.998, window_minutes=1)]},
         "spend": _spend(), "default_model": None, "keys": []},
        {"id": "mistral", "label": "Mistral", "billing": "api_key", "enabled": True,
         "health": {"state": "unknown", "until": None, "detail": None},
         "quota": {"kind": "none", "account": None, "fetched_at": None, "stale": False, "limits": []},
         "spend": _spend(cost_usd=0.0, calls=0, total_tokens=0, cache_share=None), "default_model": None,
         "keys": []},
    ],
}


def test_the_table_shows_each_kind_of_quota():
    text = quota_status.render(PAYLOAD, now=NOW + 30)
    assert "5h       [████████░░░░░░░░░░░░] 40% left" in text
    assert "Weekly   [█████████████░░░░░░░] 65% left" in text
    assert "30d Included · 4.2k tok · cache 75%" in text
    assert "Key limit: $0.00 left of $5.00" in text and "no credit" in text
    assert "$4.20 · 2 calls unpriced" in text
    assert "Req/min  [████████████████████] 499/500" in text and "no balance data" in text
    assert "may be stale · updated 1 h ago" in text
    assert "no quota data" in text
    assert text.splitlines()[-1].endswith("--refresh · --json")
    assert "gpt-6.1-sol" in text


def _codex(**health) -> dict:
    weekly = _limit(limit_key="secondary", label="Weekly", left_fraction=0.79, resets_at=NOW + 5 * 86400)
    return {"generated_at": NOW, "providers": [dict(
        PAYLOAD["providers"][0], label="OpenCode Go",
        health={"state": "rate_limited", "until": None, "detail": None, **health},
        quota=dict(PAYLOAD["providers"][0]["quota"], limits=[weekly]))]}


def test_a_past_time_is_never_printed_as_a_coming_one():
    text = quota_status.render(_codex(until=NOW - 37 * 3600), now=NOW)
    assert text.splitlines()[0].rstrip().endswith("rate limited  ·  gpt-6.1-sol")
    coming = quota_status.render(_codex(until=NOW + 600), now=NOW).splitlines()[0]
    assert "rate limited · until " in coming
    stale = _codex()
    stale["providers"][0]["quota"]["limits"][0]["resets_at"] = NOW - 60
    assert "resets" not in quota_status.render(stale, now=NOW)


def test_the_table_fits_the_terminal_width():
    wide = quota_status.render(_codex(), now=NOW)
    assert "[████████████████░░░░] 79% left (resets " in wide
    for columns in (60, 50, 40):
        lines = quota_status.render(_codex(), now=NOW, columns=columns).splitlines()
        weekly = [line for line in lines if "Weekly" in line or "resets" in line]
        assert all(len(line) <= columns for line in weekly), (columns, weekly)
        assert any("resets " in line for line in weekly) and any("79% left" in line for line in weekly)


def test_a_failed_quota_read_is_named_once_below_the_values_it_kept():
    payload = json.loads(json.dumps(PAYLOAD))
    payload["providers"][1]["quota"].update(read_error="HTTP 401", read_at=NOW - 120)
    text = quota_status.render(payload, now=NOW)
    assert text.count("last quota read failed: HTTP 401 · 2 min ago") == 1
    assert "Key limit: $0.00 left of $5.00" in text


def test_no_providers_says_how_to_add_one():
    assert "openprogram providers login" in quota_status.render({"providers": []}, now=NOW)


def test_status_without_a_provider_is_the_overview(monkeypatch, capsys):
    calls: list[str] = []

    def build_status(*, refresh):
        calls.append(refresh)
        return PAYLOAD

    import openprogram.models.usage.provider_status as provider_status
    monkeypatch.setattr(provider_status, "build_status", build_status)
    from openprogram.interfaces.cli.commands.providers import dispatch

    parser = build_parser()
    assert dispatch(parser.parse_args(["providers", "status", "--json"])) == 0
    assert json.loads(capsys.readouterr().out) == PAYLOAD
    assert dispatch(parser.parse_args(["providers", "status", "--refresh"])) == 0
    assert "OpenRouter" in capsys.readouterr().out
    assert calls == ["stale", "force"]
    args = parser.parse_args(["providers", "status", "openai"])
    assert args.provider == "openai"
