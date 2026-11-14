"""One status per connected provider: health, quota, 30-day spend, keys.

The payload of ``GET /api/providers/status`` and of ``openprogram providers
status --json``, built here once so the page and the CLI read the same
data. Its shape is the TypedDicts below; ``scripts/generate_provider_status_types.py``
writes them as TypeScript for the web.

A provider is connected when it is enabled or has a key (a stored
credential or an environment key); local servers count only when enabled.
Spend comes from ``usage.db`` (``UsageLedger.provider_days``); a
subscription's calls are included in its plan, so its spend reads as
included, with the API list price kept apart.
"""
from __future__ import annotations

import time
from typing import Any, Literal, Optional, TypedDict

from .quota import STALE_AFTER_S, QuotaReport, default_store, report_kind

DAYS = 30

#: Providers billed by a plan, not per token: their spend reads as included.
SUBSCRIPTION_PROVIDERS = frozenset({
    "openai-codex", "xai-subscription", "opencode-go", "kimi-coding", "github-copilot",
    "gemini-subscription", "google-gemini-cli", "alibaba-token-plan-cn",
})

HealthState = Literal[
    "ready", "rate_limited", "signed_out", "no_credit", "invalid_key", "unknown",
]
QuotaKind = Literal["windowed", "balance", "rate_limit", "none"]
Billing = Literal["api_key", "subscription", "local"]


class QuotaLimitWire(TypedDict):
    limit_key: str
    label: str
    unit: str
    source: str
    fetched_at: float
    used: Optional[float]
    limit: Optional[float]
    remaining: Optional[float]
    used_fraction: Optional[float]
    left_fraction: Optional[float]
    window_minutes: Optional[int]
    resets_at: Optional[float]
    status: str
    stale: bool


class QuotaWire(TypedDict):
    kind: QuotaKind
    account: Optional[str]
    fetched_at: Optional[float]
    stale: bool
    limits: list[QuotaLimitWire]
    #: Why the last read of this key's quota endpoint failed; its values above keep their own times.
    read_error: Optional[str]
    read_at: Optional[float]


class HealthWire(TypedDict):
    state: HealthState
    until: Optional[float]
    detail: Optional[str]


class SpendDay(TypedDict):
    day: str
    cost_usd: float
    tokens: int
    calls: int


class SpendWire(TypedDict):
    days: int
    calls: int
    cost_usd: Optional[float]
    list_price_usd: float
    included: bool
    unpriced_calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    cache_share: Optional[float]
    series: list[SpendDay]


class KeyHealth(TypedDict):
    account: str
    credential_id: str
    kind: str
    status: str
    active: bool
    cooldown_until: Optional[float]
    last_error: Optional[str]
    last_used_at: Optional[float]
    use_count: int
    #: When ``status`` was last written (the pool's ``updated_at``), to weigh it against a later quota read.
    status_at: Optional[float]


class ProviderStatus(TypedDict):
    id: str
    label: str
    billing: Billing
    enabled: bool
    health: HealthWire
    quota: QuotaWire
    spend: SpendWire
    default_model: Optional[str]
    keys: list[KeyHealth]


class ProviderQuotaFrame(TypedDict):
    """``data`` of the ``provider_quota`` WebSocket frame: one key's new quota."""

    provider: str
    account: str
    kind: QuotaKind
    fetched_at: Optional[float]
    stale: bool
    limits: list[QuotaLimitWire]


class ProviderStatusPayload(TypedDict):
    generated_at: float
    stale_after_s: int
    providers: list[ProviderStatus]


# Health

_STATE_OF = {
    "valid": "ready", "expiring_soon": "ready", "refreshing": "ready",
    "rate_limited": "rate_limited", "needs_reauth": "signed_out", "stale": "signed_out",
    "billing_blocked": "no_credit", "revoked": "invalid_key",
}
_RANK = {"ready": 0, "unknown": 1, "rate_limited": 2, "signed_out": 3, "no_credit": 4, "invalid_key": 5}


_REFUSED = "quota endpoint answered 401"


def _refused(read: Optional[dict], last_used_at: Optional[float]) -> bool:
    """Whether the key's last quota read was refused with 401 and no call has worked since."""
    if not read or read.get("status") != 401 or not read.get("error"):
        return False
    return not (last_used_at and read.get("read_at") and last_used_at > read["read_at"])


