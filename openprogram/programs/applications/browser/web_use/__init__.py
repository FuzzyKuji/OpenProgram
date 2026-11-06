"""web_use: list, observe and control exact Pages of OpenProgram's built-in browser.

This package is the namespace its modules share (``state`` in each of
them): the page scripts, the planner-tool parameters, the reason sets and
the ``web_use`` entry itself.
"""

from __future__ import annotations

# The submodules (controller, execute, page_recovery, prompts) read their
# dependencies as ``state.<name>`` from this package, so imports that only
# they read carry ``noqa: F401``.
import asyncio
import base64  # noqa: F401
from concurrent.futures import ThreadPoolExecutor  # noqa: F401
from contextlib import suppress  # noqa: F401
from contextvars import copy_context  # noqa: F401
import json  # noqa: F401
import math  # noqa: F401
import re  # noqa: F401
import uuid  # noqa: F401
from typing import Any, Mapping  # noqa: F401
from urllib.parse import urlparse

from openprogram.host.cancellation import CancelledError
from openprogram.programs import ToolReturn
from openprogram.programs._host.runtime import function  # noqa: F401
from openprogram.models.providers.utils.errors import ExecInterrupt
from openprogram.programs.applications.browser.contract import (  # noqa: F401
    normalize_web_use_arguments,
)


_INTERACTIVE_SELECTOR = (
    "a[href],button,input,textarea,select,summary,[role=button],"
    "[role=link],[role=checkbox],[role=radio],[role=tab],[role=menuitem],"
    "[contenteditable=true],[tabindex]:not([tabindex='-1'])"
)
_OBSERVE_SCRIPT = (
    r"""
() => {
  const selector = %r;
  const nodes = Array.from(document.querySelectorAll(selector));
  const visible = (el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== "hidden" && style.display !== "none"
      && rect.width > 0 && rect.height > 0;
  };
  const nameOf = (el) => (
    el.getAttribute("aria-label") || el.getAttribute("title")
    || el.getAttribute("placeholder") || el.innerText
    || (el.matches("input[type=password]") ? "" : el.value) || ""
  ).replace(/\s+/g, " ").trim().slice(0, 240);
  return {
    text: document.body?.innerText || "",
    viewport_width: window.innerWidth,
    viewport_height: window.innerHeight,
    navigation_time_origin: performance.timeOrigin,
    scroll_x: window.scrollX,
    scroll_y: window.scrollY,
    device_scale_factor: window.devicePixelRatio || 1,
    elements: nodes.map((el, dom_index) => ({
      dom_index,
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute("role") || (
        el.tagName === "A" ? "link" :
        el.tagName === "BUTTON" ? "button" :
        ["INPUT", "TEXTAREA"].includes(el.tagName) ? "textbox" :
        el.tagName.toLowerCase()
      ),
      name: nameOf(el),
      disabled: Boolean(el.disabled || el.getAttribute("aria-disabled") === "true"),
    })).filter((item) => visible(nodes[item.dom_index])).slice(0, 120),
  };
}
"""
    % _INTERACTIVE_SELECTOR
)

