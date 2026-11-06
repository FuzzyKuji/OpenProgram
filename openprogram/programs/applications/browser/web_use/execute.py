"""Platform web use."""
from __future__ import annotations
from importlib import import_module

# Bind to the web_use package namespace.
state = import_module(__package__)


def _desktop_unavailable_result(exc: BaseException) -> dict:
    """list_pages answer while no Desktop window can report its Pages."""
    return {
        "ok": False,
        "reason_code": "desktop_unavailable",
        "retry_command": "list_pages",
        "error": str(exc),
        "message": (
            "The OpenProgram desktop app is not connected yet; it may be "
            "restarting. Wait a few seconds, then call web_use list_pages again."
        ),
    }


def _execute_web_use(
    command: str, backend: str = "", page: str = "",
    page_context_token: str = "", web_session_id: str = "",
    arguments: dict | None = None,
) -> dict | state.ToolReturn:
    from openprogram.runtime.conversation import surface_context
    from openprogram.runtime.conversation.run_control import check_cancelled
    from .runtime import get_registry

    check_cancelled()

    payload = state.normalize_web_use_arguments({
        "command": command,
        "backend": backend,
        "page": page,
        "page_context_token": page_context_token,
        "web_session_id": web_session_id,
        "arguments": arguments,
    })
    command = str(payload.get("command") or command)
    backend = str(payload.get("backend") or "")
    page = str(payload.get("page") or "")
    page_context_token = str(payload.get("page_context_token") or "")
    web_session_id = str(payload.get("web_session_id") or "")
    arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}

    context = surface_context.current()
    owner_context_id = str((context or {}).get("context_id") or "")
    captured_here = False
    opened_here = False
    url = state._requested_url(arguments)
    if command in {"observe", "act"} and url and (
        not state._has_usable_page(context, web_session_id, page_context_token)
        # observe with a URL and no page named opens that URL, even when the
        # chat has other pages bound (say, after list_pages). Observing one
        # of those instead hands back a page the caller never asked for.
        or command == "observe"
        and not state._has_usable_page(None, web_session_id, page_context_token)
        and not state._bound_page_shows_origin(context, url)
    ):
        # A tab opens behind the user's work unless they asked to watch it.
        opened = surface_context.open_page(url, background=not bool(arguments.get("visible")))
        if "surfaces" not in opened:
            return state._open_page_error(opened)
        context = opened
        captured_here = True
        opened_here = True
        web_session_id = ""
        page_context_token = ""
    needs_page_capture = (
        not opened_here
        and context is None
        and (
            command == "list_pages"
            or (
                command == "observe"
                and not web_session_id
                and not page_context_token
            )
        )
    )
    if needs_page_capture:
        if command == "list_pages":
            try:
                context = surface_context.capture_pages_for_listing()
            except surface_context.DesktopUnavailableError as exc:
                return _desktop_unavailable_result(exc)
        else:
            context = surface_context.capture_active()
        captured_here = True

    if command == "list_pages":
        if not captured_here:
            # A workflow subprocess inherits the chat's origin-only window
            # context, but usually has no bound Page yet. Preserve that
            # context so capture_pages can use the parent webtab bridge;
            # passing None would make the child search its own empty WS
            # registry (or make an in-process call enumerate every window).
            capture_context = context if (
                surface_context.tool_enabled(context)
                or bool(
                    isinstance(context, dict)
                    and (
                        context.get("origin_window_id")
                        or context.get("window_id")
                    )
                )
            ) else None
            # A restarted App or closed origin window must not make discovery
            # fail: capture_pages_for_listing falls back to the other
            # registered windows and waits briefly for the App to reconnect.
            try:
                context = surface_context.capture_pages_for_listing(
                    capture_context
                )
            except surface_context.DesktopUnavailableError as exc:
                return _desktop_unavailable_result(exc)
            captured_here = True
        context = context or {}
        owner_id = surface_context.web_use_owner_id(
            {"context_id": owner_context_id} if owner_context_id else context
        )
        try:
            result = get_registry().list_pages(context=context, owner_id=owner_id)
        except BaseException:
            if captured_here:
                surface_context.release_bindings(context)
            raise
        if captured_here and not result.get("ok"):
            surface_context.release_bindings(context)
        return result

    owner_id = surface_context.web_use_owner_id(
        {"context_id": owner_context_id} if owner_context_id else context
    )
    if opened_here:
        try:
            observed = state._start_session_on_opened_page(
                context=context,
                owner_id=owner_id,
                backend=backend,
                arguments=arguments if command == "observe" else {},
                before_dispatch=check_cancelled,
            )
        except BaseException:
            surface_context.release_bindings(context)
            raise
        if observed.get("ok") is False:
            return observed
        if command == "observe" or str(arguments.get("action") or "") in {
            "", "navigate",
        }:
            return observed
        try:
            result = get_registry().execute(
                command="act",
                backend=backend,
                web_session_id=str(observed.get("web_session_id") or ""),
                owner_id=owner_id,
                page_context=context,
                arguments=arguments,
                before_dispatch=check_cancelled,
            )
        except BaseException:
            surface_context.release_bindings(context)
            raise
        if isinstance(result, dict):
            result = dict(result)
            result.setdefault("web_session_id", observed.get("web_session_id"))
        return result

    binding_id = ""
    page_key = ""
    if command == "observe" and not web_session_id and not page_context_token:
        token = surface_context.bind(context)
        unbound = False
        try:
            binding_id = surface_context.resolve_binding(page)
            page_key = surface_context.resolve_page_key(page)
        except RuntimeError:
            # Nothing is bound under that name in this turn: a new turn, a
            # spawned agent, or a page name from list_pages. Find it there.
            if captured_here:
                surface_context.release_bindings(context)
            unbound = True
        except BaseException:
            if captured_here:
                surface_context.release_bindings(context)
            raise
        finally:
            surface_context.reset(token)
        if unbound:
            listed = _listed_page_token(page)
            if isinstance(listed, dict):
                return listed
            return _execute_web_use(
                "observe", backend, "", listed, "", arguments,
            )
    try:
        result = get_registry().execute(
            command=command,
            backend=backend,
            web_session_id=web_session_id,
            binding_id=binding_id,
            page_key=page_key,
            owner_id=owner_id,
            page_context_token=page_context_token,
            page_context=context,
            arguments=arguments,
            before_dispatch=check_cancelled,
        )
    except BaseException:
        if captured_here:
            surface_context.release_bindings(context)
        raise
    if captured_here and command == "observe" and (
        not result.get("web_session_id") or result.get("session_reused")
    ):
        surface_context.release_bindings(context)
    return result