def _key_view(key: KeyHealth, now: float, read: Optional[dict] = None) -> tuple[HealthState, Optional[str]]:
    """A key's state now and why, from the newest evidence about it.

    Two records speak about a key: its pool status, written when a call
    failed (``status_at``), and the last read of its quota endpoint
    (``read_at``). The newer one wins; at the same time a 401 from the
    endpoint outranks a stored billing stop or throttle. So a stored
    status expires the way a throttle does (``pool._is_healthy`` picks a
    key again once ``cooldown_until`` has passed, so an expired throttle
    reads ``ready``): a ``billing_blocked`` stop is overruled by a later
    read that answered, after which a spent balance on that read decides,
    and by a later 401, which reads ``invalid_key``.
    """
    state: HealthState = _STATE_OF.get(key["status"], "unknown")  # type: ignore[assignment]
    read_at = (read or {}).get("read_at")
    if read and read_at is not None and read_at >= (key.get("status_at") or 0.0):
        if _refused(read, key["last_used_at"]):
            return "invalid_key", _REFUSED
        if state == "no_credit" and not read.get("error"):
            state = "ready"
    if state in ("ready", "rate_limited"):
        cooling = bool(key["cooldown_until"] and key["cooldown_until"] > now)
        state = "rate_limited" if cooling else "ready"
    return state, (key["last_error"] if state != "ready" else None)


def health_of(keys: list[KeyHealth], reports: list[QuotaReport], now: float,
              reads: Optional[dict[str, dict]] = None) -> HealthWire:
    """The best key's state from its newest evidence; a spent quota overrides a ready one."""
    reads = reads or {}
    if not keys:
        if _refused(reads.get(""), None):
            return {"state": "invalid_key", "until": None, "detail": _REFUSED}
        return {"state": "unknown", "until": None, "detail": None}
    views = {k["credential_id"]: _key_view(k, now, reads.get(k["credential_id"])) for k in keys}
    best = min(keys, key=lambda k: (_RANK[views[k["credential_id"]][0]], not k["active"]))
    state, detail = views[best["credential_id"]]
    until = best["cooldown_until"] if state == "rate_limited" else None
    if state == "ready":
        report = next((r for r in reports if r.account == best["credential_id"]), None)
        spent = [limit for limit in (report.limits if report else []) if limit.status == "exhausted"]
        if spent:
            limit = max(spent, key=lambda item: item.resets_at or 0.0)
            balance = limit.limit_key.rsplit(":", 1)[-1] in ("balance", "key_limit", "credits")
            state = "no_credit" if balance else "rate_limited"
            until = None if balance else limit.resets_at
            detail = limit.label
    return {"state": state, "until": until, "detail": detail}


def keys_of(provider: str) -> list[KeyHealth]:
    """Each stored key of a provider with its health; never its value."""
    try:
        from openprogram.models.auth.account.account_selection import get_active_account
        from openprogram.models.auth.store import get_store
        pools = [pool for pool in get_store().list_pools() if pool.provider_id == provider]
        active = get_active_account(provider)
    except Exception:
        return []
    out: list[KeyHealth] = []
    for pool in pools:
        for cred in pool.credentials:
            out.append({
                "account": pool.account_id,
                "credential_id": cred.credential_id,
                "kind": str(cred.kind),
                "status": str(cred.status),
                "active": pool.account_id == active,
                "cooldown_until": cred.cooldown_until_ms / 1000 if cred.cooldown_until_ms else None,
                "last_error": cred.last_error,
                "last_used_at": cred.last_used_at_ms / 1000 if cred.last_used_at_ms else None,
                "use_count": int(cred.use_count or 0),
                "status_at": cred.updated_at_ms / 1000 if cred.updated_at_ms else None,
            })
    return out


# Spend

def _day(index: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(index * 86400))


