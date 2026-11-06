"""Target ``browser``: a web browser, chosen first, then operated with one set of actions.

As in Codex, the browser is chosen by ``args.browser``: omitted, it is
OpenProgram's built-in browser, whose tabs the browser application's tab
driver drives; ``chrome`` or ``edge`` is the user's own browser, reached
through the Playwright Extension. The actions are the same in all of them.

Both come from the ``browser`` service; without it the target is
unavailable and computer_use_agent operates the desktop only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openprogram.programs._host.execution import ToolReturn

NAME = "browser"

# Actions that only read, so a failed one changed nothing.
READS = frozenset({"tabs", "read", "wait", "screenshot", "console", "network"})
# Choosing the browser; it is not an argument of any action.
_BROWSER_FIELD = "browser"

_GUIDE = (Path(__file__).parent.parent / "guides" / "browser.md").read_text(encoding="utf-8")

# The user's browser speaks the Playwright MCP backend's names.
_EXTENSION_NAMES = {"tabs": "list_pages", "read": "observe", "open": "observe", "console": "console_messages",
                    "network": "network_requests"}


def guide() -> str:
    return _GUIDE


def _browser():
    from openprogram.programs._host import services as _services
    return _services.lookup("browser")


def available() -> bool:
    """Whether the browser application is loaded."""
    return _browser() is not None


def actions() -> tuple[str, ...]:
    """The tab driver's actions; none without the browser."""
    browser = _browser()
    return tuple(browser.tabs.ACTIONS) if browser is not None else ()


def _is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith((".localhost", ".test"))


def user_browser(args: dict) -> str:
    """``chrome`` or ``edge`` when the call operates the user's own browser, else ``""``."""
    browser = _browser()
    return browser.browser_of(args) if browser is not None else ""


def approval(steps: list[tuple[str, dict]], args: dict) -> str | bool:
    """Uploads and new external origins ask; the App's own tabs are the conversation's to use.

    The user's own Chrome or Edge holds their sign-ins: one grant covers it."""
    chosen = user_browser(args)
    if chosen:
        names = _browser().user_browser_names
        if any(action == "upload" for action, _ in steps):
            return f"computer_use_agent uploads a local file to a website in your {names[chosen]}"
        return f"computer_use_agent controls your {names[chosen]}"
    for action, step in steps:
        merged = {**args, **step}
        if action == "upload":
            return "Upload the selected local file to the website; this can transmit file contents immediately."
        url = str(merged.get("url") or "")
        if url and not _is_local(url):
            return f"computer_use_agent opens {urlparse(url).scheme}://{urlparse(url).netloc}"
    return False


def evaluates(steps: list[tuple[str, dict]]) -> bool:
    """Whether a call runs page JavaScript, which is approved every time."""
    return any(action == "evaluate" for action, _ in steps)


def open_target(args: dict, session: str) -> ToolReturn:
    return run([("tabs", {})], args, session)


def render(result: dict[str, Any]) -> str:
    """A result as the model reads it: a header line, then the page or its changes as YAML."""
    if result.get("ok") is False:
        lines = [f"Error ({result.get('reason_code')}): {result.get('error') or result.get('message') or ''}".rstrip()]
    elif "tabs" in result:
        rows = result["tabs"]
        if not rows:
            return "No tabs are open. open(url) opens one."
        return "Tabs (the current one is used when tab is omitted):\n" + "\n".join(
            f"- {row['tab']}{' (current)' if row.get('current') else ''}: {row.get('title') or '(untitled)'} — "
            f"{row.get('url') or ''} [{row.get('shown')}{', focused' if row.get('focused') else ''}]" for row in rows)
    else:
        lines = [result["done"]] if result.get("done") else []
    if result.get("tab") and result.get("url") is not None:
        lines.append(f"tab {result['tab']} · {result.get('title') or '(untitled)'} · {result['url']}")
    elif result.get("tab") and not lines:
        lines.append(f"tab {result['tab']}")
    if result.get("note"):
        lines.append(f"note: {result['note']}")
    if result.get("file_chooser"):
        chooser = result["file_chooser"]
        kinds = f" for {chooser['accept']}" if chooser.get("accept") else ""
        lines.append(f"the page opened a file chooser{kinds}{' (several files)' if chooser.get('multiple') else ''}; "
                     "upload(path) without ref answers it. Nothing opened on the user's screen")
    for row in result.get("opened") or []:
        lines.append(f"it opened a new tab {row['tab']} · {row.get('title') or '(untitled)'} · {row.get('url') or ''}; "
                     f"pass tab=\"{row['tab']}\" to use it")
    for key, label in (("result", "result"), ("console", "console"), ("network", "network")):
        if key in result:
            value = result[key]
            body = value if isinstance(value, str) else "\n".join(
                item if isinstance(item, str) else
                f"{item['method']} {item['url']} → {item.get('error') or item['status']}" for item in value)
            lines.append(f"{label}:\n{body or '(none)'}")
    if "page" in result:
        lines.append("page:\n" + result["page"])
    elif "changes" in result:
        lines.append("changes:\n" + (result["changes"] or "(nothing on the page changed)"))
    if result.get("tabs") is not None and result.get("ok") is False:
        lines.append("tabs: " + ", ".join(f"{row['tab']} ({row.get('title') or row.get('url')})"
                                          for row in result["tabs"]))
    return "\n".join(lines)


