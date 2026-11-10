"""The user's own Chrome or Edge, with the built-in browser's actions.

As in Codex, a browser is chosen first and every action afterwards is the
same whichever browser it is: here the ``browser`` target's actions
(``list_pages``, ``observe``, ``click``, ``type`` …) reach the user's
Chrome or Edge through Playwright MCP in extension mode. The server opens a
relay and the Playwright Extension in that browser connects to it, so the
user's real tabs are driven with their sign-ins. Element actions are
translated by the Playwright MCP backend's own ``_action_call``, the same
translation the built-in browser's ``playwright_mcp`` backend uses.
"""
from __future__ import annotations

import base64
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Mapping

from .web_use import page_actions as pa
import logging

_log = logging.getLogger(__name__)

BROWSERS = {"chrome": "chrome", "edge": "msedge"}
NAMES = {"chrome": "Chrome", "edge": "Edge"}
EXTENSION_ID = "mmlmfjhmonkocbjadbfplnigmagldckm"
# Edge installs it from the Chrome Web Store as well.
STORE_URL = f"https://chromewebstore.google.com/detail/playwright-extension/{EXTENSION_ID}"
# Connecting waits for the user to pick a tab in the extension.
_TIMEOUT = 120.0
_VERIFY_ASSERTIONS = ("text_contains", "text_not_contains", "url_contains", "title_contains",
                      "element_present", "file_selected")

_lock = threading.Lock()
_clients: dict[tuple[str, str], Any] = {}
_translator = None

# Where each browser keeps its profiles (macOS, Windows, Linux).
_DATA_DIRS = {
    "darwin": {"chrome": "Library/Application Support/Google/Chrome",
               "edge": "Library/Application Support/Microsoft Edge"},
    "win32": {"chrome": "Google/Chrome/User Data", "edge": "Microsoft/Edge/User Data"},
    "linux": {"chrome": ".config/google-chrome", "edge": ".config/microsoft-edge"},
}


def _data_dir(browser: str) -> Path:
    import os
    import sys
    platform = "win32" if sys.platform.startswith("win") else "darwin" if sys.platform == "darwin" else "linux"
    relative = _DATA_DIRS[platform][browser]
    if platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / relative
    return Path.home() / relative


def installed(browser: str) -> bool:
    """Whether the Playwright Extension is installed in one of ``browser``'s profiles.

    A store install unpacks into ``<profile>/Extensions/<id>``, which is what
    Playwright MCP looks for too. Only files are read; the browser is not touched.
    """
    root = _data_dir(browser)
    try:
        profiles = [entry for entry in root.iterdir() if entry.is_dir()]
    except OSError:
        return False
    return any((profile / "Extensions" / EXTENSION_ID).is_dir() for profile in profiles)


def installed_browsers() -> tuple[str, ...]:
    """The user's browsers this module can reach: those with the extension installed."""
    return tuple(browser for browser in BROWSERS if installed(browser))


def browser_of(args: Mapping[str, Any]) -> str:
    """``chrome`` or ``edge`` when the call names the user's browser, else ``""`` (built-in)."""
    value = str(args.get("browser") or "").strip().lower()
    return {"msedge": "edge", "google chrome": "chrome", "microsoft edge": "edge"}.get(value, value) \
        if value not in {"", "app", "builtin", "built-in", "iab", "openprogram"} else ""


def token() -> str:
    try:
        from openprogram.state.config import read_config
        value = (read_config().get("computer_use") or {}).get("chrome_extension_token")
    except Exception:
        return ""
    return str(value or "").strip()


def _command(browser: str) -> list[str]:
    from .web_use.mcp_backends import _NPX_PREFIX, _PLAYWRIGHT_MCP_VERSION

    output = Path(tempfile.gettempdir()) / "openprogram-extension-browser"
    return [*_NPX_PREFIX, f"@playwright/mcp@{_PLAYWRIGHT_MCP_VERSION}", "--extension",
            "--browser", BROWSERS[browser], "--caps", "vision", "--output-dir", str(output)]


def _client(session: str, browser: str):
    from .web_use.mcp_backends import _SyncMCPClient

    key = (session, browser)
    with _lock:
        client = _clients.get(key)
        if client is not None and client.is_alive():
            return client
        _clients.pop(key, None)
    env = {"PLAYWRIGHT_MCP_EXTENSION_TOKEN": token()} if token() else {}
    background_tabs = Path(__file__).parent / "web_use" / "playwright_background_tabs.cjs"
    env["NODE_OPTIONS"] = f'--require "{background_tabs}"'
    client = _SyncMCPClient(_command(browser), timeout=_TIMEOUT, env=env)
    with _lock:
        _clients[key] = client
    return client