def _listed_page_token(page: str) -> str | dict:
    """The page_context_token of ``page`` (a name or alias from list_pages), or,
    with no name, of the one Page the user is looking at. A failure lists the
    Pages to choose from."""
    listed = _execute_web_use("list_pages")
    if not isinstance(listed, dict) or listed.get("ok") is not True:
        return listed if isinstance(listed, dict) else {
            "ok": False, "reason_code": "page_context_required"}
    pages = [item for item in listed.get("pages") or [] if isinstance(item, dict)]
    name = (page or "").strip()
    if name:
        matches = [item for item in pages if name == item.get("page")
                   or name == item.get("tab_id") or name in (item.get("aliases") or [])]
    else:
        matches = ([item for item in pages if item.get("focused")]
                   or [item for item in pages if item.get("visible")
                       and item.get("region") == "center"])
    if len(matches) == 1 and matches[0].get("page_context_token"):
        return str(matches[0]["page_context_token"])
    return {
        "ok": False,
        "reason_code": "page_not_found" if name else "page_required",
        "pages": [{key: item.get(key) for key in (
            "page", "title", "origin", "visible", "focused", "page_context_token",
        )} for item in pages],
        "recovery_command": "observe",
        "message": (
            (f"No Page named {name!r} is open. " if name else
             "Several Pages are open and none is in front. ")
            + "Call observe with the page_context_token of the task page from pages."
        ),
    }


def execute_direct_web_use(arguments: dict, *, owner_id: str):
    """Execute the first-class MCP contract with server-injected ownership."""
    from openprogram.runtime.conversation import surface_context
    from openprogram.runtime.conversation.run_control import check_cancelled
    from .runtime import get_registry

    check_cancelled()

    arguments = state.normalize_web_use_arguments(arguments)
    command = str(arguments.get("command") or "")
    registry = get_registry()
    if command == "list_pages":
        try:
            context = surface_context.capture_pages_for_listing()
        except surface_context.DesktopUnavailableError as exc:
            return _desktop_unavailable_result(exc)
        try:
            result = registry.list_pages(context=context, owner_id=owner_id)
        except BaseException:
            surface_context.release_bindings(context)
            raise
        if not result.get("ok"):
            surface_context.release_bindings(context)
        return result
    nested = (
        arguments.get("arguments")
        if isinstance(arguments.get("arguments"), dict)
        else {}
    )
    web_session_id = str(arguments.get("web_session_id") or "")
    page_context_token = str(arguments.get("page_context_token") or "")
    url = state._requested_url(nested)
    if command in {"observe", "act"} and url and not state._has_usable_page(
        None, web_session_id, page_context_token,
    ):
        opened = surface_context.open_page(url, background=not bool(nested.get("visible")))
        if "surfaces" not in opened:
            return state._open_page_error(opened)
        try:
            observed = state._start_session_on_opened_page(
                context=opened,
                owner_id=owner_id,
                backend=str(arguments.get("backend") or ""),
                arguments=nested if command == "observe" else {},
                before_dispatch=check_cancelled,
            )
        except BaseException:
            surface_context.release_bindings(opened)
            raise
        if observed.get("ok") is False:
            return observed
        if command == "observe" or str(nested.get("action") or "") in {
            "", "navigate",
        }:
            return observed
        result = registry.execute(
            command="act",
            backend=str(arguments.get("backend") or ""),
            web_session_id=str(observed.get("web_session_id") or ""),
            owner_id=owner_id,
            page_context=opened,
            arguments=nested,
            before_dispatch=check_cancelled,
        )
        if isinstance(result, dict):
            result = dict(result)
            result.setdefault("web_session_id", observed.get("web_session_id"))
        return result
    return registry.execute(
        command=command,
        backend=str(arguments.get("backend") or ""),
        web_session_id=web_session_id,
        owner_id=owner_id,
        page_context_token=page_context_token,
        arguments=nested,
        before_dispatch=check_cancelled,
    )
