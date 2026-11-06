"""The ``web`` resource provider and the Page leases the core borrows.

``register`` adds the provider ``web`` (list, open, observe, act, verify,
release, close a built-in browser Page) to the shared resource registry and
returns its undo; the application's ``setup`` calls it.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager


def close_page(web_session_id):
    """Close the observed Page's tab; distinct from releasing its control session."""
    from openprogram.runtime.conversation import surface_context
    from openprogram.host.resources import desktop_link
    from .web_use.runtime import get_registry
    registry = get_registry()
    owner = surface_context.web_use_owner_id()
    with registry._lock:
        session = registry._sessions.get(web_session_id)
    if session is None:
        return {'ok': False, 'error': 'web_session_not_found'}
    with session.operation_lock:
        if session.closed or session.closing or session.owner_id != owner:
            return {'ok': False, 'error': 'web_session_owner_mismatch'}
        descriptor = desktop_link.binding_page_descriptor(session.binding_id)
        if descriptor.get('page_key') != session.page_key:
            return {'ok': False, 'error': 'page_context_stale'}
        result = desktop_link.request_close_tab(session.binding_id)
        if result.get('ok'):
            registry.execute(command='close', owner_id=owner, web_session_id=web_session_id)
        return result


@contextmanager
def authorized_page(arguments, window_id):
    """Reuse the observed Page's lease for a native presentation command."""
    from openprogram.runtime.conversation import surface_context
    from openprogram.host.resources.providers.builtin import _require_tool
    from openprogram.host.resources import desktop_link
    from .web_use.runtime import get_registry
    _require_tool('web_use')
    registry = get_registry()
    with registry._lock:
        session = registry._sessions.get(arguments.get('web_session_id'))
    if session is None:
        raise ValueError('observe_web_resource_before_interface_operation')
    with session.operation_lock:
        if session.closed or session.closing or session.owner_id != surface_context.web_use_owner_id():
            raise PermissionError('web_session_owner_mismatch')
        descriptor = desktop_link.binding_page_descriptor(session.binding_id)
        args = arguments.get('arguments', [])
        if (not args or descriptor.get('tab_id') != args[0] or descriptor.get('page_key') != session.page_key
                or (window_id and descriptor.get('window_id') != window_id)):
            raise ValueError('page_context_stale')
        resolved = desktop_link.request_bound_tab(session.binding_id)
        if not resolved.get('ok'):
            raise ValueError('page_context_stale')
        from openprogram.host.processes import current_owner
        session_id, _, _ = current_owner()
        yield {**descriptor, 'session_id': session_id}


def _web(action: str, arguments: dict):
    from openprogram.host.resources.providers.builtin import _require_tool
    _require_tool("web_use")
    from .web_use.execute import _execute_web_use
    if action == "close":
        return close_page(arguments["web_session_id"])
    if action == "open":
        from openprogram.runtime.conversation import surface_context
        from .web_use.page_recovery import _open_page_error, _start_session_on_opened_page
        opened = surface_context.open_page(arguments["url"], background=True)
        if "surfaces" not in opened:
            return _open_page_error(opened)
        try:
            return _start_session_on_opened_page(
                context=opened, owner_id=surface_context.web_use_owner_id(),
                backend=arguments.get("backend", ""), arguments={},
            )
        except BaseException:
            surface_context.release_bindings(opened)
            raise
    # release ends the control session and keeps the Page; close (above) closes its tab.
    command = {"list": "list_pages", "release": "close"}.get(action, action)
    return _execute_web_use(command, **arguments)


def _actions() -> dict[str, dict]:
    from .contract import web_use_parameters
    web_schema = web_use_parameters()
    actions = {}
    for action, command in (("list", "list_pages"), ("observe", "observe"), ("act", "act"),
                            ("verify", "verify"), ("release", "close")):
        # Specialize the existing command-conditioned schema without weakening it.
        schema = copy.deepcopy(web_schema)
        # The command is injected by the adapter, not accepted from the caller.
        conditions = schema.pop("allOf", [])
        schema["properties"].pop("command")
        schema["required"] = []
        for condition in conditions:
            if condition["if"]["properties"]["command"]["const"] == command:
                schema["properties"].update(condition["then"].get("properties", {}))
                schema["required"] = condition["then"].get("required", [])
        schema["additionalProperties"] = False
        actions[action] = schema
    actions["close"] = {"type": "object", "properties": {"web_session_id": {"type": "string", "minLength": 1}},
                        "required": ["web_session_id"], "additionalProperties": False}
    actions["open"] = {"type": "object", "properties": {
        "url": {"type": "string", "pattern": "^https?://"},
        "backend": web_schema["properties"]["backend"],
    }, "required": ["url"], "additionalProperties": False}
    return actions


def register(registry):
    """Add the ``web`` provider to ``registry``; returns the undo."""
    from openprogram.host.resources import ResourceProvider
    registry.register(ResourceProvider("web", "Built-in browser Page", _actions(), _web))
    return lambda: registry.unregister("web")