def _one(action: str, step: dict, args: dict, session: str = "") -> ToolReturn:
    merged = {**args, **step}
    chosen = user_browser(merged)
    merged.pop(_BROWSER_FIELD, None)
    if chosen:
        return _in_user_browser(chosen, action, merged, session)
    result = _browser().tabs.driver().run(action, merged, session)
    images = result.pop("_images", [])
    return ToolReturn(text=render(result), json_data=result, images=images, is_error=result.get("ok") is False)


def _in_user_browser(chosen: str, action: str, merged: dict, session: str) -> ToolReturn:
    extension_browser = _browser().extension
    try:
        browser = extension_browser.ExtensionBrowser(session, chosen)
    except extension_browser.Unavailable as exc:
        return ToolReturn(text=f"Error: {exc}", is_error=True)
    if "tab" in merged:
        merged["page"] = merged.pop("tab")
    name = _EXTENSION_NAMES.get(action, action)
    if name in ("list_pages", "observe", "close"):
        result = browser.run(name, merged)
    else:
        result = browser.run("act", {"action": name, **merged})
    images = result.pop("_images", [])
    return ToolReturn(json_data=result, images=images, is_error=result.get("ok") is False)


def run(steps: list[tuple[str, dict]], args: dict, session: str) -> ToolReturn:
    """Run one action, or several in order, stopping at the first failure."""
    browser = _browser()
    if browser is None:
        return ToolReturn(text="Error: the browser is not enabled; computer_use_agent operates the desktop only.",
                          is_error=True)
    known = browser.tabs.ACTIONS
    for number, (action, _) in enumerate(steps, 1):
        if action not in known:
            where = f"step {number}: " if len(steps) > 1 else ""
            return ToolReturn(text=f"Error: {where}unknown browser action {action!r}; actions: {', '.join(known)}",
                              is_error=True)
    if len(steps) == 1:
        return _one(steps[0][0], steps[0][1], args, session)
    from openprogram.runtime.conversation.run_control import check_cancelled
    with browser.tabs.batch():
        return _steps(steps, args, session, check_cancelled)


def _steps(steps: list[tuple[str, dict]], args: dict, session: str, check_cancelled) -> ToolReturn:
    """Several actions in order; the tabs they touch stay held by this list until it ends."""
    texts, results, images = [], [], []
    for number, (action, step) in enumerate(steps, 1):
        check_cancelled()
        result = _one(action, step, args, session)
        images.extend(result.images)
        results.append(result.json_data)
        texts.append(f"[{number}] {action}: {result.text or ''}")
        if result.is_error:
            texts.append(f"step {number} failed; the steps after it did not run")
            return ToolReturn(text="\n".join(texts), json_data=results, images=images, is_error=True)
    return ToolReturn(text="\n".join(texts), json_data=results, images=images)


__all__ = ["NAME", "READS", "actions", "approval", "available", "evaluates", "guide", "open_target", "render", "run",
           "user_browser"]
