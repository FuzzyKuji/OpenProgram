"""The Playwright engine: automate a Chromium Page through verbs.

The ``web_use`` page controller drives Pages through ``execute``; nothing
registers it as a tool.

Verbs:

    open       launch browser + context; returns a session id
    navigate   <session_id, url>                       load a URL
    click      <session_id, selector>                  click an element
    type       <session_id, selector, text, [submit]>  fill an input
    extract    <session_id, [selector]>                return readable text
    screenshot <session_id, path>                      save PNG, return path
    close      <session_id>                            tear down

Sessions are process-local — ``open`` returns an id the agent passes
to subsequent calls. Each session owns one Playwright browser + one
page; multi-page workflows can open multiple sessions.

Playwright is an optional dependency. Without it, ``check_playwright``
returns False and the first call emits a clear install hint.

This module is the public face: SPEC, the shared per-process session
table (``_sessions``), the small filesystem / introspection helpers,
and the verb dispatch (``execute``). All verb implementations live in
``engine/_actions/`` and reach back to this module
for state via ``from .. import browser as _b``.
"""

from __future__ import annotations

from typing import Any

from openprogram.programs._authoring.helpers import read_string_param
import logging

_log = logging.getLogger(__name__)


NAME = "playwright_browser"

DESCRIPTION = (
    "Drive a browser through Playwright (Chromium / patchright / camoufox). "
    "CSS-selector + DOM control, 28 verbs (open / navigate / click / type / "
    "extract / screenshot / upload / wait / eval / html / hover / select / "
    "press / accessibility / screenshot_b64 / tabs / new_tab / switch_tab / "
    "download / cookies / save_login / frames / frame_eval / console / "
    "block / viewport / list / close). "
    "Default engine is `app` and only controls visible web tabs inside the "
    "OpenProgram desktop app. Explicit `auto` mode may use a sidecar copy of "
    "the user's Chrome profile and therefore requires approval. Complete "
    "releases include the default Playwright browser."
)


SPEC: dict[str, Any] = {
    "name": NAME,
    "description": DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "open", "navigate", "click", "type",
                    "extract", "screenshot", "close", "list",
                    "upload", "wait", "eval", "html",
                    "hover", "select", "press",
                    "accessibility", "screenshot_b64",
                    "tabs", "new_tab", "switch_tab",
                    "download", "cookies",
                    "save_login",
                    "frame_eval", "frames",
                    "console", "block",
                    "viewport",
                ],
                "description": "What to do.",
            },
            "session_id": {
                "type": "string",
                "description": "Session id returned by ``open``. Required for every action except ``open`` / ``list``.",
            },
            "url": {
                "type": "string",
                "description": "URL to navigate to. Required for ``navigate``.",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector. Required for ``click`` / ``type`` / ``upload``, optional for ``extract`` / ``html`` / ``wait``.",
            },
            "text": {
                "type": "string",
                "description": "Text to type. Required for ``type``.",
            },
            "submit": {
                "type": "boolean",
                "description": "When typing, press Enter afterwards (default false).",
            },
            "path": {
                "type": "string",
                "description": "For ``screenshot``: output PNG path. For ``upload``: file path on disk to attach to the matching <input type=file>.",
            },
            "code": {
                "type": "string",
                "description": "JavaScript expression for ``eval``. Result is JSON-stringified, capped at 2KB.",
            },
            "state": {
                "type": "string",
                "enum": ["attached", "detached", "visible", "hidden", "load", "domcontentloaded", "networkidle"],
                "description": "For ``wait``: with a selector, the element state to wait for (visible/hidden/attached/detached). Without a selector, a page load state (load/domcontentloaded/networkidle). Default 'visible' / 'networkidle'.",
            },
            "key": {
                "type": "string",
                "description": "For ``press``: keyboard key (e.g. 'Enter', 'Escape', 'Control+A', 'ArrowDown').",
            },
            "value": {
                "type": "string",
                "description": "For ``select``: option value to select inside the <select> at `selector`. Pass a list-as-string for multi-select if the element supports it.",
            },
            "tab_index": {
                "type": "integer",
                "description": "For ``switch_tab``: zero-based index returned by ``tabs`` / ``new_tab``.",
            },
            "name": {
                "type": "string",
                "description": "For ``save_login``: optional host or label to file the saved state under. Defaults to the host of the URL the session was opened with.",
            },
            "storage_state": {
                "type": "string",
                "description": "For ``open``: path to a saved storage_state JSON. If omitted but ``url`` is given, the tool auto-loads ``~/.openprogram/browser-states/<host>.json`` if it exists.",
            },
            "width": {
                "type": "integer",
                "description": "For ``viewport``: pixel width.",
            },
            "height": {
                "type": "integer",
                "description": "For ``viewport``: pixel height.",
            },
            "headless": {
                "type": "boolean",
                "description": "For ``open``: start browser in headless mode (default true).",
            },
            "stealth": {
                "type": "boolean",
                "description": "For ``open``: apply anti-bot patches (navigator.webdriver, chrome runtime, plugins, WebGL vendor) so Cloudflare/Distil-style detection passes more often (default true).",
            },
            "engine": {
                "type": "string",
                "enum": ["auto", "app", "chromium", "patchright", "camoufox"],
                "description": "For ``open``: which browser backend to use. Default 'app' controls only visible web tabs inside the OpenProgram desktop app and errors if the app is not running. Explicit 'auto' first prefers the desktop app, then may connect to a sidecar copy of the user's Chrome profile; this requires approval. Use 'chromium' for an isolated stock Playwright browser, 'patchright' for a stealth Chromium fork, or 'camoufox' for stealth Firefox.",
            },
            "timeout_ms": {
                "type": "integer",
                "description": "Per-action timeout in ms (default 30000).",
            },
        },
        "required": ["action"],
    },
}


