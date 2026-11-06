"""What a page printed and fetched: console messages, uncaught errors and requests.

Playwright keeps the recent console messages, page errors and requests of
every Page it drives, so reading them needs no listener installed in
advance and misses nothing the page did before the first read. Requests
are listed without query strings, fragments or bodies: those carry tokens
and form data that observations never show either.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

LOG_ACTIONS = ("console_messages", "network_requests")
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_TEXT = 500
_ERROR_TYPES = frozenset({"error", "assert"})


class LogError(ValueError):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


def options(arguments: dict[str, Any]) -> tuple[str, bool, int]:
    pattern = str(arguments.get("pattern") or "").strip().lower()
    only_errors = bool(arguments.get("only_errors"))
    raw = arguments.get("limit")
    try:
        limit = DEFAULT_LIMIT if raw in (None, "") else int(raw)
    except (TypeError, ValueError) as exc:
        raise LogError("invalid_limit", f"limit must be 1 to {MAX_LIMIT}") from exc
    if not 1 <= limit <= MAX_LIMIT:
        raise LogError("invalid_limit", f"limit must be 1 to {MAX_LIMIT}")
    return pattern, only_errors, limit


def short_url(url: str) -> str:
    """The URL without query or fragment; a data: URL by its type only."""
    url = str(url or "")
    if url.startswith(("data:", "blob:")):
        return url.split(",", 1)[0][:60] + ",…"
    parts = urlsplit(url)
    if not parts.scheme:
        return url[:200]
    base = f"{parts.scheme}://{parts.netloc}{parts.path}"
    return base[:300] + ("?…" if parts.query else "")


def _clip(text: Any) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + "…"


def console_rows(page) -> list[dict[str, str]]:
    """Console messages and uncaught errors, oldest first."""
    read = getattr(page, "console_messages", None)
    if not callable(read):
        raise LogError("unsupported_backend", "Reading the console needs Playwright 1.56 or newer.")
    rows = []
    for message in read() or []:
        location = getattr(message, "location", None) or {}
        where = short_url(location.get("url") or "") if isinstance(location, dict) else ""
        line = location.get("lineNumber") if isinstance(location, dict) else None
        rows.append({"type": str(getattr(message, "type", "log") or "log"), "text": _clip(message.text),
                     "where": f"{where}:{line}" if where and line is not None else where})
    errors = getattr(page, "page_errors", None)
    for error in (errors() if callable(errors) else None) or []:
        rows.append({"type": "pageerror", "text": _clip(getattr(error, "message", None) or error), "where": ""})
    return rows


def request_rows(page) -> list[dict[str, Any]]:
    """Requests the page made, oldest first, with their outcome when known."""
    read = getattr(page, "requests", None)
    if not callable(read):
        raise LogError("unsupported_backend", "Reading network requests needs Playwright 1.56 or newer.")
    rows = []
    for request in read() or []:
        failure = getattr(request, "failure", None)
        status: Any = None
        timing = getattr(request, "timing", None) or {}
        if not failure and isinstance(timing, dict) and (timing.get("responseEnd") or -1) >= 0:
            try:
                response = request.response()
                status = response.status if response is not None else None
            except Exception:
                status = None
        rows.append({"method": str(request.method), "url": short_url(request.url),
                     "type": str(getattr(request, "resource_type", "") or ""),
                     "status": status, "failure": str(failure or "")})
    return rows


def render_console(rows: list[dict[str, str]], pattern: str, only_errors: bool, limit: int) -> str:
    picked = [r for r in rows if (not only_errors or r["type"] in _ERROR_TYPES or r["type"] == "pageerror")
              and (not pattern or pattern in r["text"].lower())]
    if not picked:
        return "No console messages" + (" match" if pattern or only_errors else " yet") + "."
    shown = picked[-limit:]
    lines = [f"[{r['type']}] {r['text']}" + (f"  ({r['where']})" if r["where"] else "") for r in shown]
    head = f"{len(shown)} of {len(picked)} console message(s), oldest first:"
    return head + "\n" + "\n".join(lines)


def render_requests(rows: list[dict[str, Any]], pattern: str, only_errors: bool, limit: int) -> str:
    def failed(r):
        return bool(r["failure"]) or (isinstance(r["status"], int) and r["status"] >= 400)
    picked = [r for r in rows if (not only_errors or failed(r)) and (not pattern or pattern in r["url"].lower())]
    if not picked:
        return "No requests" + (" match" if pattern or only_errors else " yet") + "."
    shown = picked[-limit:]
    lines = []
    for r in shown:
        outcome = f"failed: {r['failure']}" if r["failure"] else (str(r["status"]) if r["status"] is not None else "no response")
        lines.append(f"{r['method']} {r['url']} → {outcome}" + (f" [{r['type']}]" if r["type"] else ""))
    head = f"{len(shown)} of {len(picked)} request(s), oldest first; query strings and bodies are not shown:"
    return head + "\n" + "\n".join(lines)


__all__ = ["DEFAULT_LIMIT", "LOG_ACTIONS", "LogError", "MAX_LIMIT", "console_rows", "options", "render_console",
           "render_requests", "request_rows", "short_url"]