def connected(session: str, browser: str) -> bool:
    """Whether this conversation already holds a connection to ``browser``."""
    with _lock:
        client = _clients.get((session, browser))
    return client is not None and client.is_alive()


def close_session(session: str) -> None:
    with _lock:
        stale = [key for key in _clients if key[0] == session]
        clients = [_clients.pop(key) for key in stale]
    for client in clients:
        try:
            client.close()
        except Exception:
            # Teardown: the client's socket or page may already be gone.
            _log.debug("browser extension client close failed session=%s", session, exc_info=True)


def _action_call(arguments: Mapping[str, Any]):
    """The Playwright MCP call for one element action, as the built-in browser's backend makes it."""
    global _translator
    if _translator is None:
        from .web_use.mcp_backends import OfficialMCPPageBackend
        _translator = OfficialMCPPageBackend("playwright_mcp", lambda: None)
    return _translator._action_call(None, arguments)


def _text(result: Any) -> str:
    return "\n".join(str(getattr(item, "text", "")) for item in getattr(result, "content", None) or []
                     if getattr(item, "type", "") == "text").strip()


def _images(result: Any) -> list[bytes]:
    return [base64.b64decode(item.data) for item in getattr(result, "content", None) or []
            if getattr(item, "type", "") == "image" and getattr(item, "data", None)]


def _failed(result: Any) -> bool:
    return bool(getattr(result, "isError", False))


class Unavailable(RuntimeError):
    pass