_REF_SNAPSHOT_SCRIPT = r"""
(el) => {
  const style = getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  const labelledBy = (el.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean)
    .map(id => el.getRootNode().getElementById?.(id)?.textContent || "").join(" ").trim();
  const nativeLabelIdentity = (labelledBy || el.getAttribute("aria-label")
    || Array.from(el.labels || []).map(node => node.innerText || node.textContent || "").join(" ")
    || "").replace(/\s+/g, " ").trim();
  const label = nativeLabelIdentity.slice(0, 240);
  const field = {label};
  if (el.tagName === "INPUT") field.input_type = el.type;
  if (el.matches("input[type=file]")) {
    field.files = Array.from(el.files || []).slice(0, 20).map(file => file.name);
  }
  const editable = el.tagName === "TEXTAREA" || el.isContentEditable || (
    el.tagName === "INPUT" && !["button", "submit", "reset", "image", "checkbox", "radio", "file", "hidden"].includes(el.type)
  );
  if (editable) {
    if (el.matches("input[type=password]")) {
      field.value_redacted = true;
    } else {
      field.value = el.isContentEditable ? el.innerText : el.value;
      field.value_source = el.isContentEditable ? "inner_text" : "dom_value";
      field.value_truncated = false;
      field.value_redacted = false;
    }
    const describe = node => ({tag: node.tagName.toLowerCase(), id: node.id || "",
      classes: Array.from(node.classList).slice(0, 6), classes_truncated: node.classList.length > 6});
    const isEditable = node => node.isContentEditable || ["INPUT", "TEXTAREA"].includes(node.tagName);
    const insideEditableValue = node => {
      for (let ancestor=node; ancestor; ancestor=ancestor.parentElement) {
        if (isEditable(ancestor)) return true;
      }
      return false;
    };
    const isVisible = node => {const style=getComputedStyle(node), rect=node.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;};
    const context = {source: "dom_structure", diagnostic_only: true, truncated: false,
      element: describe(el), ancestors: []};
    for (let parent=el.parentElement; parent && context.ancestors.length < 4; parent=parent.parentElement) {
      const ancestor = {...describe(parent), editable_count: 0, editable_count_truncated: false,
        direct_text: insideEditableValue(parent) ? "" : Array.from(parent.childNodes).filter(node => node.nodeType === Node.TEXT_NODE)
          .map(node => node.textContent).join(" ").replace(/\s+/g, " ").trim(), text_nodes: []};
      for (const node of parent.querySelectorAll("input,textarea,[contenteditable]")) {
        if (isEditable(node) && isVisible(node)) ancestor.editable_count++;
        if (ancestor.editable_count > 120) {ancestor.editable_count_truncated=true;break;}
      }
      let scanned=0;
      for (const node of parent.querySelectorAll("*")) {
        if (++scanned > 120) {context.truncated=true;break;}
        if (node.childElementCount || insideEditableValue(node) || !isVisible(node)) continue;
        const text=(node.textContent || "").replace(/\s+/g," ").trim();
        if (!text) continue;
        if (ancestor.text_nodes.length === 6) {context.truncated=true;break;}
        ancestor.text_nodes.push({...describe(node), text, source:"visible_text_leaf"});
      }
      context.ancestors.push(ancestor);
    }
    if (!el.matches("input[type=password]")) {
      let depth = 0;
      for (let parent=el.parentElement; parent && ++depth <= 12; parent=parent.parentElement) {
        const walker = document.createTreeWalker(parent, NodeFilter.SHOW_ELEMENT);
        let scanned=0, editableCount=0, labelCount=0, labelNode=null, complete=true;
        for (let node=walker.nextNode(); node; node=walker.nextNode()) {
          if (++scanned > 120) {complete=false;break;}
          if (!isVisible(node)) continue;
          if (node.matches("input,textarea,[contenteditable]") && isEditable(node)) editableCount++;
          if (node.tagName === "LABEL" && !insideEditableValue(node)) {
            labelCount++;
            labelNode=node;
          }
        }
        if (!complete) break;
        if (!labelCount) continue;
        if (editableCount === 1 && labelCount === 1 && !labelNode.childElementCount) {
          const text=(labelNode.innerText || "").replace(/\s+/g," ").trim();
          if (text) context.label_binding = {source:"visible_container_label", label:text,
            ancestor_depth:depth, editable_count:editableCount, label_count:labelCount,
            truncated:false, redacted:false};
        }
        break;
      }
    }
    field.field_context = context;
  }
  const name = (
    el.getAttribute("aria-label") || el.getAttribute("title")
    || el.getAttribute("placeholder") || el.innerText
    || (el.matches("input[type=password]") ? "" : el.value) || ""
  ).replace(/\s+/g, " ").trim().slice(0, 240);
  return {
    connected: el.isConnected,
    visible: style.visibility !== "hidden" && style.display !== "none"
      && rect.width > 0 && rect.height > 0,
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute("role") || (
      el.tagName === "A" ? "link" :
      el.tagName === "BUTTON" ? "button" :
      ["INPUT", "TEXTAREA"].includes(el.tagName) ? "textbox" :
      el.tagName.toLowerCase()
    ),
    name,
    native_label_identity: nativeLabelIdentity,
    ...field,
    disabled: Boolean(el.disabled || el.getAttribute("aria-disabled") === "true"),
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
  };
}
"""

_VIEWPORT_SCRIPT = """
() => ({
  viewport_width: window.innerWidth,
  viewport_height: window.innerHeight,
  navigation_time_origin: performance.timeOrigin,
  device_scale_factor: window.devicePixelRatio || 1,
  scroll_x: window.scrollX,
  scroll_y: window.scrollY,
})
"""

