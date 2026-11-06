"""Page-side pieces of the richer ``web_use`` actions, shared by every backend.

Clicks with options, element scrolling, inserting text at the caret,
pasting, and selecting text run as small scripts inside the page, so the
built-in browser, the headless Chromium and both MCP backends behave the
same and a bound tab is driven without being focused. Each script takes
``(element, options)``; ``element`` is ``null`` for the page's focus.
"""
from __future__ import annotations

import json
from typing import Any

# Actions added for Codex parity. They change the page like ``click`` does.
PARITY_ACTIONS = ("drag", "type_text", "paste", "select_text", "back", "forward", "reload")
MOUSE_BUTTONS = ("left", "right", "middle")
DIRECTIONS = ("down", "up", "right", "left")
PASTE_FORMATS = ("text", "md", "html")
SELECTION_TYPES = ("text", "cursor_before", "cursor_after")
# Arbitrary JavaScript reads everything a signed-in page holds, so it is
# approved per call and never by a standing rule (see permissions.policy).
EVALUATE_ACTION = "evaluate"
MAX_SCRIPT_CHARS = 8000
MAX_RESULT_CHARS = 20_000
MAX_HOLD_SECONDS = 10.0

_MODIFIERS = {
    "cmd": "Meta", "command": "Meta", "meta": "Meta", "super": "Meta",
    "ctrl": "Control", "control": "Control",
    "alt": "Alt", "option": "Alt", "opt": "Alt",
    "shift": "Shift",
}
_JS_FLAGS = {"Meta": "metaKey", "Control": "ctrlKey", "Alt": "altKey", "Shift": "shiftKey"}


class ActionError(ValueError):
    """An argument the page action cannot use; ``reason_code`` names it."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code

    def result(self) -> dict[str, Any]:
        return {"ok": False, "reason_code": self.reason_code, "message": str(self)}


def modifiers(spec: Any) -> list[str]:
    """``"cmd+shift"`` or ``"ctrl, alt"`` -> Playwright modifier names, in order, without repeats."""
    out: list[str] = []
    for part in str(spec or "").replace(",", "+").split("+"):
        name = part.strip().lower()
        if not name:
            continue
        if name not in _MODIFIERS:
            raise ActionError("invalid_modifiers", f"unknown modifier {part.strip()!r}; use cmd, ctrl, alt or shift")
        if _MODIFIERS[name] not in out:
            out.append(_MODIFIERS[name])
    return out


def click_options(arguments: dict[str, Any]) -> dict[str, Any]:
    button = str(arguments.get("mouse_button") or "left").lower()
    if button not in MOUSE_BUTTONS:
        raise ActionError("invalid_mouse_button", "mouse_button must be left, right or middle")
    try:
        count = int(arguments.get("click_count") or 1)
    except (TypeError, ValueError) as exc:
        raise ActionError("invalid_click_count", "click_count must be 1, 2 or 3") from exc
    if not 1 <= count <= 3:
        raise ActionError("invalid_click_count", "click_count must be 1, 2 or 3")
    keys = modifiers(arguments.get("modifiers"))
    return {"button": button, "count": count, "modifiers": keys,
            "flags": {_JS_FLAGS[key]: True for key in keys}}


def is_plain_click(options: dict[str, Any]) -> bool:
    return options["button"] == "left" and options["count"] == 1 and not options["modifiers"]


# Ticking one of these changes only its own state, so the observation stays usable.
CHOICE_ROLES = frozenset({"checkbox", "radio", "switch", "option", "menuitemcheckbox", "menuitemradio"})


def is_choice_control(role: Any, input_type: Any = None) -> bool:
    return str(role or "").lower() in CHOICE_ROLES or str(input_type or "").lower() in {"checkbox", "radio"}


def mouse_options(options: dict[str, Any]) -> dict[str, Any]:
    """Playwright mouse arguments that differ from a single left click."""
    out: dict[str, Any] = {}
    if options["button"] != "left":
        out["button"] = options["button"]
    if options["count"] != 1:
        out["click_count"] = options["count"]
    return out


def scroll_delta(arguments: dict[str, Any]) -> tuple[int, int]:
    """(dx, dy) in CSS pixels; ``amount`` keeps its old meaning (signed, vertical) without a direction."""
    try:
        amount = int(arguments.get("amount") if arguments.get("amount") is not None else 500)
    except (TypeError, ValueError) as exc:
        raise ActionError("invalid_amount", "amount must be a whole number of pixels") from exc
    direction = str(arguments.get("direction") or "").lower()
    if not direction:
        return 0, amount
    if direction not in DIRECTIONS:
        raise ActionError("invalid_direction", "direction must be down, up, right or left")
    amount = abs(amount)
    return {"down": (0, amount), "up": (0, -amount), "right": (amount, 0), "left": (-amount, 0)}[direction]


def hold_seconds(arguments: dict[str, Any]) -> float:
    try:
        seconds = float(arguments.get("duration") or 0)
    except (TypeError, ValueError) as exc:
        raise ActionError("invalid_duration", "duration must be a number of seconds") from exc
    if not 0 <= seconds <= MAX_HOLD_SECONDS:
        raise ActionError("invalid_duration", f"duration must be between 0 and {MAX_HOLD_SECONDS:g} seconds")
    return seconds


def paste_payload(arguments: dict[str, Any]) -> dict[str, str]:
    text = arguments.get("text")
    if not isinstance(text, str) or not text:
        raise ActionError("text_required", "paste needs text")
    kind = str(arguments.get("format") or "text").lower()
    kind = "md" if kind == "markdown" else kind
    if kind not in PASTE_FORMATS:
        raise ActionError("invalid_format", "format must be text, md or html")
    if kind == "text":
        return {"text": text, "html": ""}
    if kind == "md":
        from markdown_it import MarkdownIt
        return {"text": text, "html": MarkdownIt("commonmark").enable("table").enable("strikethrough").render(text)}
    return {"text": _strip_tags(text), "html": text}


def selection_request(arguments: dict[str, Any]) -> dict[str, str]:
    text = arguments.get("text")
    if not isinstance(text, str) or not text:
        raise ActionError("text_required", "select_text needs the text to find")
    kind = str(arguments.get("selection_type") or "text")
    if kind not in SELECTION_TYPES:
        raise ActionError("invalid_selection_type", "selection_type must be text, cursor_before or cursor_after")
    return {"text": text, "prefix": str(arguments.get("prefix") or ""),
            "suffix": str(arguments.get("suffix") or ""), "kind": kind}


_FUNCTION_START = None


def evaluate_source(arguments: dict[str, Any]) -> str:
    """``script`` as a function the page can call: a function stays one, an expression is wrapped."""
    import re
    global _FUNCTION_START
    script = arguments.get("script")
    if not isinstance(script, str) or not script.strip():
        raise ActionError("script_required", "evaluate needs script: an expression or a function such as () => document.title")
    script = script.strip()
    if len(script) > MAX_SCRIPT_CHARS:
        raise ActionError("script_too_long", f"script is limited to {MAX_SCRIPT_CHARS} characters")
    if _FUNCTION_START is None:
        _FUNCTION_START = re.compile(r"^(async\s+)?(function\b|\([^()]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)")
    return script if _FUNCTION_START.match(script) else f"() => ({script})"


def evaluation_text(result: Any) -> str:
    """The script's result as JSON text, cut at MAX_RESULT_CHARS."""
    if result is None:
        text = "undefined"
    elif isinstance(result, str):
        text = result
    else:
        text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f"\n[truncated, {len(text) - MAX_RESULT_CHARS} more characters]"
    return text


