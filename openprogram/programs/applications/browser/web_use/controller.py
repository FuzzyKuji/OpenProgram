"""Platform controller."""
from __future__ import annotations
from importlib import import_module

# Bind to the web_use package namespace.
state = import_module(__package__)

from . import page_actions as pa
from . import observe_diff, page_logs
import logging

_log = logging.getLogger(__name__)


def _safe_observation_id(candidate: str, secrets, used=()) -> str:
    """Keep generated control IDs usable without echoing a known secret."""
    from openprogram.programs.applications.browser.privacy import contains_password_value
    if not contains_password_value(candidate, secrets):
        return candidate
    alphabet = [char for char in "abcdefghijklmnopqrstuvwxyz0123456789_-"
                if not contains_password_value(char, secrets)]
    if alphabet:
        for _ in range(64):
            candidate = "".join(alphabet[int(char, 16) % len(alphabet)]
                                for char in state.uuid.uuid4().hex)
            if candidate not in used and not contains_password_value(candidate, secrets):
                return candidate
    raise RuntimeError("Cannot safely identify browser controls")


def _bounded_field_context(context, secrets, budget):
    from openprogram.programs.applications.browser.privacy import redact_password_values
    original_binding = context.get("label_binding", {})
    original_label = original_binding.get("label")
    context = redact_password_values(context, secrets)
    binding = context.get("label_binding")
    if isinstance(binding, dict) and isinstance(original_label, str):
        binding["redacted"] = bool(binding.get("redacted")) or binding.get("label") != original_label
        binding["truncated"] = bool(binding.get("truncated")) or len(binding.get("label", "")) > 400
    truncated = bool(context.get("truncated"))
    def bound(value):
        nonlocal truncated
        if isinstance(value, str):
            truncated |= len(value) > 400
            return value[:400]
        if isinstance(value, dict):
            return {key: bound(item) for key, item in value.items()}
        if isinstance(value, list):
            return [bound(item) for item in value]
        return value
    context = bound(context)
    while True:
        context["truncated"] = truncated
        size = len(state.json.dumps(context, ensure_ascii=False).encode("utf-8"))
        if size <= budget:
            return context, budget - size
        if not context.get("ancestors"):
            return None, budget
        context["ancestors"].pop()
        truncated = True


_CONTENTEDITABLE_TYPE_SCRIPT = """async (element, text) => {
    if (!element.isConnected || !element.isContentEditable) return false;
    element.replaceChildren(element.ownerDocument.createTextNode(text));
    const selection = element.ownerDocument.getSelection();
    const range = element.ownerDocument.createRange();
    range.selectNodeContents(element);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
    element.dispatchEvent(new InputEvent('input', {
        bubbles: true, composed: true, inputType: 'insertText', data: text
    }));
    // Observe synchronous handlers and queued editor state updates.
    await new Promise(resolve => setTimeout(resolve, 0));
    return element.isConnected && element.isContentEditable && element.innerText === text;
}"""