_AGENT_CURSOR_SCRIPT = r"""
armed => {
  const key = "__openprogramAgentCursor";
  let state = globalThis[key];
  if (!state || state.version !== 2) {
    state = {version: 2, armed: false, show: null};
    try {
      Object.defineProperty(globalThis, key, {
        value: state, configurable: true,
      });
    } catch (_) {
      return false;
    }
    state.show = (clientX, clientY) => {
      document.querySelectorAll("[data-openprogram-agent-cursor]")
        .forEach(node => node.remove());

      const host = document.createElement("div");
      host.setAttribute("data-openprogram-agent-cursor", "");
      host.setAttribute("aria-hidden", "true");
      Object.assign(host.style, {
        position: "fixed",
        left: `${clientX}px`,
        top: `${clientY}px`,
        width: "0",
        height: "0",
        zIndex: "2147483647",
        pointerEvents: "none",
      });

      const ring = document.createElement("span");
      Object.assign(ring.style, {
        position: "absolute",
        left: "-15px",
        top: "-15px",
        width: "30px",
        height: "30px",
        border: "2px solid rgba(112, 92, 255, .9)",
        borderRadius: "50%",
        boxSizing: "border-box",
      });

      const cursor = document.createElement("span");
      Object.assign(cursor.style, {
        position: "absolute",
        left: "-2px",
        top: "-2px",
        width: "24px",
        height: "30px",
        filter: "drop-shadow(0 2px 3px rgba(0, 0, 0, .35))",
      });
      cursor.innerHTML = '<svg viewBox="0 0 24 30" width="24" height="30" '
        + 'xmlns="http://www.w3.org/2000/svg"><path d="M2 2v21l5.6-5.2 '
        + '3.8 9.1 4.2-1.8-3.8-9.1H20L2 2Z" fill="#705cff" '
        + 'stroke="white" stroke-width="2" stroke-linejoin="round"/></svg>';
      host.append(ring, cursor);
      (document.documentElement || document.body)?.append(host);

      const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (!reduced) {
        ring.animate([
          {transform: "scale(.35)", opacity: 1},
          {transform: "scale(1.35)", opacity: 0},
        ], {duration: 650, easing: "cubic-bezier(.2,.8,.2,1)"});
        cursor.animate([
          {transform: "translate(-2px,-2px)", opacity: 1},
          {transform: "translate(0,0)", opacity: 1, offset: .65},
          {transform: "translate(0,0)", opacity: 0},
        ], {duration: 900, easing: "ease-out"});
      }
      setTimeout(() => host.remove(), reduced ? 240 : 900);
    };
    addEventListener("pointerdown", event => {
      if (!state.armed || !event.isTrusted) return;
      state.armed = false;
      state.show(event.clientX, event.clientY);
    }, true);
  }
  state.armed = Boolean(armed);
  return true;
}
"""

_BACKGROUND_REF_CLICK_SCRIPT = r"""
element => {
  const cursor = globalThis.__openprogramAgentCursor;
  if (cursor?.armed && typeof cursor.show === "function") {
    const rect = element.getBoundingClientRect();
    cursor.armed = false;
    cursor.show(rect.left + rect.width / 2, rect.top + rect.height / 2);
  }
  if (typeof element.click === "function") {
    element.click();
    return;
  }
  element.dispatchEvent(new MouseEvent("click", {
    bubbles: true,
    cancelable: true,
    view: window,
  }));
}
"""

_CAPTURE_HANDLES_SCRIPT = (
    r"""
() => {
  const nodes = Array.from(document.querySelectorAll(%r));
  const visible = (el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== "hidden" && style.display !== "none"
      && rect.width > 0 && rect.height > 0;
  };
  return nodes.filter(visible).slice(0, 120);
}
"""
    % _INTERACTIVE_SELECTOR
)


