"""Private official-MCP adapters restricted to one exact Electron Page."""
from __future__ import annotations

import asyncio
import os
import re
import threading
import uuid
from contextlib import suppress
from typing import Any, Callable, Mapping

from openprogram.extensions.mcp.client import MCPClient
from . import page_actions as pa
from openprogram.extensions.mcp.config import MCPServerConfig
import logging

_log = logging.getLogger(__name__)


_PLAYWRIGHT_MCP_VERSION = "0.0.79"
_CHROME_DEVTOOLS_MCP_VERSION = "1.7.0"
# Both packages are pinned to exact versions, so a cached copy is already the
# right one. Without --prefer-offline npx revalidates the manifest against the
# registry on every launch; on a slow or broken network that alone outlasts
# the MCP start timeout and the backend never starts.
_NPX_PREFIX = ("npx", "--prefer-offline", "-y")


def _result_text(result: Any) -> str:
    lines = []
    for item in getattr(result, "content", ()) or ():
        text = getattr(item, "text", None)
        if isinstance(text, str):
            lines.append(text)
    return "\n".join(lines)


def _structured(result: Any) -> dict[str, Any]:
    value = getattr(result, "structuredContent", None)
    if value is None:
        value = getattr(result, "structured_content", None)
    return value if isinstance(value, dict) else {}


# One snapshot line names a role and a ref: Playwright MCP writes
# `- checkbox "Agree" [ref=e85]`, Chrome DevTools MCP `uid=1_5 checkbox "Agree"`.
_PLAYWRIGHT_REF_LINE = re.compile(r"^\s*-\s+([a-z]+)\b[^\n]*?\[ref=([^\]\s]+)\]", re.MULTILINE)
_DEVTOOLS_REF_LINE = re.compile(r"^\s*uid=(\S+)\s+([a-z]+)\b", re.MULTILINE)


def snapshot_roles(text: str) -> dict[str, str]:
    """The role of each ref in an upstream snapshot."""
    roles = {ref: role for role, ref in _PLAYWRIGHT_REF_LINE.findall(text or "")}
    roles.update(_DEVTOOLS_REF_LINE.findall(text or ""))
    return roles


def _is_error(result: Any) -> bool:
    return bool(
        getattr(result, "isError", False)
        or getattr(result, "is_error", False)
    )


async def _cancel_pending_tasks(timeout: float = 6.0) -> None:
    current = asyncio.current_task()
    pending = [
        task for task in asyncio.all_tasks()
        if task is not current and not task.done()
    ]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending, timeout=timeout)


class _SyncMCPClient:
    """Keep the async MCP supervisor alive on one private event loop."""

    def __init__(self, command: list[str], *, timeout: float = 30.0,
                 env: dict[str, str] | None = None) -> None:
        self._loop = asyncio.new_event_loop()
        self._client = None
        self._thread = threading.Thread(
            target=self._run, name="web-use-mcp", daemon=True,
        )
        self._thread.start()
        try:
            self._client = MCPClient(MCPServerConfig(
                name="web-use-private",
                command=command,
                env=dict(env or {}),
                timeout_seconds=timeout,
            ))
            self._submit(self._client.start(), timeout + 5)
            if self._client.error:
                raise RuntimeError("computer_use_backend_unavailable")
        except BaseException:
            self.close()
            raise

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, awaitable, timeout: float = 35.0):
        future = asyncio.run_coroutine_threadsafe(awaitable, self._loop)
        return future.result(timeout=timeout)

    def call(self, name: str, arguments: dict[str, Any]):
        return self._submit(self._client.call_tool(name, arguments))

    def is_alive(self) -> bool:
        """True while the private loop runs and the MCP session is usable.

        A supervisor that gave up (fatal or re-auth), a dropped session that is
        still reconnecting, or a stopped loop all count as dead: the caller
        replaces the client instead of sending a write into it.
        """
        client = self._client
        if client is None or not self._thread.is_alive() or not self._loop.is_running():
            return False
        if getattr(client, "error", None):
            return False
        ready = getattr(client, "is_ready", None)
        return True if ready is None else bool(ready)

    def close(self) -> None:
        client = getattr(self, "_client", None)
        if client is not None and self._loop.is_running():
            try:
                self._submit(client.stop(), 5)
            except Exception:
                # Teardown: the MCP client may already be dead; the loop is stopped below regardless.
                _log.debug("MCP client stop failed", exc_info=True)
        if self._loop.is_running():
            # A start that timed out leaves the supervisor (and its npx child)
            # pending. Cancel and await it on this loop so the stdio transport
            # terminates the child before the loop closes; otherwise the child
            # outlives the loop that owns its pipes.
            try:
                self._submit(_cancel_pending_tasks(), 8)
            except Exception:
                # Teardown: best-effort cancel; the loop is stopped below regardless.
                _log.debug("MCP pending task cancel failed", exc_info=True)
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)
        if not self._thread.is_alive():
            self._loop.close()