# ---------------------------------------------------------------------------
# Process-local state. Shared with everything under ``_actions/`` via
# attribute reach (``_b._sessions``); intentionally not persisted.
# ---------------------------------------------------------------------------

_sessions: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Filesystem + introspection helpers (kept here because both the action
# modules and external code import them off ``browser``).
# ---------------------------------------------------------------------------

def _state_dir() -> str:
    """Where saved login states live — one JSON per host. Created lazily."""
    from openprogram.state.paths import get_state_dir

    p = get_state_dir() / "browser-states"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def _state_path_for(name_or_url: str) -> str:
    """Map a host or arbitrary name to the on-disk JSON path."""
    import os
    from urllib.parse import urlparse
    name = name_or_url
    if "://" in name_or_url:
        try:
            name = urlparse(name_or_url).hostname or name_or_url
        except ValueError:
            # Malformed URL (bad port, bad IPv6): the raw string names the state file.
            _log.debug("state name URL unparsable: %s", name_or_url, exc_info=True)
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in name)
    return os.path.join(_state_dir(), f"{safe}.json")


def _has_saved_login(name_or_url: str) -> bool:
    import os
    return os.path.isfile(_state_path_for(name_or_url))


def check_playwright() -> bool:
    """Gate the tool's visibility by whether Playwright is importable."""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _install_hint() -> str:
    return (
        "Error: the bundled Playwright browser is unavailable. "
        "Reinstall the complete OpenProgram release."
    )


def _require_session(session_id: str) -> dict[str, Any] | str:
    if not session_id:
        return "Error: `session_id` is required."
    sess = _sessions.get(session_id)
    if sess is None:
        return f"Error: no browser session with id {session_id!r}."
    return sess


def _current_page(sess: dict[str, Any]):
    """Return the active page for a session (multi-tab support)."""
    pages = sess.get("pages") or [sess.get("page")]
    idx = sess.get("active", 0)
    return pages[idx] if 0 <= idx < len(pages) else pages[0]


# ---------------------------------------------------------------------------
# Verb dispatcher.  Each branch routes into ``_actions/*`` which holds the
# real implementation.  Keeping this in one place gives a fast index of
# every supported verb + which module to look in.
# ---------------------------------------------------------------------------