_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "observe",
                "screenshot",
                "navigate",
                "click",
                "type",
                "press",
                "scroll",
                "hover",
                "select",
                "upload",
                "stop",
                "wait",
                "verify",
            ],
        },
        "expected_frame_id": {
            "type": "string",
            "description": "Latest frame_id returned by observe.",
        },
        "ref": {
            "type": "string",
            "description": "Element ref returned by observe, for example e3.",
        },
        "x": {
            "type": "number",
            "description": "Viewport CSS x coordinate; click only after screenshot.",
        },
        "y": {
            "type": "number",
            "description": "Viewport CSS y coordinate; click only after screenshot.",
        },
        "url": {"type": "string"},
        "text": {"type": "string", "description": "Text to type, or blocker explanation for stop. Never the expected verification value."},
        "path": {"type": "string", "description": "For upload: user-approved local file, up to 50 MiB. Selecting a file can immediately send it to the website."},
        "key": {"type": "string"},
        "value": {"type": "string", "minLength": 1, "description": "Required non-empty expected value for verify; filename for file_selected. Also used by select."},
        "amount": {"type": "integer"},
        "assertion": {
            "type": "string",
            "enum": [
                "text_contains",
                "text_not_contains",
                "url_contains",
                "title_contains",
                "element_present",
                "file_selected",
            ],
        },
    },
    "required": ["action"],
    "allOf": [
        {
            "if": {
                "properties": {"action": {"const": "verify"}},
                "required": ["action"],
            },
            "then": {"required": ["expected_frame_id", "assertion", "value"]},
        }
    ],
    "additionalProperties": False,
}


def _origin(url: str) -> str:
    parsed = urlparse(url or "")
    if not parsed.scheme or not parsed.hostname:
        return ""
    default = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default
    return f"{parsed.scheme}://{parsed.hostname}:{port}"


def _is_local(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)


def _web_use_requires_approval(url: str = "", **_kw):
    arguments = _kw.get("arguments") or _kw
    if isinstance(arguments, dict) and arguments.get("action") == "upload":
        return "Upload the selected local file to the bound website; this can transmit file contents immediately."
    if url and not _is_local(url):
        return f"web_use will open external origin {_origin(url)}"
    return False


from .controller import (
    BrowserPageController,
)
from .prompts import (
    _result_for_prompt,
)
from .page_recovery import (
    _requested_url,
    _has_usable_page,
    _bound_page_shows_origin,
    _open_page_error,
    _opened_observation_is_live,
    _start_session_on_opened_page,
    _recover_web_use_page,
)
from .execute import (
    _desktop_unavailable_result,
    _execute_web_use,
    execute_direct_web_use,
)


def _new_controller() -> BrowserPageController:
    return BrowserPageController()


# Failures whose exact Page may still be open: the wrapper observes it again.
_RECOVERABLE_WEB_USE_REASONS = frozenset({
    "target_lost",
    "page_context_stale",
    "page_closed",
    "binding_not_found",
    "page_context_not_found",
    "page_context_consumed",
    "web_session_not_found",
})
# A session or token that no longer exists (turn ended, close, restart). When
# its Page cannot be re-observed, the failure carries the current pages so the
# next call is a single observe with a fresh token.
_ENDED_HANDLE_REASONS = frozenset({
    "page_context_not_found",
    "page_context_consumed",
    "web_session_not_found",
})


# Refusals decided before anything reaches the page. A failure with one of
# these applied nothing, so it is never an operation of unknown outcome.
_NOT_DISPATCHED_REASONS = frozenset({
    "stale_observation", "invalid_arguments", "desktop_response_timeout",
    "target_lost", "page_context_stale", "page_closed", "binding_not_found",
    "page_in_use", "page_context_required", "page_context_not_found",
    "page_context_consumed", "page_context_owner_mismatch", "page_not_found",
    "page_required", "web_session_not_found", "web_session_owner_mismatch",
    "owner_closing", "backend_mismatch", "unsupported_backend", "unsupported_action",
    "guarded_dispatch_unsupported", "observation_failed", "ref_not_found",
    "target_disabled", "file_input_required", "file_ref_action_required",
    "desktop_unavailable",
})


def _with_current_pages(failure: dict) -> dict:
    try:
        listed = _execute_web_use("list_pages")
    except Exception:
        # Discovery is a convenience here; the original failure still stands.
        return failure
    if not isinstance(listed, dict) or listed.get("ok") is not True:
        if isinstance(listed, dict) and listed.get("reason_code") == "desktop_unavailable":
            return {
                **failure,
                "retry_command": "list_pages",
                "message": (
                    f"{failure.get('message') or ''} The OpenProgram desktop app "
                    "is not connected yet; it may be restarting. Wait a few "
                    "seconds, then call web_use list_pages again."
                ).strip(),
            }
        return failure
    pages = [
        {
            key: page.get(key)
            for key in (
                "page", "window_id", "tab_id", "title", "origin",
                "visible", "focused", "page_context_token",
            )
        }
        for page in listed.get("pages") or []
        if isinstance(page, dict)
    ]
    ended = (
        "This browser session or page_context_token no longer exists (it "
        "ended with its turn, was closed, or OpenProgram restarted)."
    )
    return {
        **failure,
        "pages": pages,
        "recovery_command": "observe",
        "message": (
            f"{ended} The current pages are listed in pages: call web_use "
            "observe with the page_context_token of the task page, without "
            "the old web_session_id."
            if pages else
            f"{ended} No page is open now: call web_use observe with "
            "arguments.url to open the task page."
        ),
    }