class BrowserPageController:
    """One call-scoped browser session and its latest observation refs."""

    def __init__(self, browser_api=None, *, url: str = "", max_steps: int = 20):
        if browser_api is None:
            from openprogram.programs.applications.browser.engine import browser as browser_api
        self.browser_api = browser_api
        self.initial_url = url
        self.binding_id = ""
        self.page_revision = 0
        self.access_revision = 0
        self.geometry_revision = 0
        self.max_steps = max(1, int(max_steps))
        self.session_id = ""
        self._frame: dict[str, state.Any] | None = None
        self._frame_identity = None
        self._frame_passwords = ()
        self._refs: dict[str, state.Any] = {}
        self._ref_meta: dict[str, dict[str, state.Any]] = {}
        self._frame_seq = 0
        self._last_observation: dict[str, state.Any] | None = None
        self._mutations = 0
        self._verified_mutation = -1
        self._evidence: list[dict[str, state.Any]] = []
        self._screenshot_frame = ""
        self._screenshot_viewport: dict[str, state.Any] | None = None
        self._navigation_time_origin: float | None = None
        self._terminal_reason = ""
        self._last_action = ""
        self._last_result: state.Any = None
        self._planner_screenshot_result: state.ToolReturn | None = None
        self._action_seq = 0
        self._owner = state.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="browser-agent-page",
        )
        self.tool = state.function(
            name="browser_page",
            description=(
                "Control only the exact bound OpenProgram browser Page. Start with "
                "observe. Use screenshot only for visual verification, canvas, "
                "or when DOM/ARIA refs cannot identify the target. Every write "
                "needs the latest frame_id and refs become stale after it. "
                "Editable elements provide their actual value; exact readback "
                "requires value_truncated=false and value_redacted=false."
            ),
            parameters=state._TOOL_PARAMETERS,
            requires_approval=self._requires_approval,
            path_params={"path": "read"},
            register_globally=False,
            max_result_chars=100_000,
        )(self.execute)

    def _submit(self, callback, *args, **kwargs):
        return self._owner.submit(state.copy_context().run, callback, *args, **kwargs).result()

    def _requires_approval(self, action: str = "", url: str = "", **_kw):
        if action == "upload":
            return "Upload the selected local file to the bound website; this can transmit file contents immediately."
        if action == pa.EVALUATE_ACTION:
            return "Run a script in the page; it can read and change everything the page holds."
        if action not in {
            "navigate", "click", "type", "press", "scroll", "hover", "select", *pa.PARITY_ACTIONS,
        }:
            return False
        if self.binding_id:
            return False
        target_url = url or str((self._frame or {}).get("url") or self.initial_url)
        if state._is_local(target_url):
            return False
        return f"browser action '{action}' changes external origin {state._origin(target_url)}"

    def _ensure_open(self) -> None:
        if self.session_id:
            return
        result = self.browser_api.execute(
            action="open", engine="app", url=self.initial_url or None,
            binding_id=self.binding_id or None,
            expected_page_revision=self.page_revision,
            expected_access_revision=self.access_revision,
            expected_geometry_revision=self.geometry_revision,
        )
        match = state.re.search(r"`(br_[^`]+)`", str(result))
        if not match:
            self._terminal_reason = "target_lost"
            raise RuntimeError(str(result))
        self.session_id = match.group(1)

    def _session(self) -> dict[str, state.Any]:
        self._ensure_open()
        session = self.browser_api._sessions.get(self.session_id)
        if not isinstance(session, dict):
            self._terminal_reason = "target_lost"
            raise RuntimeError("visible browser session was lost")
        return session

    def _page(self):
        session = self._session()
        current = getattr(self.browser_api, "_current_page", None)
        return current(session) if callable(current) else session["page"]

    def evaluate_bound_page(self, expression: str, argument: state.Any = None) -> state.Any:
        """Evaluate against the Page on the controller's Playwright thread."""
        return self._submit(
            self._evaluate_bound_page, expression, argument,
        )

    def _evaluate_bound_page(self, expression: str, argument: state.Any) -> state.Any:
        page = self._page()
        if argument is None:
            return page.evaluate(expression)
        return page.evaluate(expression, argument)

    def capture_observation(self, capture):
        """Redact an upstream capture on the owning Page thread, including frames."""
        def redact():
            from openprogram.programs.applications.browser.privacy import password_values, redact_password_values
            page = self._page()
            secrets = password_values(page)
            value = capture()
            return redact_password_values(value, secrets + password_values(page))
        return self._submit(redact)

    def set_agent_cursor_armed(self, armed: bool) -> None:
        """Show feedback only for pointer events emitted by one Agent click."""
        self._submit(self._set_agent_cursor_armed, bool(armed))

    def _set_agent_cursor_armed(self, armed: bool) -> None:
        try:
            page = self._page()
        except Exception:
            return
        frames = list(getattr(page, "frames", ()) or ()) or [page]
        for frame in frames:
            with state.suppress(Exception):
                frame.evaluate(state._AGENT_CURSOR_SCRIPT, armed)

    def _agent_click(self, callback) -> None:
        self._set_agent_cursor_armed(True)
        try:
            callback()
        finally:
            self._set_agent_cursor_armed(False)

    def prepare_external_action(self, arguments: state.Mapping[str, state.Any]) -> dict | None:
        """Validate an MCP action without moving Playwright objects off-owner."""
        return self._submit(
            self._prepare_external_action, dict(arguments),
        )

    def _prepare_external_action(self, arguments: dict[str, state.Any]) -> dict | None:
        frame_id = str(arguments.get("expected_frame_id") or "")
        stale = self._require_fresh(frame_id)
        if stale is not None:
            return stale
        action = str(arguments.get("action") or "")
        points = []
        if action == "click" and not arguments.get("ref"):
            points.append((arguments.get("x"), arguments.get("y")))
        if action == "drag" and not arguments.get("ref") and not arguments.get("to_ref"):
            points += [(arguments.get("x"), arguments.get("y")), (arguments.get("to_x"), arguments.get("to_y"))]
        for x, y in points:
            point = self._visual_point(self._page(), frame_id, x, y)
            if isinstance(point, dict):
                return point
        return self._write_allowed()

    def invalidate_external_frame(self) -> dict[str, state.Any]:
        return self._submit(self._invalidate_frame)

    def record_external_mutation(self, detail: str, *, keep_frame: bool = False) -> dict[str, state.Any]:
        return self._submit(self._mutated, detail, keep_frame=keep_frame)

    def pointer_scale(self) -> float | None:
        return self._submit(self._pointer_scale)

    def hover_external_ref(self, attribute: str, frame_id: str, *, before_dispatch=None) -> dict:
        return self._submit(
            self._hover_external_ref, attribute, frame_id,
            before_dispatch=before_dispatch,
        )

    def clear_external_ref(self, attribute: str) -> None:
        def clear():
            for frame in self._page().frames:
                with state.suppress(Exception):
                    frame.locator(f"[{attribute}]").evaluate_all(
                        "(nodes, attr) => nodes.forEach(n => n.removeAttribute(attr))", attribute,
                    )
        self._submit(clear)

    def _hover_external_ref(self, attribute: str, frame_id: str, *, before_dispatch=None) -> dict:
        page = self._page()
        targets = [frame.locator(f"[{attribute}]") for frame in page.frames]
        try:
            stale = self._require_fresh(frame_id) or self._write_allowed()
            if stale:
                return stale
            matches = [target for target in targets if target.count() == 1]
            scale = self._pointer_scale()
            if len(matches) != 1 or scale is None:
                return self._invalidate_frame()
            target = matches[0]
            if before_dispatch is not None:
                before_dispatch()
            target.scroll_into_view_if_needed()
            bounds = target.bounding_box()
            if not bounds:
                return self._invalidate_frame()
            if before_dispatch is not None:
                before_dispatch()
            page.mouse.move((bounds["x"] + bounds["width"] / 2) * scale,
                            (bounds["y"] + bounds["height"] / 2) * scale)
            return self._mutated("hovered external reference")
        finally:
            for target in targets:
                with state.suppress(Exception):
                    target.evaluate_all("(nodes, attr) => nodes.forEach(n => n.removeAttribute(attr))", attribute)

    def _pointer_scale(self) -> float | None:
        if not self.binding_id:
            return 1.0
        from openprogram.host.resources.desktop_link import request_bound_tab

        result = request_bound_tab(
            self.binding_id,
            expected_page_revision=self.page_revision,
            expected_access_revision=self.access_revision,
            expected_geometry_revision=self.geometry_revision,
        )
        if not result.get("ok"):
            return None
        scale = result.get("input_scale", 1)
        if type(scale) not in (int, float) or not state.math.isfinite(scale) or scale <= 0:
            return None
        return float(scale)

    def _viewport(self, page, snapshot: dict[str, state.Any]) -> dict[str, state.Any]:
        size = page.viewport_size or {}
        return {
            "width": int(size.get("width") or snapshot.get("viewport_width") or 0),
            "height": int(size.get("height") or snapshot.get("viewport_height") or 0),
            "device_scale_factor": snapshot.get("device_scale_factor", 1),
            "scroll_x": snapshot.get("scroll_x", 0),
            "scroll_y": snapshot.get("scroll_y", 0),
        }

    def _observe(self) -> dict[str, state.Any]:
        from openprogram.programs.applications.browser.privacy import password_values, redact_password_values
        page = self._page()
        secrets = password_values(page)
        snapshot = page.evaluate(state._OBSERVE_SCRIPT)
        if not isinstance(snapshot, dict):
            raise RuntimeError("browser observation did not return an object")
        self._frame_seq += 1
        frame_id = f"frame_{self._frame_seq}_{state.uuid.uuid4().hex[:8]}"
        handles_array = page.evaluate_handle(state._CAPTURE_HANDLES_SCRIPT)
        elements = []
        value_budget = 32768  # UTF-8 bytes across editable fields in this frame.
        context_budget = 32768  # UTF-8 JSON bytes across diagnostic contexts.
        refs = {}
        ref_meta = {}
        try:
            # The browser selects at most 120 visible nodes in one page-side
            # operation. JSHandle properties preserve those exact nodes while
            # avoiding an unbounded element_handles() materialization.
            for key, js_handle in handles_array.get_properties().items():
                if not key.isdigit():
                    continue
                handle = js_handle.as_element()
                if handle is None:
                    continue
                try:
                    actual = handle.evaluate(state._REF_SNAPSHOT_SCRIPT)
                except Exception:
                    handle.dispose()
                    continue
                if (
                    not isinstance(actual, dict)
                    or not actual.get("connected")
                    or not actual.get("visible")
                ):
                    handle.dispose()
                    continue
                ref = f"e{len(elements) + 1}"
                metadata = {
                    "ref": ref,
                    "tag": str(actual.get("tag") or "element"),
                    "role": str(actual.get("role") or actual.get("tag") or "element"),
                    "name": str(actual.get("name") or ""),
                    "disabled": bool(actual.get("disabled")),
                }
                for field in ("label", "value", "value_source", "value_truncated", "value_redacted", "field_context", "input_type", "files"):
                    if field in actual:
                        metadata[field] = actual[field]
                refs[ref] = handle
                ref_meta[ref] = {
                    field: metadata[field]
                    for field in ("tag", "role", "name", "disabled")
                }
                ref_meta[ref]["input_type"] = actual.get("input_type")
                ref_meta[ref]["label"] = actual.get("label")
                ref_meta[ref]["native_label_identity"] = actual.get("native_label_identity")
                ref_meta[ref]["label_binding"] = (actual.get("field_context") or {}).get("label_binding")
                try:
                    ref_meta[ref]["bounds"] = {
                        "x": float(actual["x"]), "y": float(actual["y"]),
                        "width": float(actual["width"]), "height": float(actual["height"]),
                    }
                except (KeyError, TypeError, ValueError):
                    pass
                elements.append({
                    field: value
                    for field, value in metadata.items()
                    if field != "tag"
                })
        finally:
            handles_array.dispose()
        try:
            aria = page.locator("body").aria_snapshot() or ""
        except Exception:
            aria = ""
        session = self._session()
        frame_identity = (page.url, session.get("app_tab_id"), session.get("app_target_id"))
        frame = {
            "frame_id": frame_id,
            "url": page.url,
            "origin": state._origin(page.url),
            "title": page.title(),
            "target": {
                "kind": "web_tab",
                "tab_id": session.get("app_tab_id"),
                "target_id": session.get("app_target_id"),
            },
            "viewport": self._viewport(page, snapshot),
            "text": str(snapshot.get("text") or ""),
            "aria_snapshot": aria,
            "elements": elements,
        }
        try:
            secrets += password_values(page)
            frame["frame_id"] = _safe_observation_id(frame_id, secrets)
            for element in elements:
                original = element["ref"]
                ref = _safe_observation_id(original, secrets, refs)
                if ref != original:
                    refs[ref] = refs.pop(original)
                    ref_meta[ref] = ref_meta.pop(original)
                    element["ref"] = ref
            for element in elements:
                value = element.get("value")
                if isinstance(value, str) and redact_password_values(value, secrets) != value:
                    del element["value"]
                    element["value_redacted"] = True
                    if element.get("name") and value.startswith(element["name"]):
                        element["name"] = "[redacted]"
                elif isinstance(value, str):
                    # Redact the full host-local value before truncating it:
                    # cutting a long secret first would expose its prefix.
                    value = value[:8192]
                    encoded = value.encode("utf-8")
                    if len(encoded) > value_budget:
                        value = encoded[:value_budget].decode("utf-8", errors="ignore")
                    element["value_truncated"] = value != element["value"]
                    element["value"] = value
                    value_budget -= len(value.encode("utf-8"))
                context = element.get("field_context")
                if isinstance(context, dict):
                    context, context_budget = _bounded_field_context(context, secrets, context_budget)
                    element["field_context_truncated"] = context is None or bool(context.get("truncated"))
                    if context is None:
                        del element["field_context"]
                    else:
                        element["field_context"] = context
            frame = redact_password_values(frame, secrets)
            frame["text"] = frame["text"][:12000]
            if len(frame["aria_snapshot"]) > 12000:
                frame["aria_snapshot"] = frame["aria_snapshot"][:12000] + "\n[truncated]"
        except BaseException:
            for handle in refs.values():
                with state.suppress(Exception):
                    handle.dispose()
            raise
        self._frame = frame
        self._frame_identity = frame_identity
        self._frame_passwords = secrets
        try:
            self._navigation_time_origin = float(snapshot.get("navigation_time_origin"))
        except (TypeError, ValueError):
            self._navigation_time_origin = None
        self._dispose_refs()
        self._refs = refs
        self._ref_meta = ref_meta
        self._screenshot_frame = ""
        self._screenshot_viewport = None
        return frame

    def _fresh(self, expected_frame_id: str) -> bool:
        if not self._frame or expected_frame_id != self._frame["frame_id"]:
            return False
        page = self._page()
        session = self._session()
        if (page.url, session.get("app_tab_id"), session.get("app_target_id")) != self._frame_identity:
            return False
        if self._navigation_time_origin is not None:
            try:
                current = float(page.evaluate(state._VIEWPORT_SCRIPT).get("navigation_time_origin"))
            except (AttributeError, TypeError, ValueError):
                return False
            if current != self._navigation_time_origin:
                return False
        return True

    def _require_fresh(self, expected_frame_id: str) -> dict[str, state.Any] | None:
        if self._fresh(expected_frame_id):
            return None
        return self._invalidate_frame()

    def _invalidate_frame(self) -> dict[str, state.Any]:
        self._frame = None
        self._dispose_refs()
        self._ref_meta = {}
        self._screenshot_frame = ""
        self._screenshot_viewport = None
        self._navigation_time_origin = None
        return {"ok": False, "reason_code": "stale_observation"}

    def _ref(self, ref: str):
        key = (ref or "").lstrip("@")
        target = self._refs.get(key)
        expected = self._ref_meta.get(key)
        if target is None or expected is None:
            return None, "ref_not_found"
        try:
            actual = target.evaluate(state._REF_SNAPSHOT_SCRIPT)
        except Exception:
            return None, "stale_observation"
        if (
            not isinstance(actual, dict)
            or not actual.get("connected")
            or not actual.get("visible")
            or any(
                actual.get(field) != expected.get(field)
                for field in ("tag", "role", "name", "disabled", "label", "native_label_identity", "input_type")
            )
            or (actual.get("field_context") or {}).get("label_binding") != expected.get("label_binding")
        ):
            return None, "stale_observation"
        return target, None

    def _mutated(
        self, detail: str, *, point: dict | None = None, extra: dict | None = None,
        keep_frame: bool = False,
    ) -> dict[str, state.Any]:
        """Record a write. ``keep_frame`` is for a field edit (typing, choosing an
        option, ticking a box): when the page is still the observed one, its refs
        stay usable, so a form can be filled without observing after every field.
        Refs are still checked one by one when they are used."""
        from openprogram.programs.applications.browser.privacy import password_values, redact_password_values
        secrets = self._frame_passwords
        identity: dict[str, state.Any] = {}
        try:
            page = self._page()
            secrets += password_values(page)
            session = self._session()
            identity = {
                "url": page.url,
                "title": page.title(),
                "target": {
                    "kind": "web_tab",
                    "tab_id": session.get("app_tab_id"),
                    "target_id": session.get("app_target_id"),
                },
            }
            secrets += password_values(page)
        except Exception:
            identity = {}
        self._mutations += 1
        kept = ""
        with state.suppress(Exception):
            if keep_frame and self._frame and self._fresh(self._frame["frame_id"]):
                kept = self._frame["frame_id"]
        if kept:
            payload = {"ok": True, "detail": detail, "observe_required": False,
                       "frame_id": kept, **identity}
            if point is not None:
                payload["point"] = point
            payload.update(extra or {})
            return redact_password_values(payload, secrets)
        self._frame = None
        self._dispose_refs()
        self._ref_meta = {}
        self._screenshot_frame = ""
        self._screenshot_viewport = None
        self._navigation_time_origin = None
        payload = {"ok": True, "detail": detail, "observe_required": True, **identity}
        if point is not None:
            payload["point"] = point
        payload.update(extra or {})
        return redact_password_values(payload, secrets)

    def _read_logs(self, action: str, options: dict) -> dict[str, state.Any]:
        """Console messages or requests of the page; read-only, so the frame stays valid."""
        from openprogram.programs.applications.browser.privacy import password_values, redact_password_values
        try:
            pattern, only_errors, limit = page_logs.options(options)
            page = self._page()
            if action == "console_messages":
                text = page_logs.render_console(page_logs.console_rows(page), pattern, only_errors, limit)
            else:
                text = page_logs.render_requests(page_logs.request_rows(page), pattern, only_errors, limit)
        except page_logs.LogError as exc:
            return {"ok": False, "reason_code": exc.reason_code, "message": str(exc)}
        secrets = self._frame_passwords + password_values(page)
        return redact_password_values({"ok": True, "result": text}, secrets)

    def _write_allowed(self) -> dict[str, state.Any] | None:
        if self._terminal_reason == "file_selection_unconfirmed":
            return {"ok": False, "reason_code": self._terminal_reason, "message": "File selection has an uncertain outcome; automatic replay is disabled."}
        if self._mutations < self.max_steps:
            return None
        self._terminal_reason = "step_limit"
        return {"ok": False, "reason_code": "step_limit"}

    def execute(
        self,
        action: str,
        expected_frame_id: str = "",
        ref: str = "",
        url: str = "",
        text: str = "",
        key: str = "",
        value: str = "",
        amount: int = 500,
        assertion: str = "",
        x: float | None = None,
        y: float | None = None,
        *, path: str = "", before_dispatch=None, **options: state.Any,
    ) -> state.Any:
        """``options`` carries the parity arguments (mouse_button, to_ref, format …)."""
        def dispatch():
            if before_dispatch is not None:
                before_dispatch()
            kwargs = {"before_dispatch": before_dispatch} if before_dispatch is not None else {}
            try:
                return self._execute(action, expected_frame_id, ref, url, text, key,
                                     value, amount, assertion, x, y, path=path,
                                     options=options, **kwargs)
            except pa.ActionError as exc:
                return exc.result()
        result = self._submit(dispatch)
        self._last_action = action
        self._last_result = result
        self._action_seq += 1
        return result

    def _dispose_refs(self) -> None:
        refs, self._refs = self._refs, {}
        for handle in refs.values():
            try:
                handle.dispose()
            except Exception:
                # Teardown: the handle's page or frame may already be gone.
                _log.debug("element handle dispose failed", exc_info=True)

    def tool_for_actions(self, actions: list[str]):
        action_schema = {
            **state._TOOL_PARAMETERS["properties"]["action"],
            "enum": list(actions),
        }
        parameters = {
            **state._TOOL_PARAMETERS,
            "properties": {
                **state._TOOL_PARAMETERS["properties"],
                "action": action_schema,
            },
        }
        def dispatch(**arguments):
            result = self.execute(**arguments)
            if isinstance(result, state.ToolReturn) and result.images:
                self._planner_screenshot_result = result
            return state._result_for_prompt(result)

        return state.function(
            name="browser_page",
            description=(
                "Act on or verify the current Runtime observation for the exact "
                "bound OpenProgram Page. Observe is Runtime-owned and is not "
                "available in this planner request."
            ),
            parameters=parameters,
            requires_approval=self._requires_approval,
            path_params={"path": "read"},
            register_globally=False,
            max_result_chars=40_000,
        )(dispatch)

    def revoke_screenshot(self) -> None:
        self._submit(self._revoke_screenshot)

    def _revoke_screenshot(self) -> None:
        self._screenshot_frame = ""
        self._screenshot_viewport = None

    def _execute(
        self,
        action: str,
        expected_frame_id: str = "",
        ref: str = "",
        url: str = "",
        text: str = "",
        key: str = "",
        value: str = "",
        amount: int = 500,
        assertion: str = "",
        x: float | None = None,
        y: float | None = None,
        *, path: str = "", before_dispatch=None, options: dict | None = None,
    ) -> state.Any:
        options = {**(options or {}), "amount": amount, "text": text, "duration": (options or {}).get("duration")}

        def run(fn, *args, **kwargs):
            if before_dispatch is not None:
                before_dispatch()
            return fn(*args, **kwargs)

        if action == "stop":
            self._terminal_reason = "task_blocked"
            self._evidence = []
            self._verified_mutation = -1
            return {"ok": False, "reason_code": "task_blocked",
                    "message": text or "The planner cannot complete the task with the available actions."}
        if action == "observe":
            previous = self._last_observation
            frame = run(self._observe)
            if isinstance(frame, dict) and "frame_id" in frame:
                self._last_observation = frame
                if options.get("changes_only"):
                    return observe_diff.changes(previous, frame)
            return frame
        if action in page_logs.LOG_ACTIONS:
            return run(self._read_logs, action, options)
        if action in {"screenshot", "verify"} and not expected_frame_id and self._frame:
            expected_frame_id = self._frame["frame_id"]
        if action == "verify":
            # A new verification attempt replaces earlier completion authority,
            # including rejected arguments and stale observations.
            self._evidence = []
            self._verified_mutation = -1
            if not self._fresh(expected_frame_id):
                return {"ok": False, "reason_code": "stale_observation"}
            if not assertion or not isinstance(value, str) or not value.strip():
                return {"ok": False, "reason_code": "invalid_assertion",
                        "message": "verify requires assertion and a non-empty value. Put the expected result in value; text is only for typing or stop."}
            return run(self._verify, self._page(), expected_frame_id, assertion, value, ref)
        stale = self._require_fresh(expected_frame_id)
        if stale:
            return stale
        page = self._page()
        if action == "screenshot":
            if self._screenshot_frame == expected_frame_id:
                return {"ok": False, "reason_code": "screenshot_already_captured"}
            # Keep image pixels equal to viewport CSS pixels so a model point
            # can be passed directly to Playwright mouse coordinates even on
            # Retina / device_scale_factor != 1 displays.
            before = page.evaluate(state._VIEWPORT_SCRIPT)
            if self.binding_id:
                from openprogram.host.resources.desktop_link import (
                    request_bound_screenshot,
                )

                capture = run(request_bound_screenshot,
                    self.binding_id,
                    timeout=5.0,
                    expected_page_revision=self.page_revision,
                    expected_access_revision=self.access_revision,
                    expected_geometry_revision=self.geometry_revision,
                )
                image_data_url = str(capture.get("image_data_url") or "")
                if not capture.get("ok") or not image_data_url.startswith(
                    "data:image/png;base64,"
                ):
                    return {
                        "ok": False,
                        "reason_code": str(
                            capture.get("reason_code") or "screenshot_failed"
                        ),
                    }
                try:
                    image = state.base64.b64decode(
                        image_data_url.split(",", 1)[1], validate=True,
                    )
                except (ValueError, TypeError):
                    return {"ok": False, "reason_code": "screenshot_failed"}
            else:
                image = run(page.screenshot, full_page=False, scale="css")
            after = page.evaluate(state._VIEWPORT_SCRIPT)
            if before != after or not self._fresh(expected_frame_id):
                return self._invalidate_frame()
            self._screenshot_frame = expected_frame_id
            self._screenshot_viewport = self._viewport(page, after)
            return state.ToolReturn(
                text=f"Current viewport screenshot for {expected_frame_id}.",
                images=[image],
                json_data={
                    "frame_id": expected_frame_id,
                    "viewport": dict(self._screenshot_viewport),
                },
            )
        if action == "wait":
            run(page.wait_for_timeout, max(0, min(int(amount), 5000)))
            return {"ok": True, "frame_id": expected_frame_id}
        capped = self._write_allowed()
        if capped:
            return capped
        if action == "navigate":
            if not state._is_http_url(url):
                return {"ok": False, "reason_code": "unsupported_url"}
            run(page.goto, url)
            return self._mutated(f"navigated to {url}")
        if action in ("back", "forward", "reload"):
            before = page.url
            if action == "reload":
                run(page.reload)
                return self._mutated("reloaded the page")
            response = run(page.go_back if action == "back" else page.go_forward)
            if response is None and page.url == before:
                return {"ok": False, "reason_code": "no_history",
                        "message": f"The page has no history to go {action} to."}
            return self._mutated(f"went {action} to {page.url}")
        if action == pa.EVALUATE_ACTION:
            source = pa.evaluate_source(options)
            try:
                value = run(page.evaluate, source)
            except Exception as exc:
                # The script may have changed the page before it threw.
                failed = self._mutated("the script threw", extra={
                    "ok": False, "reason_code": "evaluate_failed",
                    "message": str(exc).strip().splitlines()[0][:500] if str(exc).strip() else type(exc).__name__})
                return failed
            return self._mutated("evaluated the script", extra={"result": pa.evaluation_text(value)})
        if action == "scroll":
            dx, dy = pa.scroll_delta(options)
            if ref:
                target, ref_error = self._ref(ref)
                if target is None:
                    return self._invalidate_frame() if ref_error == "stale_observation" else {"ok": False, "reason_code": ref_error}
                moved = run(target.evaluate, pa.SCROLL_SCRIPT, {"dx": dx, "dy": dy})
                if not (moved or {}).get("moved"):
                    return {"ok": False, "reason_code": "not_scrollable",
                            "message": f"Nothing around {ref} can scroll further that way."}
                return self._mutated(f"scrolled {(moved or {}).get('container', 'page')} by ({dx}, {dy})px")
            scale = self._pointer_scale()
            if scale is None:
                return self._invalidate_frame()
            run(page.mouse.wheel, dx, dy)
            return self._mutated(f"scrolled ({dx}, {dy})px" if dx else f"scrolled {dy}px")
        if action == "click" and not ref:
            click = pa.click_options(options)
            point = self._visual_point(page, expected_frame_id, x, y)
            if isinstance(point, dict):
                return point
            point_x, point_y = point
            scale = self._pointer_scale()
            if scale is None:
                return self._invalidate_frame()

            def click_point():
                for held in click["modifiers"]:
                    page.keyboard.down(held)
                try:
                    page.mouse.click(point_x * scale, point_y * scale, **pa.mouse_options(click))
                finally:
                    for held in reversed(click["modifiers"]):
                        page.keyboard.up(held)
            self._agent_click(lambda: run(click_point))
            return self._mutated(
                f"{self._click_words(click)} viewport point ({point_x:g}, {point_y:g})",
                point={"x": point_x, "y": point_y, "width": 0, "height": 0},
            )
        if action == "drag":
            return self._drag(page, expected_frame_id, ref, options, x, y, run)
        if action == "press" and not ref:
            hold = pa.hold_seconds(options)
            if hold:
                run(page.keyboard.down, key)
                try:
                    page.wait_for_timeout(int(hold * 1000))
                finally:
                    page.keyboard.up(key)
            else:
                run(page.keyboard.press, key)
            return self._mutated(f"pressed {key}" + (f" for {hold:g}s" if hold else ""))
        if action in ("type_text", "paste") and not ref:
            return self._page_script(page, action, None, options, run)
        target, ref_error = self._ref(ref)
        if target is None:
            if ref_error == "stale_observation":
                return self._invalidate_frame()
            return {"ok": False, "reason_code": ref_error}
        if action == "click":
            if self._ref_meta.get((ref or "").lstrip("@"), {}).get("disabled"):
                return {"ok": False, "reason_code": "target_disabled"}
            click = pa.click_options(options)
            if self.binding_id and pa.is_plain_click(click):
                self._agent_click(
                    lambda: run(target.evaluate, state._BACKGROUND_REF_CLICK_SCRIPT)
                )
            elif self.binding_id:
                # A bound tab stays in the background: dispatch the events in the page.
                self._agent_click(lambda: run(target.evaluate, pa.POINTER_SCRIPT, {
                    "button": click["button"], "count": click["count"], "flags": click["flags"]}))
            elif pa.is_plain_click(click):
                self._agent_click(lambda: run(target.click))
            else:
                self._agent_click(lambda: run(
                    target.click, button=click["button"], click_count=click["count"],
                    modifiers=click["modifiers"]))
            meta = self._ref_meta.get((ref or "").lstrip("@")) or {}
            bounds = meta.get("bounds")
            return self._mutated(
                f"{self._click_words(click)} {ref}",
                point=dict(bounds) if isinstance(bounds, dict) else None,
                keep_frame=pa.is_plain_click(click) and pa.is_choice_control(
                    meta.get("role"), meta.get("input_type")),
            )
        if action == "upload":
            from .file_inputs import file_payload
            if self._ref_meta.get((ref or "").lstrip("@"), {}).get("input_type") != "file":
                return {"ok": False, "reason_code": "file_input_required", "message": "upload requires a file-input ref from the latest observation."}
            if self._ref_meta.get((ref or "").lstrip("@"), {}).get("disabled"):
                return {"ok": False, "reason_code": "target_disabled"}
            payload, error = file_payload(path)
            if error:
                return error
            # Guards run again after the local read, immediately before transmission.
            if before_dispatch is not None:
                before_dispatch()
            if not self._fresh(expected_frame_id):
                return self._invalidate_frame()
            target, ref_error = self._ref(ref)
            if target is None:
                return {"ok": False, "reason_code": ref_error}
            try:
                target.set_input_files(payload)
            except BaseException as exc:
                self._mutated("unconfirmed file selection")
                self._terminal_reason = "file_selection_unconfirmed"
                if isinstance(exc, state._CANCELLATION_ERRORS) or not isinstance(exc, Exception):
                    raise
                return {"ok": False, "reason_code": self._terminal_reason,
                        "message": "File selection has an uncertain outcome; inspect the Page instead of uploading again.",
                        "observe_required": True}
            result = self._mutated("selected one file")
            result["server_acceptance_verified"] = False
            return result
        if action == "type":
            editable = run(lambda: target.evaluate("element => element.isContentEditable"))
            if editable is True:
                # Keep native editable/visibility checks and focus; clearing avoids
                # Chromium paragraph nodes adding a rendered newline to blank lines.
                try:
                    run(target.fill, "")
                    exact = run(target.evaluate, _CONTENTEDITABLE_TYPE_SCRIPT, text)
                except BaseException:
                    self._mutated(f"unconfirmed type into {ref}")
                    raise
                result = self._mutated(f"typed {len(text)} character(s) into {ref}")
                if exact is not True:
                    result.update(ok=False, reason_code="editable_value_mismatch")
                return result
            run(target.fill, text)
            return self._mutated(f"typed {len(text)} character(s) into {ref}", keep_frame=True)
        if action == "press":
            hold = pa.hold_seconds(options)
            if hold:
                run(target.focus)
                run(page.keyboard.down, key)
                try:
                    page.wait_for_timeout(int(hold * 1000))
                finally:
                    page.keyboard.up(key)
                return self._mutated(f"pressed {key} on {ref} for {hold:g}s")
            run(target.press, key)
            return self._mutated(f"pressed {key} on {ref}")
        if action in ("type_text", "paste", "select_text"):
            return self._page_script(page, action, target, options, run, ref=ref)
        if action == "hover":
            scale = self._pointer_scale()
            if scale is None:
                return self._invalidate_frame()
            if scale == 1:
                run(target.hover)
            else:
                run(target.scroll_into_view_if_needed)
                bounds = target.bounding_box()
                if not bounds:
                    return self._invalidate_frame()
                run(page.mouse.move, (bounds["x"] + bounds["width"] / 2) * scale,
                    (bounds["y"] + bounds["height"] / 2) * scale)
            return self._mutated(f"hovered {ref}")
        if action == "select":
            run(target.select_option, value)
            return self._mutated(f"selected an option in {ref}", keep_frame=True)
        return {"ok": False, "reason_code": "unsupported_action"}

    @staticmethod
    def _click_words(click: dict[str, state.Any]) -> str:
        words = {1: "clicked", 2: "double-clicked", 3: "triple-clicked"}[click["count"]]
        if click["button"] != "left":
            words = f"{click['button']}-{words}"
        if click["modifiers"]:
            words += " with " + "+".join(click["modifiers"])
        return words

    def _visual_point(self, page, expected_frame_id: str, x, y) -> tuple[float, float] | dict:
        """A point of the last screenshot, or the failure that makes it unusable."""
        if x is None or y is None:
            return {"ok": False, "reason_code": "target_required"}
        if self._screenshot_frame != expected_frame_id:
            return {"ok": False, "reason_code": "visual_observation_required"}
        try:
            point_x, point_y = float(x), float(y)
        except (TypeError, ValueError):
            return {"ok": False, "reason_code": "invalid_coordinate"}
        viewport = self._viewport(page, page.evaluate(state._VIEWPORT_SCRIPT))
        if viewport != self._screenshot_viewport:
            return self._invalidate_frame()
        if (
            not state.math.isfinite(point_x) or not state.math.isfinite(point_y)
            or point_x < 0 or point_y < 0
            or point_x >= viewport["width"] or point_y >= viewport["height"]
        ):
            return {"ok": False, "reason_code": "invalid_coordinate"}
        return point_x, point_y

    def _ref_center(self, ref: str) -> tuple[float, float] | dict:
        target, ref_error = self._ref(ref)
        if target is None:
            return self._invalidate_frame() if ref_error == "stale_observation" else {"ok": False, "reason_code": ref_error}
        target.scroll_into_view_if_needed()
        bounds = target.bounding_box()
        if not bounds:
            return self._invalidate_frame()
        return bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2

    def _drag(self, page, expected_frame_id: str, ref: str, options: dict, x, y, run) -> dict:
        """Press, move in steps, release: works for pointer-driven and HTML5 drag targets."""
        start = self._ref_center(ref) if ref else self._visual_point(page, expected_frame_id, x, y)
        if isinstance(start, dict):
            return start
        to_ref = str(options.get("to_ref") or "")
        end = (self._ref_center(to_ref) if to_ref
               else self._visual_point(page, expected_frame_id, options.get("to_x"), options.get("to_y")))
        if isinstance(end, dict):
            return end
        scale = self._pointer_scale()
        if scale is None:
            return self._invalidate_frame()

        def drag():
            page.mouse.move(start[0] * scale, start[1] * scale)
            page.mouse.down()
            try:
                page.mouse.move(end[0] * scale, end[1] * scale, steps=12)
            finally:
                page.mouse.up()
        self._agent_click(lambda: run(drag))
        source = ref or f"({start[0]:g}, {start[1]:g})"
        destination = to_ref or f"({end[0]:g}, {end[1]:g})"
        return self._mutated(f"dragged {source} to {destination}")

    def _page_script(self, page, action: str, target, options: dict, run, *, ref: str = "") -> dict:
        """type_text, paste and select_text, run inside the page on ``target`` or the focus."""
        if action == "type_text":
            text = options.get("text")
            if not isinstance(text, str) or not text:
                raise pa.ActionError("text_required", "type_text needs text")
            script, payload = pa.INSERT_TEXT_SCRIPT, {"text": text}
            detail = f"inserted {len(text)} character(s)"
        elif action == "paste":
            payload = pa.paste_payload(options)
            script = pa.PASTE_SCRIPT
            detail = f"pasted {len(payload['text'])} character(s)"
        else:
            payload = pa.selection_request(options)
            script = pa.SELECT_TEXT_SCRIPT
            detail = {"text": "selected", "cursor_before": "placed the caret before",
                      "cursor_after": "placed the caret after"}[payload["kind"]] + f" {payload['text']!r}"
        if target is None:
            result = run(page.evaluate, f"(o) => ({script.strip()})(null, o)", payload)
        else:
            result = run(target.evaluate, script, payload)
        if not isinstance(result, dict) or not result.get("ok"):
            code = (result or {}).get("reason_code") if isinstance(result, dict) else None
            return {"ok": False, "reason_code": code or f"{action}_failed",
                    "message": {"focus_required": "Nothing on the page has keyboard focus; pass ref.",
                                "not_editable": "The focused element does not take text.",
                                "text_not_found": "That text is not inside the element."}.get(code or "", "")}
        if result.get("handled_by_page"):
            detail += "; the page handled the paste itself"
        elif action == "paste":
            detail += " as rich text" if result.get("rich") else " as plain text"
        return self._mutated(detail + (f" in {ref}" if ref else ""))

    def _verify(self, page, frame_id: str, assertion: str, value: str, ref: str = "") -> dict:
        from openprogram.programs.applications.browser.privacy import contains_password_value, password_values, redact_password_values
        secrets = password_values(page)
        if contains_password_value(value, secrets):
            return {"ok": False, "passed": False, "reason_code": "sensitive_assertion"}
        # Assertions evaluate the real Page. Redaction is an output policy;
        # it must never turn a visible secret into a successful absence check.
        text = page.inner_text("body")
        snapshot = page.evaluate(state._OBSERVE_SCRIPT)
        checks = {
            "text_contains": value in text,
            "text_not_contains": value not in text,
            "url_contains": value in page.url,
            "title_contains": value in page.title(),
            "element_present": any(
                value.casefold() in str(item.get("name") or "").casefold()
                for item in snapshot.get("elements") or []
            ),
        }
        if assertion == "file_selected":
            target, error = self._ref(ref)
            if target is None:
                return {"ok": False, "reason_code": error}
            files = target.evaluate("el => el.matches('input[type=file]') && el.isConnected ? Array.from(el.files || []).map(file => file.name) : []")
            checks["file_selected"] = isinstance(files, list) and value in files
        if assertion not in checks:
            return {"ok": False, "reason_code": "unsupported_assertion"}
        passed = bool(checks[assertion])
        evidence = {
            "kind": "assertion",
            "assertion": assertion,
            "value": value,
            "frame_id": frame_id,
            "passed": passed,
            **({"ref": ref, "server_acceptance_verified": False} if assertion == "file_selected" else {}),
        }
        if not self._fresh(frame_id):
            return self._invalidate_frame()
        if passed:
            self._verified_mutation = self._mutations
            self._evidence = [evidence]
        return redact_password_values({
            "ok": True, "passed": passed, "evidence": evidence,
            # Preserve the bounded observation for the caller's answer. The
            # assertion verifies only its named condition, not every field.
            **({"observation": self._frame} if passed else {}),
        }, secrets)

    def final_result(self, *, summary: str, reason_code: str | None = None) -> dict:
        return self._submit(
            self._final_result,
            summary=summary,
            reason_code=reason_code,
        )

    def _final_result(self, *, summary: str, reason_code: str | None = None) -> dict:
        from openprogram.programs.applications.browser.privacy import password_values, redact_password_values
        secrets = ()
        privacy_failed = False
        if self.session_id:
            try:
                secrets = password_values(self._page())
            except Exception:
                privacy_failed = True
                summary = "Browser target is unavailable."
        observation = None
        verified = bool(self._evidence) and self._verified_mutation == self._mutations
        if privacy_failed:
            verified = False
            self._evidence = []
            self._verified_mutation = -1
        if verified:
            evidence = self._evidence[-1]
            # Human input and asynchronous Page updates do not increment the
            # controller's mutation counter. Recheck the exact document and
            # assertion before delivering a successful task result.
            self._evidence = []
            self._verified_mutation = -1
            try:
                frame_id = evidence["frame_id"]
                verification = self._verify(
                    self._page(), frame_id, evidence["assertion"], evidence["value"], evidence.get("ref", ""),
                ) if self._fresh(frame_id) else {}
                verified = verification.get("passed") is True
                if verified:
                    observation = verification.get("observation")
            except Exception:
                verified = False
        reason = reason_code or self._terminal_reason or (
            "verified" if verified else "verification_missing"
        )
        status = "cancelled" if reason == "cancelled" else (
            "succeeded" if verified and reason == "verified" else "failed"
        )
        if privacy_failed:
            reason = "observation_privacy_unavailable"
            status = "failed"
        target = {"kind": "web_tab", "tab_id": None, "url": ""}
        if self.session_id and not privacy_failed:
            try:
                session = self._session()
                target.update({
                    "tab_id": session.get("app_tab_id"),
                    "url": self._page().url,
                })
            except Exception:
                reason = "target_lost"
                status = "failed"
        return redact_password_values({
            "status": status,
            "reason_code": reason,
            "summary": summary,
            "target": target,
            "steps_taken": self._mutations,
            "completion_evidence": list(self._evidence) if status == "succeeded" else [],
            **({"observation": observation} if status == "succeeded" and isinstance(observation, dict) else {}),
            "artifacts": [],
        }, secrets)

    def close(self) -> str | None:
        try:
            return self._submit(self._close)
        finally:
            self._owner.shutdown(wait=True)

    def _close(self) -> str | None:
        session_id, self.session_id = self.session_id, ""
        self._frame = None
        self._frame_identity = None
        self._frame_passwords = ()
        self._dispose_refs()
        self._ref_meta = {}
        self._screenshot_frame = ""
        self._screenshot_viewport = None
        self._navigation_time_origin = None
        if not session_id:
            return None
        try:
            result = str(self.browser_api.execute(
                action="close", session_id=session_id,
            ))
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        if result.startswith("Error:") or " with warnings:" in result:
            return result
        return None