def execute(
    action: str | None = None,
    session_id: str | None = None,
    url: str | None = None,
    selector: str | None = None,
    text: str | None = None,
    submit: bool = False,
    path: str | None = None,
    code: str | None = None,
    state: str | None = None,
    key: str | None = None,
    value: str | None = None,
    tab_index: int | None = None,
    headless: bool = True,
    stealth: bool = True,
    engine: str = "app",
    storage_state: str | None = None,
    name: str | None = None,
    width: int | None = None,
    height: int | None = None,
    timeout_ms: int = 30_000,
    **kw: Any,
) -> str:
    action = action or read_string_param(kw, "action", "op")
    if not action:
        return "Error: `action` is required."
    action = action.lower()

    session_id = session_id or read_string_param(kw, "session_id", "sid")
    url = url or read_string_param(kw, "url")
    selector = selector or read_string_param(kw, "selector", "sel")
    text = text if text is not None else read_string_param(kw, "text", "value")
    path = path or read_string_param(kw, "path", "file")
    code = code if code is not None else read_string_param(kw, "code", "js", "expression")
    state = state or read_string_param(kw, "state")
    key = key or read_string_param(kw, "key", "shortcut")
    value = value if value is not None else read_string_param(kw, "value", "option")
    if tab_index is None:
        tab_raw = read_string_param(kw, "tab_index", "index", "tab")
        if tab_raw is not None:
            try:
                tab_index = int(tab_raw)
            except (TypeError, ValueError):
                tab_index = None

    # Lazy-import the action modules so the per-process cost is paid
    # only on first use of the tool. Each module is tiny (one topic).
    from openprogram.programs.applications.browser.engine._actions import (
        open_action,
        interact,
        read as read_mod,
        console as console_mod,
        tabs as tabs_mod,
        lifecycle,
    )

    if action == "open":
        eng = engine or read_string_param(kw, "engine", "backend") or "app"
        ss = storage_state or read_string_param(kw, "storage_state", "state")
        cdp = read_string_param(kw, "cdp_url", "cdp")
        binding_id = read_string_param(kw, "binding_id")
        return open_action._open(
            headless=headless,
            timeout_ms=timeout_ms,
            stealth=stealth,
            engine=eng,
            url=url,
            storage_state=ss,
            cdp_url=cdp,
            binding_id=binding_id,
            expected_page_revision=int(kw.get("expected_page_revision") or 0),
            expected_access_revision=int(kw.get("expected_access_revision") or 0),
            expected_geometry_revision=int(kw.get("expected_geometry_revision") or 0),
        )
    if action == "save_login":
        nm = name or read_string_param(kw, "name", "host", "label")
        return lifecycle._save_login(session_id or "", nm)
    if action == "frames":
        return console_mod._frames(session_id or "")
    if action == "frame_eval":
        return console_mod._frame_eval(session_id or "", selector or "", code or "")
    if action == "console":
        return console_mod._console(session_id or "")
    if action == "block":
        return console_mod._block(session_id or "", selector or "")
    if action == "viewport":
        w = width if width is not None else int(read_string_param(kw, "width") or 0)
        h = height if height is not None else int(read_string_param(kw, "height") or 0)
        return tabs_mod._viewport(session_id or "", w, h)
    if action == "navigate":
        return interact._navigate(session_id or "", url or "")
    if action == "click":
        return interact._click(session_id or "", selector or "")
    if action == "type":
        return interact._type(session_id or "", selector or "", text or "", submit=submit)
    if action == "extract":
        return read_mod._extract(session_id or "", selector or None)
    if action == "screenshot":
        return read_mod._screenshot(session_id or "", path or "")
    if action == "upload":
        return interact._upload(session_id or "", selector or "", path or "")
    if action == "wait":
        return interact._wait(session_id or "", selector or None, state, timeout_ms)
    if action == "eval":
        return interact._eval_js(session_id or "", code or "")
    if action == "html":
        return read_mod._html(session_id or "", selector or None)
    if action == "hover":
        return interact._hover(session_id or "", selector or "")
    if action == "select":
        return interact._select_option(session_id or "", selector or "", value or "")
    if action == "press":
        return interact._press(session_id or "", key or "")
    if action == "accessibility":
        return read_mod._accessibility(session_id or "", selector or None)
    if action == "screenshot_b64":
        return read_mod._screenshot_b64(session_id or "", selector or None)
    if action == "tabs":
        return tabs_mod._tabs(session_id or "")
    if action == "new_tab":
        return tabs_mod._new_tab(session_id or "")
    if action == "switch_tab":
        return tabs_mod._switch_tab(session_id or "", tab_index or 0)
    if action == "download":
        return tabs_mod._download(session_id or "", selector or "", path or "", timeout_ms)
    if action == "cookies":
        return read_mod._cookies(session_id or "")
    if action == "close":
        return lifecycle._close(session_id or "")
    if action == "list":
        return lifecycle._list()
    return f"Error: unknown action {action!r}."



__all__ = ["NAME", "SPEC", "DESCRIPTION", "execute", "check_playwright"]