def spend_of(provider: str, rows: list[dict], now: float) -> SpendWire:
    """Thirty days of one provider's calls, with a point for every day."""
    first = int(now // 86400) - DAYS + 1
    by_day = {int(row["day"]): row for row in rows}
    series: list[SpendDay] = []
    for index in range(first, first + DAYS):
        row = by_day.get(index) or {}
        tokens = sum(int(row.get(k) or 0) for k in
                     ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"))
        series.append({"day": _day(index), "cost_usd": round(float(row.get("cost") or 0.0), 6),
                       "tokens": tokens, "calls": int(row.get("calls") or 0)})
    total = {k: sum(int(row.get(k) or 0) for row in rows) for k in
             ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "calls",
              "unpriced_calls")}
    price = round(sum(float(row.get("cost") or 0.0) for row in rows), 6)
    prompt = total["input_tokens"] + total["cache_read_tokens"] + total["cache_write_tokens"]
    included = provider in SUBSCRIPTION_PROVIDERS
    return {
        "days": DAYS,
        "calls": total["calls"],
        "cost_usd": None if included else price,
        "list_price_usd": price,
        "included": included,
        "unpriced_calls": total["unpriced_calls"],
        "input_tokens": total["input_tokens"],
        "output_tokens": total["output_tokens"],
        "cache_read_tokens": total["cache_read_tokens"],
        "cache_write_tokens": total["cache_write_tokens"],
        "total_tokens": prompt + total["output_tokens"],
        "cache_share": round(total["cache_read_tokens"] / prompt, 4) if prompt else None,
        "series": series,
    }


# Quota

def quota_of(reports: list[QuotaReport], keys: list[KeyHealth], now: float,
             reads: Optional[dict[str, dict]] = None) -> QuotaWire:
    """The quota of the key in use (the active one, else the one last reported).

    A failed last read of that key's endpoint is carried once, as
    ``read_error``; the values it could not refresh stay, with their times.
    """
    reads = reads or {}
    active = {k["credential_id"] for k in keys if k["active"]}
    if not reports:
        account = next(iter(sorted(active & set(reads))), None) or next(iter(sorted(reads)), None)
        read = reads.get(account) if account is not None else None
        return {"kind": "none", "account": account or None, "fetched_at": None, "stale": False, "limits": [],
                "read_error": (read or {}).get("error"), "read_at": (read or {}).get("read_at")}
    report = next((r for r in reports if r.account in active), None) \
        or max(reports, key=lambda r: r.fetched_at or 0.0)
    wire = report.wire(now)
    read = reads.get(report.account) or {}
    return {"kind": report_kind(report.limits), "account": report.account or None,  # type: ignore[typeddict-item]
            "fetched_at": wire["fetched_at"], "stale": wire["stale"], "limits": wire["limits"],
            "read_error": read.get("error"), "read_at": read.get("read_at")}


# Providers

def connected_providers() -> list[dict]:
    """The catalogue rows of the providers that are enabled or hold a key."""
    from openprogram.models import listing
    from openprogram.models.providers.catalog.local import is_local_provider
    rows = listing.list_providers()
    return [row for row in rows
            if row.get("enabled") or (row.get("configured") and not is_local_provider(row["id"]))]


def _default_models(now: float, ledger: Any) -> dict[str, str]:
    """Per provider: the model last picked if it is this provider's, else its most used."""
    out: dict[str, str] = {}
    try:
        for row in ledger.provider_models(since=now - DAYS * 86400):
            out.setdefault(row["provider"], row["model_id"])
    except Exception:
        pass
    try:
        from openprogram.models.providers.catalog.last_used import last_used_in_config
        from openprogram.state import config as user_config
        pair = last_used_in_config(user_config.read_config())
        if pair:
            out[pair[0]] = pair[1]
    except Exception:
        pass
    return out


def build_status(*, refresh: str = "none", providers: Optional[list[dict]] = None,
                 ledger: Any = None, now: Optional[float] = None) -> ProviderStatusPayload:
    """The status of every connected provider.

    ``refresh`` is ``"none"`` (stored values only), ``"stale"`` (read the
    quota endpoints whose value is older than ten minutes, as a page opening
    does) or ``"force"`` (read them all now, as Refresh does).
    """
    now = time.time() if now is None else now
    if ledger is None:
        from .ledger import default_ledger as ledger
    rows = connected_providers() if providers is None else providers
    ids = [row["id"] for row in rows]
    if refresh in ("stale", "force"):
        from .quota_fetchers import refresh as read_quota
        read_quota(ids, reason="open" if refresh == "stale" else "manual")
    from .quota_fetchers import last_reads
    days = ledger.provider_days(since=(int(now // 86400) - DAYS + 1) * 86400)
    defaults = _default_models(now, ledger)
    from openprogram.models.providers.catalog.local import is_local_provider
    out: list[ProviderStatus] = []
    for row in rows:
        pid = row["id"]
        keys = keys_of(pid)
        reports = default_store.reports(pid)
        stored = {k["credential_id"] for k in keys} | {""}
        reports = [r for r in reports if r.account in stored]
        reads = {a: r for a, r in last_reads(pid).items() if a in stored}
        billing: Billing = "local" if is_local_provider(pid) else (
            "subscription" if pid in SUBSCRIPTION_PROVIDERS else "api_key")
        out.append({
            "id": pid,
            "label": str(row.get("label") or pid),
            "billing": billing,
            "enabled": bool(row.get("enabled")),
            "health": health_of(keys, reports, now, reads),
            "quota": quota_of(reports, keys, now, reads),
            "spend": spend_of(pid, [d for d in days if d["provider"] == pid], now),
            "default_model": defaults.get(pid),
            "keys": keys,
        })
    return {"generated_at": now, "stale_after_s": STALE_AFTER_S, "providers": out}


__all__ = [
    "DAYS",
    "HealthWire",
    "KeyHealth",
    "ProviderQuotaFrame",
    "ProviderStatus",
    "ProviderStatusPayload",
    "QuotaLimitWire",
    "QuotaWire",
    "SUBSCRIPTION_PROVIDERS",
    "SpendDay",
    "SpendWire",
    "build_status",
    "connected_providers",
    "health_of",
    "keys_of",
    "quota_of",
    "spend_of",
]
