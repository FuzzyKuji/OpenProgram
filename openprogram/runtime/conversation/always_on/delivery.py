"""Send always-on reports to the channel conversations an Agent picked.

A report is saved first, then sent in the background, one message per
target, through the channels' stateless outbound path
(``openprogram.runtime.channel_link``). A failed send
never loses the report or fails the tool; its result is recorded on the
report row.

Design: docs/reference/design/runtime/always-on-agents.md
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from openprogram.runtime.conversation.always_on import store


def _key(target: dict[str, Any]) -> tuple[str, str, str]:
    return (str(target.get("channel") or ""), str(target.get("account_id") or ""),
            str(target.get("peer_id") or ""))


def channel_targets(agent_id: str) -> list[dict[str, str]]:
    """Channel conversations reports can go to: peer bindings of this Agent
    and the channel conversations it already has, newest first."""
    from openprogram.runtime.agent_registry.manager import ALWAYS_ON_CHANNELS
    from openprogram.runtime import channel_link
    from openprogram.runtime.context.session_db import default_db

    found: dict[tuple[str, str, str], dict[str, str]] = {}

    def add(channel: str, account_id: str, peer_id: str, label: str) -> None:
        target = {"channel": channel, "account_id": account_id, "peer_id": peer_id,
                  "label": label or peer_id}
        if channel in ALWAYS_ON_CHANNELS and account_id and peer_id:
            found.setdefault(_key(target), target)

    try:
        rows = default_db().list_sessions(agent_id=agent_id, limit=500, include_archived=True)
    except Exception:
        rows = []
    for row in rows:
        if row.get("channel") and row.get("peer_id"):
            add(str(row["channel"]), str(row.get("account_id") or ""), str(row["peer_id"]),
                str(row.get("peer_display") or ""))
    for binding in channel_link.peer_bindings(agent_id):
        match = binding.get("match") or {}
        peer = match.get("peer") or {}
        if not peer.get("id"):
            continue
        channel = str(match.get("channel") or "")
        account_ids = ([match["account_id"]] if match.get("account_id")
                       else channel_link.account_ids(channel))
        for account_id in account_ids:
            add(channel, str(account_id), str(peer["id"]), "")
    return list(found.values())


def report_text(agent_name: str, report: dict[str, Any]) -> str:
    """Markdown; the channel transport renders it for each platform."""
    parts = [f"**{agent_name} · {report.get('title') or ''}**"]
    if report.get("body"):
        parts.append(str(report["body"]))
    if report.get("links"):
        parts.append("\n".join(f"- {link}" for link in report["links"]))
    return "\n\n".join(parts)


def pending(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**target, "status": "sending"} for target in targets]


def deliver(session_id: str, agent_name: str, report: dict[str, Any],
            on_done: Callable[[dict[str, Any] | None], None] | None = None) -> threading.Thread | None:
    """Send ``report`` to its pending deliveries in a daemon thread."""
    targets = [row for row in report.get("deliveries") or [] if row.get("status") == "sending"]
    if not targets:
        return None

    def run() -> None:
        from openprogram.runtime import channel_link

        text = report_text(agent_name, report)
        results = []
        for target in targets:
            try:
                sent = channel_link.send_message(target["channel"], target["account_id"],
                                                 target["peer_id"], text)
                ok, error = sent.ok, "" if sent.ok else (sent.error_kind or "unknown")
                detail = "" if sent.ok else str(sent.error_detail or "")[:300]
            except Exception as exc:  # noqa: BLE001 - a send must never lose the report
                ok, error, detail = False, "unknown", f"{type(exc).__name__}: {exc}"[:300]
            row = {key: value for key, value in target.items() if key != "status"}
            row["status"] = "sent" if ok else "failed"
            if not ok:
                row["error"], row["detail"] = error, detail
            results.append(row)
        updated = store.update_report(session_id, report["id"], deliveries=results)
        if on_done is not None:
            on_done(updated)

    thread = threading.Thread(target=run, name=f"always-on-deliver-{session_id}", daemon=True)
    thread.start()
    return thread
