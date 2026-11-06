"""Session-scoped command contract for the built-in browser Page."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from dataclasses import field
from contextlib import suppress
import copy
import threading
import uuid
from typing import Any, Callable, Mapping

from openprogram.programs import ToolReturn
from openprogram.programs.applications.browser.contract import (
    SUPPORTED_WEB_USE_BACKENDS,
    normalize_web_use_arguments,
)
import logging

_log = logging.getLogger(__name__)


SUPPORTED_BACKENDS = SUPPORTED_WEB_USE_BACKENDS
DEFAULT_BACKEND = SUPPORTED_BACKENDS[0]

# Actions whose effect does not depend on what the caller last read from the
# page. Without a current frame the registry observes first (read-only)
# instead of rejecting them; screenshot and wait also retry once on a stale
# frame because they never write.
_REFRESHABLE_ACTIONS = frozenset({"navigate", "screenshot", "wait"})
_READ_ONLY_ACTIONS = frozenset({"screenshot", "wait"})
# Ended sessions and expired tokens remember only their exact window/tab so a
# later call from the same chat can re-observe that Page. Bounded, in memory.
_TOMBSTONE_LIMIT = 512

_SESSION_GONE_MESSAGE = (
    "This web_session_id no longer exists: a session ends with its turn, on "
    "close, or when OpenProgram restarts. Call list_pages, then observe the "
    "task page with its new page_context_token."
)
_TOKEN_GONE_MESSAGE = (
    "This page_context_token is no longer valid: tokens are single-use and "
    "expire when the turn ends or OpenProgram restarts. Call list_pages, then "
    "observe the task page with its new page_context_token."
)
_TOKEN_OWNER_MESSAGE = (
    "This page_context_token was issued to another turn or caller. Call "
    "list_pages and use a token from that result."
)
_STALE_MESSAGE = (
    "The page changed after this frame was observed, so nothing was sent. "
    "Call observe on this web_session_id, then retry with the new frame_id."
)
_UNSEEN_REFS_MESSAGE = (
    "Refs come only from an observe result. This frame was captured "
    "automatically for a screenshot or navigation, so call observe on this "
    "web_session_id and use refs from that result."
)
_NO_FRAME_MESSAGE = (
    "There is no current observation: the previous action changed the page. "
    "Call observe on this web_session_id, then retry with the new frame_id."
)


_PAGE_IN_USE_MESSAGE = (
    "Another task is acting on this page right now (another conversation, or "
    "an action still running). Nothing was sent. The page itself is fine: "
    "wait for that task to finish, then call observe again."
)


def _unresolved_session_id(value: str) -> bool:
    return str(value or "").strip().lower() in {"", "pending"}


def _owner_scope(owner_id: str) -> str:
    """Turn owners of one chat share a recovery scope; other owners stay exact."""
    parts = str(owner_id or "").split(":", 2)
    if len(parts) == 3 and parts[0] == "turn" and parts[1]:
        return f"turn:{parts[1]}"
    return str(owner_id or "")


def _capability_target(capability: Mapping[str, Any]) -> dict[str, str]:
    context = capability.get("context") or {}
    surface = next((
        item for item in context.get("surfaces") or [] if isinstance(item, dict)
    ), {})
    return {
        "window_id": str(surface.get("window_id") or context.get("window_id") or ""),
        "tab_id": str(surface.get("tab_id") or ""),
    }


def _session_target(session: WebUseSession) -> dict[str, str]:
    identity = session.state.get("page_identity") or {}
    window_id = str(identity.get("window_id") or "")
    tab_id = str(identity.get("tab_id") or "")
    context = session.page_context if isinstance(session.page_context, dict) else {}
    for item in context.get("surfaces") or []:
        if isinstance(item, dict) and item.get("binding_id") == session.binding_id:
            window_id = window_id or str(
                item.get("window_id") or context.get("window_id") or ""
            )
            tab_id = tab_id or str(item.get("tab_id") or "")
            break
    return {"window_id": window_id, "tab_id": tab_id}


def _reason_code(result: Any) -> str:
    payload = (
        result.json_data
        if isinstance(result, ToolReturn) and isinstance(result.json_data, dict)
        else result if isinstance(result, dict) else {}
    )
    if payload.get("ok") is not False:
        return ""
    return str(payload.get("reason_code") or "")


def _session_frame_id(session: WebUseSession) -> str:
    frame_id = str(session.state.get("frame_id") or "").strip()
    if frame_id:
        return frame_id
    controller = session.controller
    frame = getattr(controller, "_frame", None) if controller is not None else None
    if isinstance(frame, dict):
        return str(frame.get("frame_id") or "").strip()
    return ""


def _session_viewport(session: WebUseSession) -> dict[str, Any] | None:
    viewport = session.state.get("viewport")
    if isinstance(viewport, dict):
        return viewport
    frame = getattr(session.controller, "_frame", None)
    if isinstance(frame, dict) and isinstance(frame.get("viewport"), dict):
        return frame["viewport"]
    return None


def _result_frame_id(result: Any) -> str:
    payload = (
        result.json_data
        if isinstance(result, ToolReturn) and isinstance(result.json_data, dict)
        else result if isinstance(result, dict) else None
    )
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("frame_id") or "").strip()


def _trusted_binding(session: WebUseSession) -> dict[str, Any]:
    """Native window/tab/generation only from a live server binding for this Page."""
    if not session.binding_id or not session.page_key:
        return {}
    try:
        from openprogram.host.resources.desktop_link import binding_page_descriptor
        descriptor = binding_page_descriptor(session.binding_id)
    except Exception:
        return {}
    if not descriptor:
        return {}
    if str(descriptor.get("page_key") or "") != session.page_key:
        return {}
    window_id = str(descriptor.get("window_id") or "")
    tab_id = str(descriptor.get("tab_id") or "")
    generation = int(descriptor.get("connection_generation") or 0)
    if not window_id or not tab_id or generation <= 0:
        return {}
    return {
        "window_id": window_id,
        "tab_id": tab_id,
        "connection_generation": generation,
    }


def _controller_display(session: WebUseSession, result: Any = None) -> dict[str, str]:
    """title/URL from BrowserPageController observe frame or _mutated after success."""
    frame = getattr(session.controller, "_frame", None) if session.controller else None
    if isinstance(frame, dict):
        title = str(frame.get("title") or "")
        url = str(frame.get("url") or "")
        if title or url:
            return {"title": title, "target": url}
    payload = result.json_data if isinstance(result, ToolReturn) else result
    if isinstance(payload, dict) and (
        payload.get("observe_required") is True or payload.get("frame_id")
    ):
        title = str(payload.get("title") or "")
        url = str(payload.get("url") or "")
        if title or url:
            return {"title": title, "target": url}
    return {}


def _publish_bound_page(session: WebUseSession, result: Any = None) -> None:
    identity = _trusted_binding(session)
    display = _controller_display(session, result)
    if display.get("target"):
        session.state["last_url"] = display["target"]
    if identity:
        session.state["page_identity"] = identity
    if not identity:
        return
    try:
        from openprogram.programs.applications.browser.pages import publish_bound_page
        publish_bound_page(session.page_key, **identity, **display)
    except Exception:
        # Publication feeds the App's page view; the browser action itself succeeded.
        _log.debug("bound page not published page=%s", session.page_key, exc_info=True)


def _is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    except ImportError:
        return False
    return isinstance(exc, PlaywrightTimeoutError)


@dataclass
class WebUseSession:
    id: str
    backend: str
    binding_id: str
    page_key: str = ""
    page_revision: int = 0
    access_revision: int = 0
    geometry_revision: int = 0
    owner_id: str = ""
    page_context: dict[str, Any] | None = None
    controller: Any = None
    state: dict[str, Any] = field(default_factory=dict)
    operation_lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False,
    )
    closing: bool = False
    closed: bool = False
    inflight_ops: int = 0


def _session_fields(session: WebUseSession, *, reused: bool = False) -> dict[str, Any]:
    """Reusable session handle, or closed after this command cleaned it."""
    fields = {
        "web_session_id": session.id,
        "backend": session.backend,
    }
    if reused:
        fields["session_reused"] = True
    if session.closed:
        fields["closed"] = True
    return fields


class ControllerBackend:
    """Canonical command adapter over one exact BrowserPageController."""

    supports_operation_guard = True

    def __init__(self, name: str, controller_factory: Callable[[], Any]) -> None:
        self.name = name
        self._controller_factory = controller_factory

    def _controller(self, session: WebUseSession):
        if session.controller is None:
            controller = self._controller_factory()
            controller.binding_id = session.binding_id
            controller.page_revision = session.page_revision
            controller.access_revision = session.access_revision
            controller.geometry_revision = session.geometry_revision
            session.controller = controller
        return session.controller

    def observe(self, session: WebUseSession, arguments: Mapping[str, Any], *, before_dispatch=None):
        return self._controller(session).execute(
            action="observe", changes_only=bool(arguments.get("changes_only")),
            **({"before_dispatch": before_dispatch} if before_dispatch is not None else {}))

    def act(self, session: WebUseSession, arguments: Mapping[str, Any], *, before_dispatch=None):
        return self._controller(session).execute(**dict(arguments), **({"before_dispatch": before_dispatch} if before_dispatch is not None else {}))

    def verify(self, session: WebUseSession, arguments: Mapping[str, Any], *, before_dispatch=None):
        params = dict(arguments)
        params["action"] = "verify"
        return self._controller(session).execute(**params, **({"before_dispatch": before_dispatch} if before_dispatch is not None else {}))

    def close(self, session: WebUseSession) -> None:
        if session.controller is not None:
            session.controller.close()


class WebUseSessionRegistry:
    def __init__(
        self,
        *,
        adapters: Mapping[str, Any] | None = None,
        controller_factory: Callable[[], Any] | None = None,
        release_context: Callable[[dict | None], None] | None = None,
        page_key_resolver: Callable[[str], str] | None = None,
        binding_revision_resolver: Callable[[str], Mapping[str, int]] | None = None,
        binding_validator: Callable[[str], Mapping[str, Any]] | None = None,
    ) -> None:
        if adapters is None:
            if controller_factory is None:
                from . import _new_controller
                controller_factory = _new_controller
            from .mcp_backends import OfficialMCPPageBackend
            adapters = {
                "playwright_mcp": OfficialMCPPageBackend(
                    "playwright_mcp", controller_factory,
                ),
                "chrome_devtools_mcp": OfficialMCPPageBackend(
                    "chrome_devtools_mcp", controller_factory,
                ),
                "open_claude_chrome": ControllerBackend(
                    "open_claude_chrome", controller_factory,
                ),
            }
        missing = set(SUPPORTED_BACKENDS) - set(adapters)
        if missing:
            raise ValueError(f"missing computer use adapters: {sorted(missing)}")
        self._adapters = dict(adapters)
        self._sessions: dict[str, WebUseSession] = {}
        self._page_leases: dict[str, str] = {}
        self._page_capabilities: dict[str, dict[str, Any]] = {}
        self._tombstones: OrderedDict[str, dict[str, str]] = OrderedDict()
        self._closing_all = False
        self._closing_owners: set[str] = set()
        # Turns suspended at a durable wait (an approval) keep their sessions
        # for the resumed frame; a later owner releases them (see _unpark).
        self._parked_owners: set[str] = set()
        if release_context is None:
            from openprogram.runtime.conversation.surface_context import release_bindings
            release_context = release_bindings
        if page_key_resolver is None:
            from openprogram.host.resources.desktop_link import binding_page_key
            page_key_resolver = binding_page_key
        if binding_revision_resolver is None:
            from openprogram.host.resources.desktop_link import binding_revisions
            binding_revision_resolver = binding_revisions
        self._binding_validator_accepts_revisions = binding_validator is None
        if binding_validator is None:
            from openprogram.host.resources.desktop_link import request_bound_tab
            binding_validator = request_bound_tab
        self._release_context = release_context
        self._page_key_resolver = page_key_resolver
        self._binding_revision_resolver = binding_revision_resolver
        self._binding_validator = binding_validator
        self._lock = threading.RLock()

    def park_owner(self, owner_id: str) -> None:
        """Keep one turn's sessions while its execution waits to resume."""
        if owner_id:
            with self._lock:
                self._parked_owners.add(owner_id)

    def _unpark(self, owner_id: str, page_key: str = "") -> None:
        """Release parked owners this caller supersedes.

        A chat runs one turn at a time, so another turn of the same chat
        means the parked one settled without resuming; a parked owner's
        lease on the requested Page also yields to the live caller.
        """
        scope = _owner_scope(owner_id)
        with self._lock:
            if not self._parked_owners:
                return
            leased = self._sessions.get(self._page_leases.get(page_key, "")) if page_key else None
            stale = [
                parked for parked in self._parked_owners
                if parked != owner_id and (
                    (scope.startswith("turn:") and _owner_scope(parked) == scope)
                    or (leased is not None and leased.owner_id == parked)
                )
            ]
        for parked in stale:
            self.release_owner(parked)

    def _hand_over(self, owner_id: str, page_key: str) -> None:
        """Give a Page to another turn of the same chat.

        A chat's turns do not act at once: a spawned agent works while the
        turn that spawned it waits, and a new turn starts after the last one.
        So a Page another turn of this chat holds between actions passes to
        the caller; the holder observes again when it next needs the Page. A
        holder in the middle of an action keeps it (page_in_use).
        """
        scope = _owner_scope(owner_id)
        if not page_key or not scope.startswith("turn:"):
            return
        with self._lock:
            holder = self._sessions.get(self._page_leases.get(page_key, ""))
            if (
                holder is None or holder.owner_id == owner_id
                or holder.closing or holder.closed or holder.inflight_ops
                or _owner_scope(holder.owner_id) != scope
            ):
                return
        if not holder.operation_lock.acquire(blocking=False):
            return
        try:
            if not holder.closing and not holder.closed and not holder.inflight_ops:
                self._cleanup_session(holder, suppress_errors=True)
        finally:
            holder.operation_lock.release()

    def _latest_owner_session_id(self, owner_id: str) -> str:
        if not owner_id:
            return ""
        with self._lock:
            for session in reversed(list(self._sessions.values())):
                if (
                    session.owner_id == owner_id
                    and not session.closing
                    and not session.closed
                ):
                    return session.id
        return ""

    def _remember_locked(
        self, key: str, owner_id: str, target: Mapping[str, str],
    ) -> None:
        window_id = str(target.get("window_id") or "")
        tab_id = str(target.get("tab_id") or "")
        if not key or not owner_id or not window_id or not tab_id:
            return
        self._tombstones[key] = {
            "scope": _owner_scope(owner_id),
            "window_id": window_id,
            "tab_id": tab_id,
        }
        self._tombstones.move_to_end(key)
        while len(self._tombstones) > _TOMBSTONE_LIMIT:
            self._tombstones.popitem(last=False)

    def _gone(
        self, reason_code: str, message: str, *, owner_id: str, keys,
    ) -> dict[str, Any]:
        """Failure for an ended session/token, with its Page when still known.

        The hint names only the exact window/tab the same chat used before.
        A caller may observe that Page again; nothing is replayed.
        """
        result: dict[str, Any] = {
            "ok": False, "reason_code": reason_code, "message": message,
        }
        scope = _owner_scope(owner_id)
        with self._lock:
            for key in keys:
                entry = self._tombstones.get(key) if key else None
                if entry is None or not scope or entry["scope"] != scope:
                    continue
                result.update(
                    recovery_tab_id=entry["tab_id"],
                    recovery_window_id=entry["window_id"],
                    recovery_command="observe",
                )
                break
        return result

    def _detach_locked(self, session: WebUseSession, *, remember: bool = True) -> None:
        self._sessions.pop(session.id, None)
        if remember:
            self._remember_locked(session.id, session.owner_id, _session_target(session))
        for token, capability in list(self._page_capabilities.items()):
            if capability.get("context") is session.page_context:
                self._page_capabilities.pop(token, None)
                if remember:
                    self._remember_locked(
                        token, capability["owner_id"], _capability_target(capability),
                    )

    def _route_token(
        self, token: str, owner_id: str, stale_session_id: str = "",
    ) -> dict[str, Any]:
        """Resolve act/verify/observe that names a Page only by its token."""
        with self._lock:
            capability = self._page_capabilities.get(token)
            if capability is None:
                return {"error": self._gone(
                    "page_context_not_found", _TOKEN_GONE_MESSAGE,
                    owner_id=owner_id, keys=(token, stale_session_id),
                )}
            if capability["owner_id"] != owner_id:
                return {"error": {
                    "ok": False, "reason_code": "page_context_owner_mismatch",
                    "message": _TOKEN_OWNER_MESSAGE,
                }}
            if not capability["consumed"]:
                return {"open": True}
            session = self._sessions.get(str(capability.get("session_id") or ""))
            if session is not None and not session.closing and not session.closed:
                return {"session_id": session.id}
            return {"error": self._gone(
                "page_context_consumed", _TOKEN_GONE_MESSAGE,
                owner_id=owner_id, keys=(token, stale_session_id),
            )}

    def _consumed_token_failure(self, token: str) -> dict[str, Any]:
        with self._lock:
            capability = self._page_capabilities.get(token) or {}
            session = self._sessions.get(str(capability.get("session_id") or ""))
            live = session is not None and not session.closing and not session.closed
        if not live:
            return {"ok": False, "reason_code": "page_context_consumed",
                    "message": _TOKEN_GONE_MESSAGE}
        return {
            "ok": False,
            "reason_code": "page_context_consumed",
            "live_web_session_id": session.id,
            "message": (
                "This page_context_token already opened web_session_id "
                f"{session.id}. Pass that web_session_id instead of the token."
            ),
        }

    def _refresh_frame(self, session: WebUseSession, adapter, guard_args):
        """Observe before a frame-independent action; returns frame_id or a failure.

        The caller has not seen this observation, so its refs stay unusable
        until an explicit observe (see unseen_refs_frame).
        """
        failure = {
            "ok": False,
            "reason_code": "observation_failed",
            "action_dispatched": False,
            "observe_required": True,
            "recovery_command": "observe",
            "message": (
                "The page could not be observed before this action, so nothing "
                "was sent. Call observe on this web_session_id, then retry."
            ),
        }
        try:
            observed = adapter.observe(session, {}, **guard_args)
        except PermissionError:
            raise
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc) == "computer_use_backend_unavailable":
                failure["reason_code"] = "computer_use_backend_unavailable"
            return failure
        frame_id = _result_frame_id(observed)
        if not frame_id:
            if isinstance(observed, dict) and observed.get("reason_code"):
                failure["reason_code"] = str(observed["reason_code"])
            return failure
        session.state["frame_id"] = frame_id
        session.state["unseen_refs_frame"] = frame_id
        session.state.pop("observation_required", None)
        frame = getattr(session.controller, "_frame", None)
        if isinstance(frame, dict) and isinstance(frame.get("viewport"), dict):
            session.state["viewport"] = frame["viewport"]
        return frame_id

    def _cleanup_session(
        self, session: WebUseSession, *, suppress_errors: bool,
        remember: bool = True,
    ) -> None:
        """Close one locked session before making its Page available again."""
        session.closing = True
        with self._lock:
            self._detach_locked(session, remember=remember)
        error: BaseException | None = None
        try:
            self._adapters[session.backend].close(session)
        except BaseException as exc:
            error = exc
        try:
            self._release_context(session.page_context)
        except BaseException as exc:
            if error is None:
                error = exc
        finally:
            session.closed = True
            with self._lock:
                if self._page_leases.get(session.page_key) == session.id:
                    self._page_leases.pop(session.page_key, None)
        if error is not None and not suppress_errors:
            raise error

    def list_pages(self, *, context: dict, owner_id: str) -> dict[str, Any]:
        """Issue opaque, single-use capabilities for exact Page bindings."""
        self._unpark(owner_id)
        pages = []
        with self._lock:
            if self._closing_all or owner_id in self._closing_owners:
                return {"ok": False, "reason_code": "owner_closing", "pages": []}
            primary_surface_key = str(context.get("primary_surface_key") or "")
            surfaces = [
                item for item in context.get("surfaces") or []
                if isinstance(item, dict)
            ]
            surfaces.sort(
                key=lambda item: item.get("surface_key") != primary_surface_key
            )
            for item in surfaces:
                if not item.get("binding_id"):
                    continue
                token = "pct_" + uuid.uuid4().hex
                binding_id = str(item["binding_id"])
                surface_key = str(item.get("surface_key") or "")
                capability_context = {
                    "context_id": str(context.get("context_id") or ""),
                    "window_id": str(
                        item.get("window_id") or context.get("window_id") or ""
                    ),
                    "primary_surface_key": surface_key,
                    "alias_map": {
                        str(alias): surface_key
                        for alias in item.get("aliases") or []
                    },
                    "surfaces": [copy.deepcopy(item)],
                }
                self._page_capabilities[token] = {
                    "owner_id": owner_id,
                    "binding_id": binding_id,
                    "page_key": (
                        str(item.get("page_key") or "")
                        or self._page_key_resolver(binding_id)
                        or binding_id
                    ),
                    "context": capability_context,
                    "page_revision": int(item.get("page_revision") or 0),
                    "access_revision": int(item.get("access_revision") or 0),
                    "geometry_revision": int(item.get("geometry_revision") or 0),
                    "consumed": False,
                }
                pages.append({
                    "page": item.get("surface_key"),
                    "window_id": item.get("window_id") or context.get("window_id") or "",
                    "aliases": list(item.get("aliases") or []),
                    "region": item.get("region"),
                    "title": item.get("title") or "",
                    "origin": item.get("origin") or "",
                    "tab_id": item.get("tab_id") or "",
                    "tab_entry_id": item.get("tab_entry_id") or "",
                    "placement": copy.deepcopy(
                        item.get("placement") or {"mode": "single"}
                    ),
                    "opener_tab_id": item.get("opener_tab_id") or "",
                    "visible": bool(item.get("visible")),
                    "focused": bool(item.get("focused")),
                    "capabilities": list(item.get("capabilities") or []),
                    "page_context_token": token,
                })
        return {
            "ok": True,
            "browser_context_id": str(context.get("context_id") or ""),
            "window_id": str(context.get("window_id") or ""),
            "inventory_revision": int(context.get("inventory_revision") or 0),
            "active_tab_entry_id": str(
                context.get("active_tab_entry_id") or ""
            ),
            "focused_page": str(context.get("focused_page") or ""),
            "tab_entries": copy.deepcopy(context.get("tab_entries") or []),
            "windows": copy.deepcopy(context.get("windows") or []),
            "pages": pages,
        }

    def execute(
        self,
        *,
        command: str,
        backend: str = "",
        web_session_id: str = "",
        binding_id: str = "",
        page_key: str = "",
        owner_id: str = "",
        page_context_token: str = "",
        page_context: dict[str, Any] | None = None,
        arguments: Mapping[str, Any] | None = None,
        before_dispatch: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        params = dict(normalize_web_use_arguments({"arguments": arguments}).get("arguments") or {})
        self._unpark(owner_id)
        if _unresolved_session_id(web_session_id):
            web_session_id = ""
        stale_session_id = ""
        if (
            web_session_id and page_context_token
            and command in {"observe", "act", "verify"}
        ):
            with self._lock:
                known = web_session_id in self._sessions
            if not known:
                # An ended session next to a token: the token names the Page.
                stale_session_id, web_session_id = web_session_id, ""
        implicit_frame = ""
        if not web_session_id and command in {"act", "verify"}:
            if page_context_token:
                # The token names the Page; never fall back to another session.
                routed = self._route_token(
                    page_context_token, owner_id, stale_session_id,
                )
                if "error" in routed:
                    return routed["error"]
                if "session_id" in routed:
                    web_session_id = routed["session_id"]
                else:
                    observed = self.execute(
                        command="observe", backend=backend, owner_id=owner_id,
                        page_context_token=page_context_token,
                        page_context=page_context,
                        **({"before_dispatch": before_dispatch} if before_dispatch is not None else {}),
                    )
                    observed_frame = _result_frame_id(observed)
                    if (
                        not isinstance(observed, dict)
                        or observed.get("ok") is False
                        or observed.get("closed") is True
                        or not observed_frame
                        or not observed.get("web_session_id")
                    ):
                        return observed
                    web_session_id = str(observed["web_session_id"])
                    action = str(params.get("action") or "")
                    uses_ref = bool(str(params.get("ref") or "").strip())
                    if uses_ref or (
                        command == "act" and action not in _REFRESHABLE_ACTIONS
                    ):
                        # Refs and coordinates must come from an observation
                        # the caller has read; return it instead of guessing.
                        return {
                            **observed,
                            "action_performed": False,
                            "message": (
                                "No session was open for this page_context_token, "
                                f"so the page was observed first and the {action or command} "
                                "was not performed. Use refs from this observation and "
                                f"call {command} again with web_session_id {web_session_id}."
                            ),
                        }
                    implicit_frame = observed_frame
            else:
                web_session_id = self._latest_owner_session_id(owner_id)
        created_session = command == "observe" and not web_session_id
        reused_session = False
        if created_session:
            revisions: Mapping[str, int] = {}
            selected = backend or DEFAULT_BACKEND
            if selected not in self._adapters:
                return {"ok": False, "reason_code": "unsupported_backend"}
            if before_dispatch is not None and not getattr(self._adapters[selected], "supports_operation_guard", False):
                return {"ok": False, "reason_code": "guarded_dispatch_unsupported"}
            if page_context_token:
                with self._lock:
                    capability = self._page_capabilities.get(page_context_token)
                    if capability is None:
                        return self._gone(
                            "page_context_not_found", _TOKEN_GONE_MESSAGE,
                            owner_id=owner_id,
                            keys=(page_context_token, stale_session_id),
                        )
                    if capability["owner_id"] != owner_id:
                        return {"ok": False, "reason_code": "page_context_owner_mismatch",
                                "message": _TOKEN_OWNER_MESSAGE}
                    if capability["consumed"]:
                        return self._consumed_token_failure(page_context_token)
                    binding_id = capability["binding_id"]
                    page_key = capability["page_key"]
                    page_context = capability["context"]
                    revisions = {
                        "page_revision": capability["page_revision"],
                        "access_revision": capability["access_revision"],
                        "geometry_revision": capability["geometry_revision"],
                    }
            if not binding_id:
                return {"ok": False, "reason_code": "page_context_required"}
            page_key = page_key or self._page_key_resolver(binding_id) or binding_id
            self._unpark(owner_id, page_key)
            self._hand_over(owner_id, page_key)
            live = self._binding_revision_resolver(binding_id) if revisions else {}
            if live:
                # A new session has no observation to protect yet: navigation or
                # a moved pane since list_pages is what this observe will show.
                # Access granted or revoked since then still counts.
                revisions = {**revisions, **{key: live[key] for key in (
                    "page_revision", "geometry_revision") if key in live}}
            revisions = revisions or self._binding_revision_resolver(binding_id)
            if not revisions and page_context:
                revisions = next((
                    item for item in page_context.get("surfaces") or []
                    if isinstance(item, dict)
                    and item.get("binding_id") == binding_id
                ), {})
            session = WebUseSession(
                id="cs_" + uuid.uuid4().hex,
                backend=selected,
                binding_id=binding_id,
                page_key=page_key,
                page_revision=int(revisions.get("page_revision") or 0),
                access_revision=int(revisions.get("access_revision") or 0),
                geometry_revision=int(revisions.get("geometry_revision") or 0),
                owner_id=owner_id,
                page_context=page_context,
            )
            unused_capability_context = None
            with self._lock:
                if self._closing_all or owner_id in self._closing_owners:
                    return {"ok": False, "reason_code": "owner_closing"}
                leased_session_id = self._page_leases.get(page_key, "")
                leased_session = self._sessions.get(leased_session_id)
                if leased_session_id:
                    if leased_session is None:
                        return {"ok": False, "reason_code": "page_in_use",
                                "message": _PAGE_IN_USE_MESSAGE}
                    if (
                        leased_session.owner_id != owner_id
                        or leased_session.backend != selected
                        or leased_session.closing
                        or leased_session.closed
                    ):
                        return {"ok": False, "reason_code": "page_in_use",
                                "message": _PAGE_IN_USE_MESSAGE}
                    session = leased_session
                    created_session = False
                    reused_session = True
                if page_context_token:
                    capability = self._page_capabilities.get(page_context_token)
                    if capability is None:
                        return self._gone(
                            "page_context_not_found", _TOKEN_GONE_MESSAGE,
                            owner_id=owner_id,
                            keys=(page_context_token, stale_session_id),
                        )
                    if capability["owner_id"] != owner_id:
                        return {"ok": False, "reason_code": "page_context_owner_mismatch",
                                "message": _TOKEN_OWNER_MESSAGE}
                    if capability["consumed"]:
                        return self._consumed_token_failure(page_context_token)
                    if reused_session:
                        unused_capability_context = capability["context"]
                        self._page_capabilities.pop(page_context_token, None)
                    else:
                        capability["consumed"] = True
                        capability["session_id"] = session.id
                if not reused_session:
                    self._sessions[session.id] = session
                    self._page_leases[page_key] = session.id
            if unused_capability_context is not None:
                self._release_context(unused_capability_context)
        else:
            with self._lock:
                session = self._sessions.get(web_session_id)
            if session is None:
                return self._gone(
                    "web_session_not_found", _SESSION_GONE_MESSAGE,
                    owner_id=owner_id, keys=(web_session_id, page_context_token),
                )

        try:
            from openprogram.runtime.execution.run_control import (
                get_current_execution_id,
            )
            from openprogram.programs.applications.browser.pages import attribute_operating_page
            execution_id = get_current_execution_id()
            if execution_id:
                session.state["execution_id"] = execution_id
                attribute_operating_page(session.page_key)
        except Exception:
            # Execution attribution is display bookkeeping; the session works without it.
            _log.debug("browser page not attributed to execution page=%s", session.page_key, exc_info=True)

        follow_receipt = None
        cleaned = False
        with session.operation_lock:
            with self._lock:
                owner_closing = (
                    self._closing_all or session.owner_id in self._closing_owners
                )
            if session.closing or session.closed or owner_closing:
                return self._gone(
                    "web_session_not_found", _SESSION_GONE_MESSAGE,
                    owner_id=owner_id, keys=(session.id, page_context_token),
                )
            if session.owner_id and owner_id != session.owner_id:
                return {"ok": False, "reason_code": "web_session_owner_mismatch"}
            if backend and backend != session.backend:
                return {
                    "ok": False,
                    "reason_code": "backend_mismatch",
                    **_session_fields(session),
                }

            if implicit_frame:
                session.state["unseen_refs_frame"] = implicit_frame
            act_action = str(params.get("action") or "") if command == "act" else ""
            caller_frame = str(params.get("expected_frame_id") or "").strip()
            # Observe first (read-only) for an action that does not depend on
            # what the caller last read: a screenshot or wait whenever there is
            # no current frame, a navigate only when the caller named no frame.
            refresh_first = False
            retry_on_stale = act_action in _READ_ONLY_ACTIONS or (
                act_action in _REFRESHABLE_ACTIONS and not caller_frame
            )
            if command in {"act", "verify"}:
                if session.state.get("observation_required"):
                    if act_action not in _READ_ONLY_ACTIONS:
                        return {"ok": False, "reason_code": "stale_observation",
                                "observe_required": True, "recovery_command": "observe",
                                "message": _STALE_MESSAGE, **_session_fields(session)}
                    refresh_first = True
                elif not caller_frame:
                    frame_id = _session_frame_id(session)
                    if frame_id:
                        params["expected_frame_id"] = frame_id
                    elif act_action in _REFRESHABLE_ACTIONS:
                        refresh_first = True
                expected = str(params.get("expected_frame_id") or "").strip()
                if (
                    not refresh_first
                    and str(params.get("ref") or "").strip()
                    and expected
                    and expected == session.state.get("unseen_refs_frame")
                ):
                    return {"ok": False, "reason_code": "stale_observation",
                            "observe_required": True, "recovery_command": "observe",
                            "message": _UNSEEN_REFS_MESSAGE, **_session_fields(session)}
            if command == "act":
                missing = [
                    name for name in ("action", "expected_frame_id")
                    if (name != "expected_frame_id" or not refresh_first)
                    and (
                        not isinstance(params.get(name), str)
                        or not params[name].strip()
                    )
                ]
                if missing:
                    failure = {
                        "ok": False,
                        "reason_code": "invalid_arguments",
                        "missing_arguments": missing,
                        **_session_fields(session),
                    }
                    if "expected_frame_id" in missing:
                        failure.update(
                            observe_required=True, recovery_command="observe",
                            message=_NO_FRAME_MESSAGE,
                        )
                    return failure

            if command in {"observe", "act", "verify"}:
                revisions = self._binding_revision_resolver(session.binding_id)
                revision_changed = bool(revisions) and ((
                    session.page_revision
                    and int(revisions.get("page_revision") or 0)
                    != session.page_revision
                ) or (
                    session.access_revision
                    and int(revisions.get("access_revision") or 0)
                    != session.access_revision
                ) or (
                    session.geometry_revision
                    and int(revisions.get("geometry_revision") or 0)
                    != session.geometry_revision
                ))
                try:
                    validation = (
                        {"ok": False, "reason_code": "page_context_stale"}
                        if revision_changed
                        else (
                            self._binding_validator(
                                session.binding_id,
                                expected_page_revision=session.page_revision,
                                expected_access_revision=session.access_revision,
                                expected_geometry_revision=session.geometry_revision,
                            )
                            if self._binding_validator_accepts_revisions
                            else self._binding_validator(session.binding_id)
                        )
                    )
                except Exception:
                    validation = {"ok": False, "reason_code": "target_lost"}
                if not validation.get("ok"):
                    reason_code = str(
                        validation.get("reason_code") or "page_context_stale"
                    )
                    if reason_code == "desktop_response_timeout":
                        session.state.pop("frame_id", None)
                        session.state.pop("viewport", None)
                        session.state["observation_required"] = True
                        return {
                            "ok": False, "reason_code": reason_code,
                            "message": "The desktop did not respond in time. No action was dispatched. Observe this session again before acting.",
                            "observe_required": True, "recovery_command": "observe",
                            **_session_fields(session),
                        }
                    recovery_url = session.state.get("last_url") or _controller_display(session).get("target", "")
                    # A session stopped before its first observation still
                    # knows its tab from the page context it was opened with.
                    recovery_identity = session.state.get("page_identity") or next((
                        item for item in (session.page_context or {}).get("surfaces") or []
                        if isinstance(item, dict) and item.get("binding_id") == session.binding_id
                    ), {})
                    self._cleanup_session(session, suppress_errors=True)
                    return {
                        "ok": False,
                        "reason_code": reason_code,
                        "message": "The page changed or closed. Observe the page again before acting.",
                        "recovery_url": recovery_url,
                        "recovery_tab_id": recovery_identity.get("tab_id", ""),
                        "recovery_window_id": recovery_identity.get("window_id", ""),
                        "recovery_command": "observe",
                        **_session_fields(session),
                    }

            adapter = self._adapters[session.backend]
            # Task execution owns pause/cancel; page events never prohibit writes.
            combined_guard = before_dispatch
            use_guard = before_dispatch is not None
            guard_args = {}
            if use_guard:
                if not getattr(adapter, "supports_operation_guard", False):
                    return {"ok": False, "reason_code": "guarded_dispatch_unsupported"}
                guard_args["before_dispatch"] = before_dispatch
            dispatched_op_id = None
            try:
                if use_guard:
                    combined_guard()
                elif before_dispatch is not None:
                    before_dispatch()
                refreshed = (
                    self._refresh_frame(session, adapter, guard_args)
                    if command == "act" and refresh_first else None
                )
                if isinstance(refreshed, dict):
                    # The read-only observation failed; nothing was dispatched.
                    result = refreshed
                elif command == "observe":
                    result = adapter.observe(session, params, **guard_args)
                    frame = getattr(session.controller, "_frame", None)
                    if isinstance(frame, dict) and isinstance(frame.get("viewport"), dict):
                        session.state["viewport"] = frame["viewport"]
                elif command == "act":
                    from openprogram.programs.applications.browser.pages import (
                        report_browser_operation, sanitize_operation,
                    )
                    from openprogram.runtime.execution.run_control import (
                        get_current_execution_id,
                    )
                    if refreshed:
                        params["expected_frame_id"] = refreshed
                    dispatched_op_id = "op_" + uuid.uuid4().hex[:12]
                    pre_frame = _session_frame_id(session)
                    viewport = _session_viewport(session)
                    execution_id = get_current_execution_id()
                    dispatched = sanitize_operation(
                        action=str(params.get("action") or ""),
                        arguments=params, result={"ok": True},
                        frame_id=pre_frame,
                        geometry_revision=session.geometry_revision,
                        phase="dispatched", operation_id=dispatched_op_id,
                        viewport=viewport,
                    )
                    session.inflight_ops = int(getattr(session, "inflight_ops", 0) or 0) + 1
                    try:
                        try:
                            report_browser_operation(
                                session.page_key, dispatched, follow=True,
                                execution_id=execution_id,
                            )
                        except Exception:
                            # The dispatched receipt is display-only; the action still runs.
                            _log.debug("browser operation receipt not reported page=%s", session.page_key, exc_info=True)
                        result = adapter.act(session, params, **guard_args)
                        if (
                            retry_on_stale and not refresh_first
                            and _reason_code(result) == "stale_observation"
                        ):
                            # The frame changed underneath an action that does
                            # not depend on it, and the stale check sent
                            # nothing. Observe (read-only) and try once more.
                            retried = self._refresh_frame(session, adapter, guard_args)
                            if isinstance(retried, dict):
                                result = retried
                            else:
                                params["expected_frame_id"] = retried
                                pre_frame = retried
                                result = adapter.act(session, params, **guard_args)
                    finally:
                        session.inflight_ops = max(
                            0, int(getattr(session, "inflight_ops", 0) or 0) - 1,
                        )
                    failed = isinstance(result, dict) and result.get("ok") is False
                    follow_receipt = [(
                        session.page_key,
                        sanitize_operation(
                            action=str(params.get("action") or ""),
                            arguments=params, result=result,
                            frame_id=pre_frame or _result_frame_id(result),
                            geometry_revision=session.geometry_revision,
                            phase="failed" if failed else "acknowledged",
                            operation_id=dispatched_op_id,
                            viewport=viewport,
                        ),
                        not failed,
                        execution_id,
                    )]
                elif command == "verify":
                    result = adapter.verify(session, params, **guard_args)
                elif command == "close":
                    # A caller-closed session is not offered for re-observation.
                    self._cleanup_session(
                        session, suppress_errors=False, remember=False,
                    )
                    result = {"ok": True, "closed": True}
                else:
                    return {"ok": False, "reason_code": "invalid_command"}
            except PermissionError:
                if command == "observe" and not session.closing:
                    self._cleanup_session(session, suppress_errors=True)
                raise
            except BaseException as exc:
                if command == "observe" and not session.closing:
                    self._cleanup_session(session, suppress_errors=True)
                    if (
                        session.backend in {"playwright_mcp", "chrome_devtools_mcp"}
                        and isinstance(exc, RuntimeError)
                        and str(exc) == "computer_use_backend_unavailable"
                    ):
                        return {
                            "ok": False,
                            "reason_code": "computer_use_backend_unavailable",
                            "availability": "unavailable",
                            "message": (
                                f"The {session.backend} browser backend could not start "
                                "or connect, so the page was not observed and no action "
                                "was sent. Call observe for this page again to retry; "
                                "every attempt starts the backend fresh."
                            ),
                            **_session_fields(session),
                        }
                    raise
                if not isinstance(exc, Exception):
                    raise
                if command != "act":
                    raise
                controller = session.controller
                invalidate = getattr(controller, "invalidate_external_frame", None)
                if callable(invalidate):
                    with suppress(Exception):
                        invalidate()
                result = {
                    "ok": False,
                    "reason_code": (
                        "timeout" if _is_timeout_error(exc)
                        else "backend_action_failed"
                    ),
                    "observe_required": True,
                }
                if dispatched_op_id:
                    from openprogram.programs.applications.browser.pages import sanitize_operation
                    from openprogram.runtime.execution.run_control import (
                        get_current_execution_id,
                    )
                    follow_receipt = [(
                        session.page_key,
                        sanitize_operation(
                            action=str(params.get("action") or ""),
                            arguments=params, result=result,
                            frame_id=_session_frame_id(session),
                            geometry_revision=session.geometry_revision,
                            phase="failed", operation_id=dispatched_op_id,
                            viewport=_session_viewport(session),
                        ),
                        False,
                        get_current_execution_id(),
                    )]

            if (
                command == "act" and isinstance(result, dict)
                and result.get("ok") is True and result.get("observe_required") is True
            ):
                # The write replaced the frame; never auto-fill the old one.
                session.state.pop("frame_id", None)
                session.state.pop("unseen_refs_frame", None)
            frame_id = _result_frame_id(result)
            if frame_id:
                session.state["frame_id"] = frame_id
                if command == "observe":
                    session.state.pop("observation_required", None)
                    session.state.pop("unseen_refs_frame", None)
            if (
                command in {"act", "verify"} and isinstance(result, dict)
                and result.get("ok") is False and not result.get("message")
            ):
                reason = result.get("reason_code")
                if reason == "stale_observation":
                    result = {**result, "observe_required": True,
                              "recovery_command": "observe", "message": _STALE_MESSAGE}
                elif reason == "screenshot_already_captured":
                    result = {**result, "recovery_command": "observe", "message": (
                        "This frame already has its one screenshot. Call observe "
                        "for a new frame before taking another screenshot."
                    )}
            cleaned = bool(created_session and not frame_id)
            if cleaned:
                self._cleanup_session(session, suppress_errors=True)

        if follow_receipt:
            from openprogram.programs.applications.browser.pages import report_browser_operation
            for page_key, operation, follow, execution_id in follow_receipt:
                try:
                    report_browser_operation(
                        page_key, operation, follow=follow, execution_id=execution_id,
                    )
                except Exception:
                    # The follow receipt is display-only; the action's result stands.
                    _log.debug("browser operation receipt not reported page=%s", page_key, exc_info=True)

        failed = isinstance(result, dict) and result.get("ok") is False
        if command in {"observe", "act"} and not failed and not cleaned:
            _publish_bound_page(session, result)
        if command in {"observe", "act"} and not failed and isinstance(result, dict):
            from openprogram.programs.applications.browser.pages import take_opened_pages
            opened = take_opened_pages(session.page_key)
            if opened:
                # A popup is a separate Page. Without this the Agent kept
                # working in the opener and started the same flow twice.
                result = {
                    **result, "opened_pages": opened,
                    "opened_pages_note": (
                        "This page opened the page(s) listed in opened_pages. "
                        "Continue the flow there: call web_use list_pages and observe "
                        "the page with that tab_id. Do not start the same flow again "
                        "in this page."
                    ),
                }
        if command == "observe" and not failed and not cleaned:
            # Looking at a Page is working on it: the conversation preview
            # follows reads too, not only clicks and typing. After publish, so
            # a Page opened by this observe already has its row.
            try:
                from openprogram.programs.applications.browser.pages import (
                    report_browser_operation, sanitize_operation,
                )
                from openprogram.runtime.execution.run_control import (
                    get_current_execution_id,
                )
                report_browser_operation(
                    session.page_key,
                    sanitize_operation(
                        action="observe", arguments={}, result=result,
                        frame_id=_result_frame_id(result),
                        geometry_revision=session.geometry_revision,
                        phase="acknowledged",
                    ),
                    follow=False, execution_id=get_current_execution_id(),
                )
            except Exception:
                # The observe receipt is display-only; the result is returned regardless.
                _log.debug("browser observe receipt not reported page=%s", session.page_key, exc_info=True)

        if isinstance(result, ToolReturn):
            metadata = (
                dict(result.json_data) if isinstance(result.json_data, dict) else {}
            )
            metadata.update(_session_fields(session, reused=reused_session))
            result.json_data = metadata
            return result
        payload = dict(result) if isinstance(result, dict) else {"result": result}
        payload.update(_session_fields(session, reused=reused_session))
        return payload

    def close_all(self) -> None:
        with self._lock:
            if self._closing_all:
                return
            self._closing_all = True
            sessions = list(self._sessions.values())
            capabilities = [
                value for value in self._page_capabilities.values()
                if not value["consumed"]
            ]
            self._page_capabilities.clear()
        released = set()
        try:
            for session in sessions:
                with session.operation_lock:
                    if not session.closed:
                        self._cleanup_session(session, suppress_errors=True)
                    released.add(id(session.page_context))
            for capability in capabilities:
                context = capability["context"]
                key = id(context)
                if key not in released:
                    with suppress(Exception):
                        self._release_context(context)
                    released.add(key)
        finally:
            with self._lock:
                self._closing_all = False

    def release_page_capabilities(
        self, tokens: list[str], *, owner_id: str,
    ) -> int:
        """Release only unconsumed capabilities issued to one owner."""
        capabilities = []
        with self._lock:
            for token in dict.fromkeys(tokens):
                value = self._page_capabilities.get(token)
                if (
                    value is None
                    or value["owner_id"] != owner_id
                    or value["consumed"]
                ):
                    continue
                self._page_capabilities.pop(token, None)
                self._remember_locked(token, owner_id, _capability_target(value))
                capabilities.append(value)
        released = set()
        for capability in capabilities:
            context = capability["context"]
            key = id(context)
            if key in released:
                continue
            with suppress(Exception):
                self._release_context(context)
            released.add(key)
        return len(capabilities)

    def invalidate_page_frames(self, page_key: str) -> None:
        with self._lock:
            sessions = [item for item in self._sessions.values() if item.page_key == page_key]
        for session in sessions:
            with session.operation_lock:
                session.state.pop("frame_id", None)
                session.state.pop("viewport", None)
                controller = session.controller
                if controller is None:
                    continue
                invalidate = getattr(controller, "invalidate_external_frame", None)
                if callable(invalidate):
                    with suppress(Exception):
                        invalidate()
                    continue
                controller._frame = None
                if hasattr(controller, "_screenshot_frame"):
                    controller._screenshot_frame = ""
                if hasattr(controller, "_screenshot_viewport"):
                    controller._screenshot_viewport = None

    def revoke_screenshot(self, web_session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(web_session_id)
        if session is None:
            return
        with session.operation_lock:
            if session.closing or session.closed or session.controller is None:
                return
            revoke = getattr(session.controller, "revoke_screenshot", None)
            if callable(revoke):
                revoke()

    def release_owner(self, owner_id: str, *, strict: bool = False) -> None:
        """Release every session and unconsumed Page capability for one caller."""
        with self._lock:
            if owner_id in self._closing_owners:
                return
            self._parked_owners.discard(owner_id)
            self._closing_owners.add(owner_id)
            sessions = [s for s in self._sessions.values() if s.owner_id == owner_id]
            capabilities = []
            for token, value in list(self._page_capabilities.items()):
                if value["owner_id"] != owner_id:
                    continue
                self._page_capabilities.pop(token, None)
                # A later turn of the same chat may still name this token;
                # keep only its exact Page so that call can observe it again.
                self._remember_locked(token, owner_id, _capability_target(value))
                if not value["consumed"]:
                    capabilities.append(value)
        page_keys = [session.page_key for session in sessions if session.page_key]
        released = set()
        errors = []
        try:
            for session in sessions:
                try:
                    with session.operation_lock:
                        if not session.closed:
                            self._cleanup_session(session, suppress_errors=not strict)
                except BaseException as exc:
                    if not strict:
                        raise
                    errors.append(exc)
                released.add(id(session.page_context))
            for capability in capabilities:
                context = capability["context"]
                key = id(context)
                if key not in released:
                    try:
                        self._release_context(context)
                    except BaseException as exc:
                        if strict:
                            errors.append(exc)
                        elif not isinstance(exc, Exception):
                            raise
                    released.add(key)
        finally:
            with self._lock:
                self._closing_owners.discard(owner_id)
        try:
            from openprogram.programs.applications.browser.pages import reconcile_resource_control
            for page_key in dict.fromkeys(page_keys):
                reconcile_resource_control(page_key)
        except Exception:
            # Resource-control reconcile is bookkeeping the next operation redoes.
            _log.debug("browser resource control not reconciled owner=%s", owner_id, exc_info=True)

        if errors:
            raise errors[0]


_registry: WebUseSessionRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> WebUseSessionRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = WebUseSessionRegistry()
        return _registry


def release_owner_if_initialized(owner_id: str) -> None:
    """Release a turn owner without creating Web Use state for ordinary turns."""
    with _registry_lock:
        registry = _registry
    if registry is not None:
        registry.release_owner(owner_id)


def park_owner_if_initialized(owner_id: str) -> None:
    """Keep a suspended turn's sessions for the frame that resumes it."""
    with _registry_lock:
        registry = _registry
    if registry is not None:
        registry.park_owner(owner_id)


__all__ = [
    "WebUseSessionRegistry",
    "DEFAULT_BACKEND",
    "SUPPORTED_BACKENDS",
    "get_registry",
    "park_owner_if_initialized",
    "release_owner_if_initialized",
]