class OfficialMCPPageBackend:
    supports_operation_guard = True

    def __init__(
        self,
        name: str,
        controller_factory: Callable[[], Any],
        *,
        client_factory: Callable[[list[str]], Any] = _SyncMCPClient,
    ) -> None:
        self.name = name
        self._controller_factory = controller_factory
        self._client_factory = client_factory

    def _controller(self, session):
        if session.controller is None:
            controller = self._controller_factory()
            controller.binding_id = session.binding_id
            controller.page_revision = session.page_revision
            controller.access_revision = session.access_revision
            controller.geometry_revision = session.geometry_revision
            session.controller = controller
        return session.controller

    def _command(self, endpoint: str, target_id: str = "") -> list[str]:
        if self.name == "playwright_mcp":
            bridge = os.path.join(os.path.dirname(__file__), "playwright_exact_page_mcp.cjs")
            return [
                *_NPX_PREFIX, "--package",
                f"@playwright/mcp@{_PLAYWRIGHT_MCP_VERSION}", "--", "sh", "-c",
                'export NODE_PATH="$(dirname "$(dirname "$(command -v playwright-mcp)")")"; '
                'exec node "$1" "$2" "$3"',
                "openprogram-playwright-mcp", bridge, endpoint, target_id,
            ]
        return [
            *_NPX_PREFIX,
            f"chrome-devtools-mcp@{_CHROME_DEVTOOLS_MCP_VERSION}",
            "--wsEndpoint", endpoint,
            "--experimentalPageIdRouting",
            "--experimentalStructuredContent",
            "--experimentalVision",
            "--no-usage-statistics",
            "--no-category-performance",
            "--no-category-network",
            "--no-category-emulation",
        ]

    @staticmethod
    def _client_alive(client) -> bool:
        probe = getattr(client, "is_alive", None)
        if not callable(probe):
            return True
        try:
            return bool(probe())
        except Exception:
            return False

    def _drop_dead_client(self, session) -> bool:
        """Discard a stopped private MCP client; True when one was dropped."""
        existing = session.state.get("mcp_client")
        if existing is None or self._client_alive(existing):
            return False
        session.state.pop("mcp_client", None)
        session.state.pop("upstream_page", None)
        with suppress(Exception):
            existing.close()
        return True

    def _ensure_bound(self, session) -> Any:
        # Only observe starts a replacement client: the restart is read-only
        # and rebinds the same exact target. act never writes through a client
        # it had to restart (see act).
        self._drop_dead_client(session)
        existing = session.state.get("mcp_client")
        if existing is not None:
            return existing
        controller = self._controller(session)
        target_id = str(session.state.get("target_id") or "")
        if self.name == "playwright_mcp":
            if not target_id:
                raise RuntimeError("exact_page_not_found")
            from openprogram.programs.applications.browser.chrome import (
                desktop_app_ws_url,
            )
            endpoint = desktop_app_ws_url()
            if not endpoint:
                raise RuntimeError("computer_use_backend_unavailable")
            client = self._client_factory(self._command(endpoint, target_id))
            session.state["mcp_client"] = client
            session.state["upstream_page"] = 0
            return client

        marker_name = "__openprogram_mcp_" + uuid.uuid4().hex
        marker_value = uuid.uuid4().hex
        controller.evaluate_bound_page(
            "([name, value]) => Object.defineProperty(globalThis, name, "
            "{value, configurable: true})",
            [marker_name, marker_value],
        )
        from openprogram.programs.applications.browser.chrome import (
            desktop_app_ws_url,
        )
        client = None
        try:
            endpoint = desktop_app_ws_url()
            if not endpoint:
                raise RuntimeError("computer_use_backend_unavailable")
            client = self._client_factory(self._command(endpoint))
            selected = self._bind_chrome(client, marker_name, marker_value)
            if selected is None:
                raise RuntimeError("exact_page_not_found")
            session.state["mcp_client"] = client
            session.state["upstream_page"] = selected
            return client
        except BaseException:
            if client is not None:
                client.close()
            raise
        finally:
            try:
                controller.evaluate_bound_page(
                    "name => delete globalThis[name]", marker_name,
                )
            except Exception:
                # Teardown: the bound page may already be gone, taking the marker with it.
                _log.debug("bound page marker %s not removed", marker_name, exc_info=True)

    def _bind_chrome(self, client, marker_name: str, marker_value: str):
        listed = client.call("list_pages", {})
        pages = _structured(listed).get("pages") or []
        expression = f"() => globalThis[{marker_name!r}] || null"
        for page in pages:
            page_id = page.get("id") if isinstance(page, dict) else None
            if not isinstance(page_id, int):
                continue
            result = client.call(
                "evaluate_script", {"function": expression, "pageId": page_id},
            )
            if marker_value in _result_text(result):
                return page_id
        return None

    def observe(self, session, arguments: Mapping[str, Any], *, before_dispatch=None):
        controller = self._controller(session)
        identity = controller.execute(
            action="observe",
            **({"before_dispatch": before_dispatch} if before_dispatch is not None else {}),
        )
        if not isinstance(identity, dict) or "frame_id" not in identity:
            return identity
        target = identity.get("target") if isinstance(identity.get("target"), dict) else {}
        session.state["target_id"] = str(target.get("target_id") or "")
        client = self._ensure_bound(session)
        def capture():
            if before_dispatch is not None:
                before_dispatch()
            if self.name == "playwright_mcp":
                upstream = client.call("browser_snapshot", {})
            else:
                upstream = client.call(
                    "take_snapshot",
                    {"pageId": session.state["upstream_page"]},
                )
            if _is_error(upstream):
                raise RuntimeError("backend_observation_failed")
            return _result_text(upstream)
        upstream_text = controller.capture_observation(capture)
        session.state["frame_id"] = identity["frame_id"]
        session.state["ref_roles"] = snapshot_roles(upstream_text)
        # File capabilities are issued by the same controller that reads and
        # transmits the bytes. Never reinterpret an upstream eN/uid as a native
        # ref, or resolve a file input by its label/order after observation.
        file_refs = {}
        file_elements = []
        for element in identity.get("elements") or []:
            if element.get("input_type") != "file":
                continue
            public_ref = "file_" + uuid.uuid4().hex
            file_refs[public_ref] = str(element["ref"])
            file_elements.append({**element, "ref": public_ref,
                                  "ref_backend": "native_file"})
        session.state["file_refs"] = file_refs
        session.state["file_refs_frame"] = identity["frame_id"]
        return {
            **identity,
            "elements": file_elements,
            "file_input_instruction": (
                "For upload and file_selected verification, use only the file_ "
                "refs in elements with this frame_id. Do not click Choose File "
                "first or use MCP snapshot refs for uploads. File selection "
                "does not prove server acceptance."
            ),
            "aria_snapshot": upstream_text,
            "backend_observation": self.name,
        }

    def _evaluate(self, session, ref: str, function: str):
        """Run ``function`` in the page, on the element ``ref`` names when given."""
        if self.name == "playwright_mcp":
            return "browser_evaluate", {**({"target": ref} if ref else {}), "function": function}
        return "evaluate_script", {"pageId": session.state["upstream_page"], "function": function,
                                   **({"args": [ref]} if ref else {})}

    def _action_call(self, session, arguments: Mapping[str, Any]):
        """The upstream tool call for one act, or None for an action this backend lacks.

        Raises ``ActionError`` for options the backend cannot honour, so the
        call fails before anything is sent instead of doing something weaker.
        """
        action = str(arguments.get("action") or "")
        ref = str(arguments.get("ref") or "").lstrip("@")
        options = dict(arguments)
        playwright = self.name == "playwright_mcp"
        page_id = None if playwright else session.state["upstream_page"]

        def unsupported(what: str):
            raise pa.ActionError("unsupported_option", f"{what} is not available on the {self.name} backend")

        if action == "click":
            click = pa.click_options(options)
            if ref:
                if playwright:
                    if click["count"] == 3:
                        unsupported("a triple click")
                    # Only what differs from a plain click, so a plain one stays the minimal call.
                    return "browser_click", {
                        "target": ref,
                        **({"doubleClick": True} if click["count"] == 2 else {}),
                        **({"button": click["button"]} if click["button"] != "left" else {}),
                        **({"modifiers": click["modifiers"]} if click["modifiers"] else {})}
                if pa.is_plain_click(click) or (click["count"] == 2 and click["button"] == "left"
                                                and not click["modifiers"]):
                    return "click", {"uid": ref, "pageId": page_id, **({"dblClick": True} if click["count"] == 2 else {})}
                return self._evaluate(session, ref, pa.bound_call(pa.POINTER_SCRIPT, {
                    "button": click["button"], "count": click["count"], "flags": click["flags"]}))
            if click["modifiers"]:
                unsupported("a coordinate click with modifiers")
            if playwright:
                return "browser_mouse_click_xy", {"x": arguments.get("x"), "y": arguments.get("y"),
                                                  "button": click["button"], "clickCount": click["count"]}
            if not pa.is_plain_click(click):
                unsupported("a coordinate click other than a single left click")
            return "click_at", {"x": arguments.get("x"), "y": arguments.get("y"), "pageId": page_id}
        if action == "drag":
            to_ref = str(arguments.get("to_ref") or "").lstrip("@")
            if ref and to_ref:
                return (("browser_drag", {"startTarget": ref, "endTarget": to_ref}) if playwright
                        else ("drag", {"from_uid": ref, "to_uid": to_ref, "pageId": page_id}))
            if ref or to_ref:
                unsupported("a drag between a ref and a point")
            if any(arguments.get(key) is None for key in ("x", "y", "to_x", "to_y")):
                raise pa.ActionError("invalid_arguments", "drag needs ref and to_ref, or x, y, to_x and to_y")
            if not playwright:
                unsupported("a coordinate drag")
            return "browser_mouse_drag_xy", {"startX": arguments.get("x"), "startY": arguments.get("y"),
                                             "endX": arguments.get("to_x"), "endY": arguments.get("to_y")}
        if action == "scroll":
            dx, dy = pa.scroll_delta(options)
            if ref:
                return self._evaluate(session, ref, pa.bound_call(pa.SCROLL_SCRIPT, {"dx": dx, "dy": dy},
                                                                  require="moved"))
            if playwright:
                return "browser_mouse_wheel", {"deltaX": dx, "deltaY": dy}
            return self._evaluate(session, "", f"() => window.scrollBy({dx}, {dy})")
        if action == "type_text":
            text = arguments.get("text")
            if not isinstance(text, str) or not text:
                raise pa.ActionError("text_required", "type_text needs text")
            return self._evaluate(session, ref, pa.bound_call(
                pa.INSERT_TEXT_SCRIPT, {"text": text}, with_element=bool(ref), require="ok"))
        if action == "paste":
            return self._evaluate(session, ref, pa.bound_call(
                pa.PASTE_SCRIPT, pa.paste_payload(options), with_element=bool(ref), require="ok"))
        if action == "select_text":
            if not ref:
                raise pa.ActionError("ref_not_found", "select_text needs the ref of the element holding the text")
            return self._evaluate(session, ref, pa.bound_call(
                pa.SELECT_TEXT_SCRIPT, pa.selection_request(options), require="ok"))
        if action == "press":
            if pa.hold_seconds(options):
                unsupported("holding a key")
            return (("browser_press_key", {"key": arguments.get("key")}) if playwright
                    else ("press_key", {"key": arguments.get("key"), "pageId": page_id}))
        if action in ("back", "forward", "reload"):
            if not playwright:
                return "navigate_page", {"type": action, "pageId": page_id}
            if action == "back":
                return "browser_navigate_back", {}
            return self._evaluate(session, "", "() => history.forward()" if action == "forward"
                                  else "() => location.reload()")
        if playwright:
            mapping = {
                "type": ("browser_type", {
                    "target": ref, "text": str(arguments.get("text") or ""),
                }),
                "hover": ("browser_hover", {"target": ref}),
                "select": ("browser_select_option", {
                    "target": ref, "values": [str(arguments.get("value") or "")],
                }),
                "navigate": ("browser_navigate", {"url": arguments.get("url")}),
            }
        else:
            mapping = {
                "type": ("fill", {
                    "uid": ref, "value": str(arguments.get("text") or ""),
                    "pageId": page_id,
                }),
                "hover": ("hover", {"uid": ref, "pageId": page_id}),
                "select": ("fill", {
                    "uid": ref, "value": str(arguments.get("value") or ""),
                    "pageId": page_id,
                }),
                "navigate": ("navigate_page", {
                    "type": "url", "url": arguments.get("url"),
                    "pageId": page_id,
                }),
            }
        return mapping.get(action)

    def act(self, session, arguments: Mapping[str, Any], *, before_dispatch=None):
        controller = self._controller(session)
        frame_id = str(arguments.get("expected_frame_id") or "")
        action = str(arguments.get("action") or "")
        if action == "upload":
            params, error = self._file_arguments(session, arguments)
            if error is not None:
                return error
            return controller.execute(
                **params,
                **({"before_dispatch": before_dispatch} if before_dispatch is not None else {}),
            )
        if str(arguments.get("ref") or "").lstrip("@").startswith("file_"):
            return {"ok": False, "reason_code": "file_ref_action_required",
                    "message": "File refs support upload and file_selected verification only."}
        if action == pa.EVALUATE_ACTION or action in ("console_messages", "network_requests"):
            # Through the controller's handle on the same tab, so the result
            # is redacted like an observation.
            return controller.execute(
                action=action, expected_frame_id=frame_id,
                **{key: arguments[key] for key in ("script", "pattern", "only_errors", "limit") if key in arguments},
                **({"before_dispatch": before_dispatch} if before_dispatch is not None else {}),
            )
        if action in {"screenshot", "wait"}:
            return controller.execute(
                action=action, expected_frame_id=frame_id,
                **({"amount": arguments["amount"]} if action == "wait" and "amount" in arguments else {}),
                **({"before_dispatch": before_dispatch} if before_dispatch is not None else {}),
            )
        rejected = controller.prepare_external_action(arguments)
        if rejected is not None:
            return rejected
        scale = 1.0
        if action in {"click", "hover", "scroll", "drag"}:
            get_scale = getattr(controller, "pointer_scale", None)
            scale = get_scale() if callable(get_scale) else 1.0
            if scale is None:
                return controller.invalidate_external_frame()
        try:
            call = self._action_call(session, arguments)
            click = pa.click_options(dict(arguments)) if action == "click" else None
        except pa.ActionError as exc:
            return exc.result()
        hover_attribute = None
        ref = str(arguments.get("ref") or "").lstrip("@")
        if call is not None and scale != 1:
            name, params = call
            if action == "click" and not ref:
                params = {**params, "x": float(arguments["x"]) * scale,
                          "y": float(arguments["y"]) * scale}
            elif action == "drag" and name == "browser_mouse_drag_xy":
                params = {key: float(value) * scale for key, value in params.items()}
            elif action == "click" and ref and not pa.is_plain_click(click):
                # A bound tab stays in the background: dispatch the events in the page.
                name, params = self._evaluate(session, ref, pa.bound_call(pa.POINTER_SCRIPT, {
                    "button": click["button"], "count": click["count"], "flags": click["flags"]}))
            elif action in {"click", "hover"} and ref:
                if action == "click":
                    from . import _BACKGROUND_REF_CLICK_SCRIPT
                    script = _BACKGROUND_REF_CLICK_SCRIPT
                else:
                    hover_attribute = "data-openprogram-pointer-" + uuid.uuid4().hex
                    script = f"(element) => element.setAttribute('{hover_attribute}', '')"
                name, params = (
                    ("browser_evaluate", {"target": ref, "function": script})
                    if self.name == "playwright_mcp" else
                    ("evaluate_script", {"pageId": session.state["upstream_page"],
                                         "args": [ref], "function": script})
                )
            call = name, params
        if call is None:
            return {"ok": False, "reason_code": "unsupported_action"}
        if self._drop_dead_client(session):
            # The private MCP process stopped after the last observe. Its refs
            # stopped with it, so never send this write through a new process.
            controller.invalidate_external_frame()
            return {
                "ok": False,
                "reason_code": "computer_use_backend_unavailable",
                "action_dispatched": False,
                "observe_required": True,
                "recovery_command": "observe",
                "message": (
                    f"The {self.name} browser backend stopped after the last "
                    "observation. The action was not sent. Call observe on this "
                    "web_session_id (it restarts the backend), then retry the "
                    "action with refs from that observation."
                ),
            }
        client = self._ensure_bound(session)
        set_cursor = getattr(controller, "set_agent_cursor_armed", None)
        cursor_armed = action in {"click", "drag"} and callable(set_cursor)
        if cursor_armed:
            with suppress(Exception):
                set_cursor(True)
        try:
            if before_dispatch is not None:
                before_dispatch()
            # The key tools press into the page's focus: give it to the ref first.
            focused = client.call(*self._evaluate(session, ref, "(element) => element.focus()")) \
                if action == "press" and ref else None
            result = focused if focused is not None and _is_error(focused) else client.call(call[0], call[1])
        except Exception:
            if hover_attribute is not None:
                with suppress(Exception):
                    controller.clear_external_ref(hover_attribute)
            raise
        finally:
            if cursor_armed:
                with suppress(Exception):
                    set_cursor(False)
        if _is_error(result):
            if hover_attribute is not None:
                with suppress(Exception):
                    controller.clear_external_ref(hover_attribute)
            controller.invalidate_external_frame()
            return {
                "ok": False,
                "reason_code": "backend_action_failed",
                "result": _result_text(result),
                "observe_required": True,
            }
        if hover_attribute is not None:
            return controller.hover_external_ref(
                hover_attribute, frame_id,
                **({"before_dispatch": before_dispatch} if before_dispatch is not None else {}),
            )
        mutation = controller.record_external_mutation(
            f"{self.name}:{action}",
            keep_frame=bool(ref) and (
                action in {"type", "select"}
                or (action == "press" and str(arguments.get("key") or "") in {"Space", " "}
                    and pa.is_choice_control(session.state.get("ref_roles", {}).get(ref)))
                or (action == "click" and pa.is_plain_click(click)
                    and pa.is_choice_control(session.state.get("ref_roles", {}).get(ref)))
            ),
        )
        return {
            **mutation,
            "result": _result_text(result),
        }

    @staticmethod
    def _file_arguments(session, arguments):
        frame_id = str(arguments.get("expected_frame_id") or "")
        if not frame_id or frame_id != session.state.get("file_refs_frame"):
            return None, {"ok": False, "reason_code": "stale_observation",
                          "observe_required": True}
        ref = str(arguments.get("ref") or "").lstrip("@")
        native_ref = session.state.get("file_refs", {}).get(ref)
        if native_ref is None:
            return None, {"ok": False, "reason_code": "file_input_required",
                          "message": "Use a file_ ref from the latest observation elements.",
                          "observe_required": True}
        return {**arguments, "ref": native_ref}, None

    def verify(self, session, arguments: Mapping[str, Any], *, before_dispatch=None):
        params = dict(arguments)
        params["action"] = "verify"
        if params.get("assertion") == "file_selected":
            params, error = self._file_arguments(session, params)
            if error is not None:
                return error
        elif str(params.get("ref") or "").lstrip("@").startswith("file_"):
            return {"ok": False, "reason_code": "file_ref_action_required"}
        return self._controller(session).execute(
            **params,
            **({"before_dispatch": before_dispatch} if before_dispatch is not None else {}),
        )

    def close(self, session) -> None:
        client = session.state.pop("mcp_client", None)
        try:
            if client is not None:
                client.close()
        finally:
            if session.controller is not None:
                session.controller.close()


__all__ = ["OfficialMCPPageBackend"]