class ExtensionBrowser:
    """One conversation's connection to the user's Chrome or Edge."""

    def __init__(self, session: str, browser: str) -> None:
        if browser not in BROWSERS:
            raise ValueError(f"browser is the built-in browser (omit it), chrome or edge; not {browser!r}")
        self.browser = browser
        try:
            self.client = _client(session, browser)
        except Exception as exc:
            raise Unavailable(
                f"could not reach your {NAMES[browser]} ({exc}). It needs Node.js (npx) and the Playwright "
                f"Extension installed in {NAMES[browser]}: {STORE_URL}") from exc

    def _call(self, name: str, arguments: dict[str, Any]) -> tuple[str, list[bytes], bool]:
        try:
            result = self.client.call(name, arguments)
        except Exception as exc:
            return (f"{exc}. If {NAMES[self.browser]} did not connect, check that the Playwright Extension is "
                    f"installed ({STORE_URL}) and a tab was shared.", [], True)
        return _text(result), _images(result), _failed(result)

    def _evaluate(self, function: str, ref: str = "") -> tuple[str, bool]:
        text, _, failed = self._call("browser_evaluate", {**({"target": ref} if ref else {}), "function": function})
        return text, failed

    def _hidden(self) -> bool:
        text, failed = self._evaluate("() => document.visibilityState")
        return not failed and "hidden" in _evaluated(text)

    def run(self, command: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """One ``browser`` command (``list_pages``, ``observe``, ``verify``, ``close``) or act action."""
        args = dict(arguments)
        if command == "list_pages":
            return self._result(*self._call("browser_tabs", {"action": "list"}))
        if command == "observe":
            return self._observe(args)
        if command == "close":
            return self._result(*self._call("browser_tabs", {"action": "close"}))
        if command == "verify":
            return self._verify(args)
        return self._act(str(args.pop("action", command) or ""), args)

    def _result(self, text: str, images: list[bytes], failed: bool, **extra: Any) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": not failed, "browser": self.browser, "result": text, **extra}
        if failed:
            out["observe_required"] = True
        if images:
            out["_images"] = images
        return out

    def _observe(self, args: dict[str, Any]) -> dict[str, Any]:
        if args.get("url"):
            # The extension's "connected" page has done its job: it becomes the tab the Agent works in.
            listed, _, unlisted = self._call("browser_tabs", {"action": "list"})
            on_connect_page = not unlisted and re.search(r"\(current\)[^\n]*/connect\.html", listed)
            text, images, failed = (self._call("browser_navigate", {"url": str(args["url"])}) if on_connect_page
                                    else self._call("browser_tabs", {"action": "new", "url": str(args["url"])}))
            if failed:
                return self._result(text, images, failed)
        elif args.get("page") not in (None, ""):
            try:
                index = int(args["page"])
            except (TypeError, ValueError):
                return {"ok": False, "reason_code": "invalid_arguments",
                        "message": "page is a tab index from list_pages"}
            text, images, failed = self._call("browser_tabs", {"action": "select", "index": index})
            if failed:
                listed, _, unlisted = self._call("browser_tabs", {"action": "list"})
                return self._result(text if unlisted else f"{text}\nThe tabs open now:\n{listed}", images, failed)
        return self._result(*self._call("browser_snapshot", {}))

    def _act(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        ref = str(args.get("ref") or "").lstrip("@")
        if action == "screenshot":
            return self._result(*self._call("browser_take_screenshot", {"type": "png"}))
        if action == "wait":
            seconds = max(0.0, min(10.0, float(args.get("amount") or args.get("duration") or 1)))
            return self._result(*self._call("browser_wait_for", {"time": seconds}))
        if action == "upload":
            path = str(args.get("path") or "")
            if not path:
                return {"ok": False, "reason_code": "invalid_arguments", "message": "upload needs path"}
            if args.get("field") is not None:
                return {"ok": False, "reason_code": "invalid_arguments",
                        "message": "upload(field=n) works in the built-in browser; here pass the upload button's ref"}
            # Without ref it answers the file chooser the last click opened.
            if ref:
                text, images, failed = self._call("browser_click", {"target": ref})
                if failed:
                    return self._result(text, images, failed)
            return self._result(*self._call("browser_file_upload", {"paths": [str(Path(path).expanduser())]}))
        if action == pa.EVALUATE_ACTION:
            try:
                source = pa.evaluate_source(args)
            except pa.ActionError as exc:
                return exc.result()
            return self._result(*self._call("browser_evaluate", {"function": source}))
        if action == "console_messages":
            return self._result(*self._call("browser_console_messages", {
                "level": "error" if args.get("only_errors") else "info"}))
        if action == "network_requests":
            return self._result(*self._call("browser_network_requests", {
                **({"filter": str(args["pattern"])} if args.get("pattern") else {})}))
        try:
            if ref and action in ("click", "hover") and self._hidden():
                # Chrome stops drawing a tab nobody is looking at, and a normal click waits for its frames.
                # The events are sent in the page, so the tab can stay behind whatever the user is doing.
                if action == "hover":
                    return self._result(*self._call("browser_evaluate", {"target": ref, "function": pa.HOVER_SCRIPT}))
                click = pa.click_options(args)
                script = pa.bound_call(pa.POINTER_SCRIPT, {
                    "button": click["button"], "count": click["count"], "flags": click["flags"]})
                return self._result(*self._call("browser_evaluate", {"target": ref, "function": script}))
            call = _action_call({**args, "action": action})
        except pa.ActionError as exc:
            return exc.result()
        if call is None:
            return {"ok": False, "reason_code": "unsupported_action",
                    "message": f"{action} is not available in {NAMES[self.browser]}"}
        return self._result(*self._call(*call))

    def _verify(self, args: dict[str, Any]) -> dict[str, Any]:
        assertion = str(args.get("assertion") or "")
        value = str(args.get("value") or "")
        ref = str(args.get("ref") or "").lstrip("@")
        if assertion not in _VERIFY_ASSERTIONS:
            return {"ok": False, "reason_code": "invalid_arguments",
                    "message": f"assertion is one of {', '.join(_VERIFY_ASSERTIONS)}"}
        if assertion in {"element_present", "file_selected"}:
            if not ref:
                return {"ok": False, "reason_code": "invalid_arguments", "message": f"{assertion} needs ref"}
            script = ("(element) => !!element" if assertion == "element_present"
                      else "(element) => !!(element.files && element.files.length)")
            text, failed = self._evaluate(script, ref)
            passed = not failed and "true" in text
        else:
            source = {"url_contains": "() => location.href", "title_contains": "() => document.title"}.get(
                assertion, "() => document.body ? document.body.innerText : ''")
            text, failed = self._evaluate(source)
            if failed:
                return self._result(text, [], True)
            found = value.lower() in _evaluated(text).lower()
            passed = not found if assertion == "text_not_contains" else found
        return {"ok": True, "browser": self.browser, "assertion": assertion, "passed": bool(passed)}


def _evaluated(text: str) -> str:
    """The value part of a browser_evaluate reply, without its markdown sections."""
    match = re.search(r"### Result\s*\n(.*?)(?:\n### |\Z)", text, re.S)
    return (match.group(1) if match else text).strip()


__all__ = ["BROWSERS", "ExtensionBrowser", "NAMES", "STORE_URL", "Unavailable", "browser_of", "close_session", "connected",
           "token"]