def _strip_tags(html: str) -> str:
    import re
    from html import unescape
    return unescape(re.sub(r"<[^>]+>", "", html))


POINTER_SCRIPT = r"""
(element, o) => {
  const rect = element.getBoundingClientRect();
  const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
  const cursor = globalThis.__openprogramAgentCursor;
  if (cursor?.armed && typeof cursor.show === "function") {
    cursor.armed = false;
    cursor.show(x, y);
  }
  const button = {left: 0, middle: 1, right: 2}[o.button] ?? 0;
  const flags = o.flags || {};
  if (button === 0 && o.count === 1 && !Object.keys(flags).length && typeof element.click === "function") {
    element.click();
    return true;
  }
  const base = {bubbles: true, cancelable: true, composed: true, view: window,
    clientX: x, clientY: y, button, ...flags};
  const pressed = {0: 1, 1: 4, 2: 2}[button];
  const fire = (type, detail, buttons) => element.dispatchEvent(type.startsWith("pointer")
    ? new PointerEvent(type, {...base, detail, buttons, pointerType: "mouse", isPrimary: true})
    : new MouseEvent(type, {...base, detail, buttons}));
  if (typeof element.focus === "function") element.focus({preventScroll: true});
  for (let i = 1; i <= o.count; i++) {
    fire("pointerdown", i, pressed); fire("mousedown", i, pressed);
    fire("pointerup", i, 0); fire("mouseup", i, 0);
    if (button === 0) fire("click", i, 0);
    else if (button === 1) fire("auxclick", i, 0);
  }
  if (button === 0 && o.count === 2) fire("dblclick", 2, 0);
  if (button === 2) fire("contextmenu", 1, 0);
  return true;
}
"""

SCROLL_SCRIPT = r"""
(element, o) => {
  const doc = element.ownerDocument;
  const root = doc.scrollingElement || doc.documentElement;
  const scrolls = (n) => {
    const s = getComputedStyle(n);
    return (o.dy && /(auto|scroll|overlay)/.test(s.overflowY) && n.scrollHeight > n.clientHeight)
      || (o.dx && /(auto|scroll|overlay)/.test(s.overflowX) && n.scrollWidth > n.clientWidth);
  };
  let node = element;
  while (node && node !== doc.body && node !== doc.documentElement && !scrolls(node)) node = node.parentElement;
  const target = node && node !== doc.body && node !== doc.documentElement ? node : root;
  const before = [target.scrollLeft, target.scrollTop];
  target.scrollBy({left: o.dx, top: o.dy, behavior: "instant"});
  return {moved: before[0] !== target.scrollLeft || before[1] !== target.scrollTop,
          container: target === root ? "page" : target.tagName.toLowerCase()};
}
"""

