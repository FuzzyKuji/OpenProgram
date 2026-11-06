"""Shared public schema for OpenProgram Web Use tools."""

from __future__ import annotations

from typing import Any, Mapping


SUPPORTED_WEB_USE_BACKENDS = (
    "playwright_mcp",
    "chrome_devtools_mcp",
    "open_claude_chrome",
)

_ACTION_FIELD_NAMES = (
    "action",
    "expected_frame_id",
    "ref",
    "x",
    "y",
    "url",
    "text",
    "path",
    "key",
    "value",
    "amount",
    "assertion",
    "mouse_button",
    "click_count",
    "modifiers",
    "to_ref",
    "to_x",
    "to_y",
    "direction",
    "format",
    "prefix",
    "suffix",
    "selection_type",
    "duration",
    "script",
    "pattern",
    "only_errors",
    "limit",
)
_VERIFY_LIFT_FIELDS = (
    "ref",
    "expected_frame_id",
    "assertion",
    "value",
)
_OBSERVE_LIFT_FIELDS = ("url", "visible", "changes_only")
_WEB_USE_CALL_KEYS = frozenset({
    "command",
    "backend",
    "page",
    "page_context_token",
    "web_session_id",
    "arguments",
    "runtime",
})
_ASSERTION_ENUM = (
    "text_contains",
    "text_not_contains",
    "url_contains",
    "title_contains",
    "element_present",
    "file_selected",
)
_ACT_ACTION_ENUM = (
    "screenshot",
    "navigate",
    "click",
    "type",
    "press",
    "scroll",
    "hover",
    "select",
    "upload",
    "drag",
    "type_text",
    "paste",
    "select_text",
    "back",
    "forward",
    "reload",
    "evaluate",
    "console_messages",
    "network_requests",
)


def _url_property() -> dict[str, Any]:
    return {
        "type": "string",
        "description": (
            "http(s) URL. observe or act with this field opens a desktop "
            "web tab when no Page is available."
        ),
    }


def _expected_frame_id_property() -> dict[str, Any]:
    return {
        "type": "string",
        "description": (
            "Latest frame_id from observe. The runtime fills this when omitted."
        ),
    }


def _action_properties() -> dict[str, Any]:
    return {
        "action": {
            "type": "string",
            "enum": list(_ACT_ACTION_ENUM),
            "description": (
                "Required for act. Direct callers may pass it next to command; "
                "it is lifted into arguments."
            ),
        },
        "expected_frame_id": _expected_frame_id_property(),
        "ref": {"type": "string"},
        "x": {"type": "number"},
        "y": {"type": "number"},
        "url": _url_property(),
        "text": {
            "type": "string",
            "description": "type replaces the field's value; type_text inserts at the caret; paste and select_text use it too.",
        },
        "path": {"type": "string", "description": "User-approved local file to upload, at most 50 MiB. May immediately transmit its contents."},
        "key": {"type": "string", "description": "press: the key, e.g. Enter or Control+A. Without ref it goes to the page's focus."},
        "value": {"type": "string"},
        "amount": {"type": "integer", "description": "scroll: pixels (default 500); negative scrolls up when no direction is given."},
        "assertion": {
            "type": "string",
            "enum": list(_ASSERTION_ENUM),
        },
        "mouse_button": {"type": "string", "enum": ["left", "right", "middle"], "description": "click: which button (default left)."},
        "click_count": {"type": "integer", "minimum": 1, "maximum": 3, "description": "click: 2 for a double click."},
        "modifiers": {"type": "string", "description": "click: keys held, e.g. \"cmd\" or \"shift+alt\"."},
        "to_ref": {"type": "string", "description": "drag: the ref to drop on."},
        "to_x": {"type": "number", "description": "drag: destination x in the last screenshot."},
        "to_y": {"type": "number", "description": "drag: destination y in the last screenshot."},
        "direction": {"type": "string", "enum": ["down", "up", "right", "left"], "description": "scroll direction; with ref the nearest scrollable container of that element scrolls."},
        "format": {"type": "string", "enum": ["text", "md", "html"], "description": "paste: how text is offered to the page (default text)."},
        "prefix": {"type": "string", "description": "select_text: text that must precede the match."},
        "suffix": {"type": "string", "description": "select_text: text that must follow the match."},
        "selection_type": {"type": "string", "enum": ["text", "cursor_before", "cursor_after"], "description": "select_text: select the text or place the caret."},
        "duration": {"type": "number", "minimum": 0, "maximum": 10, "description": "press: seconds to hold the key."},
        "script": {
            "type": "string",
            "maxLength": 8000,
            "description": (
                "evaluate: a JavaScript expression or function, e.g. () => document.title. "
                "The user approves every evaluate call; prefer observe and the other actions."
            ),
        },
        "pattern": {"type": "string", "description": "console_messages / network_requests: keep entries whose text or URL contains this."},
        "only_errors": {"type": "boolean", "description": "console_messages: errors and uncaught exceptions only; network_requests: failures and status 400+ only."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 200, "description": "console_messages / network_requests: newest entries to return (default 50)."},
    }


def _act_arguments_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": _action_properties(),
        "additionalProperties": False,
    }


def _verify_arguments_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["verify"],
                "description": "Use verify inside arguments.",
            },
            "ref": {"type": "string", "description": "Exact file-input ref for file_selected."},
            "expected_frame_id": _expected_frame_id_property(),
            "assertion": {
                "type": "string",
                "enum": list(_ASSERTION_ENUM),
            },
            "value": {"type": "string", "minLength": 1},
        },
        "required": ["assertion", "value"],
        "additionalProperties": False,
    }