_CANCELLATION_ERRORS = (CancelledError, ExecInterrupt, asyncio.CancelledError)


def _close_web_use_page(web_session_id: str) -> dict | ToolReturn:
    """web_use close: close the observed Page's tab, not only its session.

    Uses the resource close path, so ownership and the exact live binding are
    checked the same way. The control session ends with the tab.
    """
    from ..resource import close_page

    if not web_session_id:
        return ToolReturn(json_data={
            "ok": False, "page_closed": False,
            "reason_code": "web_session_required",
            "error": "close needs the web_session_id that observe returned for the Page.",
        }, is_error=True)
    result = close_page(web_session_id)
    if isinstance(result, dict) and result.get("ok"):
        return {
            "ok": True, "closed": True, "page_closed": True,
            "web_session_id": web_session_id,
        }
    failure = dict(result) if isinstance(result, dict) else {"error": str(result)}
    failure.setdefault("reason_code", str(failure.get("error") or "page_close_failed"))
    failure.update(ok=False, page_closed=False)
    return ToolReturn(json_data=failure, is_error=True)


def run_web_use(
    command: str,
    backend: str = "",
    page: str = "",
    page_context_token: str = "",
    web_session_id: str = "",
    arguments: dict | None = None,
) -> dict | ToolReturn:
    """One web_use command, with page recovery; shared by web_use and computer_use_agent."""
    if str(command or "").strip() == "close":
        nested = arguments.get("web_session_id") if isinstance(arguments, dict) else ""
        return _close_web_use_page(str(web_session_id or nested or "").strip())
    result = _execute_web_use(
        command,
        backend,
        page,
        page_context_token,
        web_session_id,
        arguments,
    )
    if isinstance(result, dict) and result.get("ok") is False:
        # Re-observe the exact lost target, but never replay a possibly
        # completed write.
        reason_code = result.get("reason_code")
        url = result.get("recovery_url")
        known_page = bool(
            result.get("recovery_tab_id") and result.get("recovery_window_id")
        )
        if reason_code in _RECOVERABLE_WEB_USE_REASONS and (
            known_page
            or (isinstance(url, str) and url.startswith(("http://", "https://")))
        ):
            recovered = _recover_web_use_page(result, backend=backend)
            if isinstance(recovered, dict) and recovered.get("ok") is not False:
                recovered.update(
                    recovered_page=True,
                    observe_required=True,
                    recovery_reason_code=reason_code,
                    recovery_previous_command=command,
                    previous_action_replayed=False,
                    message="The page was observed again. Continue using this fresh observation; the previous action was not replayed.",
                )
                return recovered
            if isinstance(recovered, dict):
                result = recovered
        if (
            result.get("reason_code") in _ENDED_HANDLE_REASONS
            # A consumed token whose session is alive already names the
            # one next call (use that web_session_id); keep it.
            and not result.get("live_web_session_id")
        ):
            result = _with_current_pages(result)
        if result.get("reason_code") in _NOT_DISPATCHED_REASONS:
            result.setdefault("action_dispatched", False)
        return ToolReturn(json_data=result, is_error=True)
    return result


def web_use(command: str,
    backend: str = "",
    page: str = "",
    page_context_token: str = "",
    web_session_id: str = "",
    arguments: dict | None = None,
) -> dict | ToolReturn:
    """List, observe, or control exact Pages in OpenProgram's built-in browser.

    Start with ``list_pages``. Select a returned ``page_context_token`` for
    ``observe``; do not pass a URL as ``page``. ``observe`` or ``act`` with
    ``url`` opens a desktop web tab when no Page is available. ``close``
    closes the observed Page's tab.
    """
    return run_web_use(command, backend, page, page_context_token, web_session_id, arguments)



__all__ = [
    "run_web_use",
    "web_use",
    "execute_direct_web_use",
    "BrowserPageController",
    # Shared with the sibling modules through ``state.<name>``.
    "_result_for_prompt",
    "_requested_url",
    "_has_usable_page",
    "_bound_page_shows_origin",
    "_open_page_error",
    "_opened_observation_is_live",
    "_start_session_on_opened_page",
    "_desktop_unavailable_result",
]