INSERT_TEXT_SCRIPT = r"""
(element, o) => {
  const doc = element ? element.ownerDocument : document;
  if (element && typeof element.focus === "function") element.focus({preventScroll: true});
  const active = doc.activeElement;
  if (!active || (active === doc.body && doc.designMode !== "on")) return {ok: false, reason_code: "focus_required"};
  if (doc.execCommand("insertText", false, o.text)) return {ok: true};
  if (typeof active.setRangeText === "function") {
    const end = active.value.length;
    active.setRangeText(o.text, active.selectionStart ?? end, active.selectionEnd ?? end, "end");
    active.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: o.text}));
    return {ok: true};
  }
  return {ok: false, reason_code: "not_editable"};
}
"""

PASTE_SCRIPT = r"""
(element, o) => {
  const doc = element ? element.ownerDocument : document;
  if (element && typeof element.focus === "function") element.focus({preventScroll: true});
  const target = doc.activeElement || doc.body;
  const data = new DataTransfer();
  data.setData("text/plain", o.text);
  if (o.html) data.setData("text/html", o.html);
  const event = new ClipboardEvent("paste", {clipboardData: data, bubbles: true, cancelable: true, composed: true});
  if (!target.dispatchEvent(event)) return {ok: true, handled_by_page: true};
  const rich = target.isContentEditable || doc.designMode === "on";
  const asHtml = rich && !!o.html;
  const done = asHtml ? doc.execCommand("insertHTML", false, o.html)
    : doc.execCommand("insertText", false, o.text);
  return done ? {ok: true, handled_by_page: false, rich: asHtml} : {ok: false, reason_code: "not_editable"};
}
"""

SELECT_TEXT_SCRIPT = r"""
(element, o) => {
  const doc = element.ownerDocument;
  const find = (hay) => {
    for (let at = hay.indexOf(o.text); at !== -1; at = hay.indexOf(o.text, at + 1)) {
      const before = hay.slice(Math.max(0, at - o.prefix.length), at);
      const after = hay.slice(at + o.text.length, at + o.text.length + o.suffix.length);
      if ((!o.prefix || before === o.prefix) && (!o.suffix || after === o.suffix)) return at;
    }
    return -1;
  };
  const span = (at) => o.kind === "cursor_before" ? [at, at]
    : o.kind === "cursor_after" ? [at + o.text.length, at + o.text.length] : [at, at + o.text.length];
  if (typeof element.setSelectionRange === "function" && typeof element.value === "string") {
    const at = find(element.value);
    if (at < 0) return {ok: false, reason_code: "text_not_found"};
    element.focus({preventScroll: true});
    element.setSelectionRange(...span(at));
    return {ok: true};
  }
  const walker = doc.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let hay = "";
  while (walker.nextNode()) { nodes.push([walker.currentNode, hay.length]); hay += walker.currentNode.data; }
  const at = find(hay);
  if (at < 0) return {ok: false, reason_code: "text_not_found"};
  const locate = (offset) => {
    for (let k = nodes.length - 1; k >= 0; k--) if (nodes[k][1] <= offset) return [nodes[k][0], offset - nodes[k][1]];
    return [element, 0];
  };
  const [start, end] = span(at);
  const editable = element.isContentEditable ? element : element.closest?.("[contenteditable]");
  if (editable && typeof editable.focus === "function") editable.focus({preventScroll: true});
  const range = doc.createRange();
  range.setStart(...locate(start));
  range.setEnd(...locate(end));
  const selection = doc.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  return {ok: true};
}
"""


def bound_call(script: str, options: dict[str, Any], *, with_element: bool = True, require: str = "") -> str:
    """A function an MCP ``evaluate`` can run, with the options inlined as JSON.

    With ``require``, a result whose field of that name is falsy throws, so
    the backend reports the call as failed instead of as done.
    """
    payload = json.dumps(options, ensure_ascii=False)
    head, element = ("(element) => ", "element") if with_element else ("() => ", "null")
    call = f"({script.strip()})({element}, {payload})"
    if not require:
        return f"{head}{call}"
    return (f"{head}{{ const r = {call}; if (!r || !r[{json.dumps(require)}]) "
            f"throw new Error((r && r.reason_code) || {json.dumps(require + '_failed')}); return r; }}")


__all__ = [
    "ActionError", "EVALUATE_ACTION", "INSERT_TEXT_SCRIPT", "MAX_RESULT_CHARS", "MAX_SCRIPT_CHARS", "PARITY_ACTIONS", "PASTE_SCRIPT", "POINTER_SCRIPT",
    "SCROLL_SCRIPT", "SELECT_TEXT_SCRIPT", "bound_call", "click_options", "evaluate_source", "mouse_options", "evaluation_text",
    "hold_seconds",
    "CHOICE_ROLES", "is_choice_control", "is_plain_click", "modifiers", "paste_payload", "scroll_delta", "selection_request",
]