def _observe_arguments_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "url": _url_property(),
            "visible": {
                "type": "boolean",
                "description": (
                    "With url: open the tab in front so the user can watch. Only when the "
                    "user asked to see it; by default pages open in the background."
                ),
            },
            "changes_only": {
                "type": "boolean",
                "description": (
                    "List in full only elements that are new or changed since the previous "
                    "observation of this page; unchanged ones are one line each with their new "
                    "ref, and an unchanged text or ARIA snapshot is left out. Every ref shown "
                    "belongs to this frame."
                ),
            },
            "detail": {
                "type": "string",
                "description": "Observation detail, for example interactive.",
            },
            "ref": {"type": "string", "description": "Exact file-input ref for file_selected."},
            "expected_frame_id": _expected_frame_id_property(),
        },
        "additionalProperties": False,
    }


def _arguments_schema() -> dict[str, Any]:
    return {
        "description": (
            "Command-specific arguments. act needs action; verify needs "
            "assertion and value; observe may include url and detail. "
            "Direct callers may still pass action, url, text, and ref next "
            "to command; they are lifted into arguments."
        ),
        "anyOf": [
            {"type": "null"},
            {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            _observe_arguments_schema(),
            _act_arguments_schema(),
            _verify_arguments_schema(),
        ],
    }


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _lift_fields_for(command: Any, action: Any) -> tuple[str, ...]:
    if command == "act":
        return _ACTION_FIELD_NAMES
    if command == "verify":
        if action == "verify":
            return ("action", *_VERIFY_LIFT_FIELDS)
        return _VERIFY_LIFT_FIELDS
    if command == "observe":
        return _OBSERVE_LIFT_FIELDS
    return ()


def normalize_web_use_arguments(args: Mapping[str, Any] | None) -> dict[str, Any]:
    """Lift command-applicable top-level fields into ``arguments``.

    Models that ignore ``allOf``/``if-then`` put ``action`` next to ``command``.
    Strict providers require every nested property and encode omission as
    JSON null; those nulls are dropped so canonical validation still sees
    omission. Numeric ``0`` stays. Already-nested non-null extras stay so
    command schemas can still reject them.
    """
    out = dict(args or {})
    had_nested = isinstance(out.get("arguments"), dict)
    nested = dict(out["arguments"]) if had_nested else {}
    action = out.get("action")
    if _blank(action):
        action = nested.get("action")
    for key in _lift_fields_for(out.get("command"), action):
        top = out.get(key)
        inner = nested.get(key)
        if not _blank(top) and key not in nested:
            nested[key] = top
        elif _blank(top) and not _blank(inner):
            out[key] = inner
    nested = {key: value for key, value in nested.items() if value is not None}
    if nested:
        out["arguments"] = nested
    elif had_nested:
        out["arguments"] = {}
    normalized = {}
    for key, value in out.items():
        if key not in _WEB_USE_CALL_KEYS:
            continue
        if value is None and key != "arguments":
            continue
        normalized[key] = value
    return normalized


def web_use_parameters() -> dict:
    """Return a fresh command-conditioned Web Use JSON Schema."""
    backend_values = ["", *SUPPORTED_WEB_USE_BACKENDS]
    return {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["list_pages", "observe", "act", "verify", "close"],
                "description": (
                    "Call list_pages first, then observe, act, verify, or close. "
                    "observe or act with url opens a desktop web tab when no "
                    "Page exists."
                ),
            },
            "backend": {
                "type": "string",
                "enum": backend_values,
                "description": (
                    "Backend selected when observe creates a session. Omit or "
                    "use an empty string for the default backend."
                ),
            },
            "page": {
                "type": "string",
                "maxLength": 512,
                "description": "A Page alias from the current turn; never a URL",
            },
            "page_context_token": {"type": "string", "maxLength": 128},
            "web_session_id": {
                "type": "string",
                "maxLength": 128,
                "description": (
                    "Session id returned by observe. Do not invent placeholders "
                    "such as pending; omit it and the runtime reuses the latest "
                    "session for this turn."
                ),
            },
            "arguments": _arguments_schema(),
        },
        "required": ["command"],
        "allOf": [
            {
                "if": {
                    "properties": {"command": {"const": "act"}},
                    "required": ["command"],
                },
                "then": {
                    "properties": {
                        "web_session_id": {"type": "string"},
                        "arguments": _act_arguments_schema(),
                    },
                },
            },
            {
                "if": {
                    "properties": {"command": {"const": "verify"}},
                    "required": ["command"],
                },
                "then": {
                    "required": ["web_session_id"],
                    "properties": {
                        "web_session_id": {"type": "string", "minLength": 1},
                        "arguments": _verify_arguments_schema(),
                    },
                },
            },
            {
                "if": {
                    "properties": {"command": {"const": "close"}},
                    "required": ["command"],
                },
                "then": {
                    "required": ["web_session_id"],
                    "properties": {
                        "web_session_id": {"type": "string", "minLength": 1},
                    },
                },
            },
        ],
        "additionalProperties": False,
    }


__all__ = [
    "SUPPORTED_WEB_USE_BACKENDS",
    "normalize_web_use_arguments",
    "web_use_parameters",
]
