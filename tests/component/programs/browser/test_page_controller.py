from __future__ import annotations

import base64
import threading

import pytest


class _FakeLocator:
    def __init__(self, page, index: int | None = None):
        self.page = page
        self.index = index

    def nth(self, index: int):
        return _FakeLocator(self.page, index)

    def aria_snapshot(self):
        return '- document:\n  - button "Save"\n  - textbox "Name"'

    def element_handle(self):
        if self.index is None or self.index >= len(self.page.node_order):
            return None
        return _FakeElementHandle(self.page, self.page.node_order[self.index])

    def element_handles(self):
        handles = [
            _FakeElementHandle(self.page, node_id) for node_id in self.page.node_order
        ]
        if self.page.mutate_after_handle_capture:
            self.page.node_order.insert(0, "capture-window-save")
        return handles

    def click(self):
        self.page.calls.append(("click", self.index))
        self.page.body_text = "Saved"

    def fill(self, text: str):
        self.page.calls.append(("fill", self.index, text))

    def press(self, key: str):
        self.page.calls.append(("press", self.index, key))

    def hover(self):
        self.page.calls.append(("hover", self.index))

    def select_option(self, value: str):
        self.page.calls.append(("select", self.index, value))

    def evaluate(self, _script: str):
        index = 0 if self.index is None else self.index
        return self.page.element_snapshot(index)


class _FakeElementHandle:
    def __init__(self, page, node_id: str):
        self.page = page
        self.node_id = node_id

    def _index(self):
        try:
            return self.page.node_order.index(self.node_id)
        except ValueError:
            return None

    def evaluate(self, script: str):
        index = self._index()
        if "element.click()" in script:
            if self.page.agent_cursor_armed:
                self.page.agent_cursor_events.append((120, 80))
            self.page.calls.append(("click", index))
            self.page.body_text = "Saved"
            return None
        if index is None:
            return {
                "connected": False,
                "visible": False,
                "tag": "button",
                "role": "button",
                "name": "Save",
                "disabled": False,
            }
        return {
            "connected": True,
            "visible": self.page.element_visible,
            **self.page.element_snapshot(index),
        }

    def click(self):
        self.page.native_handle_clicks += 1
        if self.page.agent_cursor_armed:
            self.page.agent_cursor_events.append((120, 80))
        self.page.calls.append(("click", self._index()))
        self.page.body_text = "Saved"

    def fill(self, text: str):
        self.page.calls.append(("fill", self._index(), text))

    def press(self, key: str):
        self.page.calls.append(("press", self._index(), key))

    def hover(self):
        self.page.calls.append(("hover", self._index()))

    def select_option(self, value: str):
        self.page.calls.append(("select", self._index(), value))

    def as_element(self):
        return self

    def dispose(self):
        self.page.disposed_nodes.append(self.node_id)


class _FakeArrayHandle:
    def __init__(self, page):
        self.handles = [
            _FakeElementHandle(page, node_id) for node_id in page.node_order[:120]
        ]
        if page.mutate_after_handle_capture:
            page.node_order.insert(0, "capture-window-save")

    def get_properties(self):
        return {str(index): handle for index, handle in enumerate(self.handles)}

    def dispose(self):
        return None


class _FakeMouse:
    def __init__(self, page):
        self.page = page

    def click(self, x: float, y: float):
        if self.page.agent_cursor_armed:
            self.page.agent_cursor_events.append((x, y))
        self.page.calls.append(("mouse_click", x, y))
        self.page.body_text = "Clicked point"

    def wheel(self, x: int, y: int):
        self.page.calls.append(("wheel", x, y))


class _FakePage:
    def __init__(self):
        self.url = "http://127.0.0.1:18100/fixture"
        self.body_text = "Name Save"
        self.button_name = "Save"
        self.button_disabled = False
        self.element_visible = True
        self.navigation_time_origin = 1
        self.viewport_width = 960
        self.viewport_height = 640
        self.scroll_x = 0
        self.scroll_y = 0
        self.calls = []
        self.agent_cursor_armed = False
        self.agent_cursor_states = []
        self.agent_cursor_events = []
        self.agent_cursor_script = ""
        self.native_handle_clicks = 0
        self.node_order = ["save", "name"]
        self.disposed_nodes = []
        self.mutate_after_handle_capture = False
        self.mutate_during_screenshot = False
        self.viewport_size = {"width": 960, "height": 640}
        self.mouse = _FakeMouse(self)

    def title(self):
        return "Fixture"

    def locator(self, _selector: str):
        return _FakeLocator(self)

    def evaluate(self, _script: str, argument=None):
        if _script.lstrip().startswith("() => Array.from("):
            return []
        if "__openprogramAgentCursor" in _script:
            self.agent_cursor_armed = bool(argument)
            self.agent_cursor_states.append(bool(argument))
            self.agent_cursor_script = _script
            return None
        return {
            "text": self.body_text,
            "viewport_width": self.viewport_width,
            "viewport_height": self.viewport_height,
            "navigation_time_origin": self.navigation_time_origin,
            "scroll_x": self.scroll_x,
            "scroll_y": self.scroll_y,
            "device_scale_factor": 1,
            "elements": [
                {"dom_index": index, **self.node_snapshot(node_id)}
                for index, node_id in enumerate(self.node_order)
            ],
        }

    def evaluate_handle(self, _script: str):
        return _FakeArrayHandle(self)

    def node_snapshot(self, node_id: str):
        if node_id == "name":
            return {
                "tag": "input",
                "role": "textbox",
                "name": "Name",
                "disabled": False,
            }
        return {
            "tag": "button",
            "role": "button",
            "name": self.button_name,
            "disabled": self.button_disabled,
        }

    def element_snapshot(self, index: int):
        return self.node_snapshot(self.node_order[index])

    def screenshot(self, *, full_page: bool, scale: str):
        self.calls.append(("screenshot", full_page, scale))
        if self.mutate_during_screenshot:
            self.scroll_y += 1
        return b"\x89PNG fake"

    def goto(self, url: str):
        self.calls.append(("goto", url))
        self.url = url

    def inner_text(self, selector: str):
        assert selector == "body"
        return self.body_text


class _FakeBrowserAPI:
    def __init__(self):
        self.page = _FakePage()
        self._sessions = {}
        self.closed = []
        self.threads = []
        self.open_arguments = None

    def execute(self, action: str, **kwargs):
        self.threads.append(threading.get_ident())
        if action == "open":
            assert kwargs["engine"] == "app"
            self.open_arguments = dict(kwargs)
            self._sessions["br_test"] = {
                "page": self.page,
                "app_tab_id": "tab-1",
                "app_target_id": "target-1",
            }
            return "Opened browser session `br_test` (engine=app)."
        if action == "close":
            sid = kwargs["session_id"]
            self.closed.append(sid)
            self._sessions.pop(sid, None)
            return f"Closed {sid}."
        raise AssertionError(f"unexpected browser action: {action}")


def _controller():
    from openprogram.programs.applications.browser.web_use import (
        BrowserPageController,
    )

    api = _FakeBrowserAPI()
    return BrowserPageController(browser_api=api), api


def test_observe_returns_dom_aria_and_refs_without_a_screenshot():
    controller, api = _controller()

    result = controller.execute(action="observe")

    assert result["url"] == api.page.url
    assert result["title"] == "Fixture"
    assert result["viewport"] == {
        "width": 960,
        "height": 640,
        "device_scale_factor": 1,
        "scroll_x": 0,
        "scroll_y": 0,
    }
    assert result["text"] == "Name Save"
    assert result["aria_snapshot"].startswith("- document:")
    assert [element["ref"] for element in result["elements"]] == ["e1", "e2"]
    assert not any(call[0] == "screenshot" for call in api.page.calls)


def test_failed_password_redaction_disposes_new_observation_handles(monkeypatch):
    controller, api = _controller()
    original = api.page.evaluate
    reads = []

    def evaluate(script, argument=None):
        if script.lstrip().startswith("() => Array.from("):
            reads.append(True)
            if len(reads) == 2:
                raise RuntimeError("password frame detached")
        return original(script, argument)

    monkeypatch.setattr(api.page, "evaluate", evaluate)
    try:
        with pytest.raises(RuntimeError, match="password frame detached"):
            controller.execute(action="observe")
        assert set(api.page.disposed_nodes) == set(api.page.node_order)
    finally:
        controller.close()


def test_screenshot_is_one_current_viewport_image_on_the_same_frame():
    from openprogram.programs import ToolReturn

    controller, api = _controller()
    observation = controller.execute(action="observe")

    result = controller.execute(action="screenshot")

    assert isinstance(result, ToolReturn)
    assert result.images == [b"\x89PNG fake"]
    assert api.page.calls[-1] == ("screenshot", False, "css")
    assert observation["frame_id"] in (result.text or "")
    assert controller.execute(action="screenshot") == {
        "ok": False,
        "reason_code": "screenshot_already_captured",
    }


def test_bound_screenshot_uses_hidden_desktop_capture(monkeypatch):
    from openprogram.programs import ToolReturn
    from openprogram.interfaces.server.ws_actions import webtab

    controller, api = _controller()
    controller.binding_id = "surface-background"
    controller.page_revision = 3
    controller.access_revision = 4
    controller.geometry_revision = 5
    calls = []
    monkeypatch.setattr(
        webtab,
        "request_bound_screenshot",
        lambda binding_id, **kwargs: calls.append((binding_id, kwargs))
        or {
            "ok": True,
            "image_data_url": "data:image/png;base64,"
            + base64.b64encode(b"\x89PNG hidden").decode("ascii"),
        },
    )

    observation = controller.execute(action="observe")
    result = controller.execute(
        action="screenshot",
        expected_frame_id=observation["frame_id"],
    )

    assert isinstance(result, ToolReturn)
    assert result.images == [b"\x89PNG hidden"]
    assert not any(call[0] == "screenshot" for call in api.page.calls)
    assert calls == [
        (
            "surface-background",
            {
                "timeout": 5.0,
                "expected_page_revision": 3,
                "expected_access_revision": 4,
                "expected_geometry_revision": 5,
            },
        )
    ]


def test_write_requires_fresh_frame_and_invalidates_old_refs():
    controller, api = _controller()
    observation = controller.execute(action="observe")

    result = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        ref="e1",
    )

    assert result["ok"] is True
    assert api.page.calls[-1] == ("click", 0)
    assert api.page.native_handle_clicks == 1
    stale = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        ref="e1",
    )
    assert stale == {"ok": False, "reason_code": "stale_observation"}


def test_bound_ref_click_uses_background_dom_click():
    controller, api = _controller()
    controller.binding_id = "surface-background"
    observation = controller.execute(action="observe")

    result = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        ref="e1",
    )

    assert result["ok"] is True
    assert api.page.calls[-1] == ("click", 0)
    assert api.page.native_handle_clicks == 0


def test_ref_hidden_after_observe_is_stale_and_is_not_clicked():
    controller, api = _controller()
    observation = controller.execute(action="observe")
    api.page.element_visible = False

    result = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        ref="e1",
    )

    assert result == {"ok": False, "reason_code": "stale_observation"}
    assert api.page.body_text == "Name Save"
    assert not any(call[0] == "click" for call in api.page.calls)
    assert api.page.native_handle_clicks == 0


def test_agent_click_cursor_is_internal_and_only_armed_for_agent_clicks():
    controller, api = _controller()

    api.page.mouse.click(4, 5)
    assert api.page.agent_cursor_events == []

    observed = controller.execute(action="observe")
    clicked = controller.execute(
        action="click",
        expected_frame_id=observed["frame_id"],
        ref="e1",
    )
    assert clicked["ok"] is True
    assert api.page.agent_cursor_states == [True, False]
    assert api.page.agent_cursor_events == [(120, 80)]
    assert "pointerEvents" in api.page.agent_cursor_script
    assert "aria-hidden" in api.page.agent_cursor_script

    observed = controller.execute(action="observe")
    controller.execute(
        action="screenshot",
        expected_frame_id=observed["frame_id"],
    )
    clicked = controller.execute(
        action="click",
        expected_frame_id=observed["frame_id"],
        x=100,
        y=80,
    )
    assert clicked["ok"] is True
    assert api.page.agent_cursor_states == [True, False, True, False]
    assert api.page.agent_cursor_events[-1] == (100, 80)


def test_unrelated_dynamic_dom_change_does_not_invalidate_a_named_ref():
    controller, api = _controller()
    observation = controller.execute(action="observe")
    api.page.body_text = "The page changed independently"

    result = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        ref="e1",
    )

    assert result["ok"] is True
    assert api.page.calls[-1] == ("click", 0)


def test_changed_element_identity_invalidates_the_ref_before_click():
    controller, api = _controller()
    observation = controller.execute(action="observe")
    api.page.button_name = "Delete"

    result = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        ref="e1",
    )

    assert result == {"ok": False, "reason_code": "stale_observation"}
    assert not any(call[0] == "click" for call in api.page.calls)


def test_observed_disabled_ref_is_not_clicked():
    controller, api = _controller()
    api.page.button_disabled = True
    observation = controller.execute(action="observe")

    result = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        ref="e1",
    )

    assert result == {"ok": False, "reason_code": "target_disabled"}
    assert not any(call[0] == "click" for call in api.page.calls)


def test_same_fingerprint_node_replacement_invalidates_exact_ref():
    controller, api = _controller()
    observation = controller.execute(action="observe")
    api.page.node_order[0] = "replacement-save"

    result = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        ref="e1",
    )

    assert result == {"ok": False, "reason_code": "stale_observation"}
    assert not any(call[0] == "click" for call in api.page.calls)


def test_same_fingerprint_sibling_insertion_keeps_exact_observed_node():
    controller, api = _controller()
    observation = controller.execute(action="observe")
    api.page.node_order.insert(0, "inserted-save")

    result = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        ref="e1",
    )

    assert result["ok"] is True
    assert api.page.calls[-1] == ("click", 1)


def test_capture_window_insertion_cannot_retarget_observed_ref():
    controller, api = _controller()
    api.page.mutate_after_handle_capture = True
    observation = controller.execute(action="observe")

    result = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        ref="e1",
    )

    assert result["ok"] is True
    assert api.page.calls[-1] == ("click", 1)


def test_same_url_document_replacement_invalidates_the_frame():
    controller, api = _controller()
    observation = controller.execute(action="observe")
    api.page.navigation_time_origin = 2

    result = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        ref="e1",
    )

    assert result == {"ok": False, "reason_code": "stale_observation"}
    assert not any(call[0] == "click" for call in api.page.calls)


def test_visual_point_click_requires_same_frame_screenshot_and_css_viewport():
    controller, api = _controller()
    api.page.viewport_size = None
    observation = controller.execute(action="observe")
    assert observation["viewport"]["width"] == 960
    assert observation["viewport"]["height"] == 640

    assert controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        x=100,
        y=80,
    ) == {"ok": False, "reason_code": "visual_observation_required"}
    controller.execute(action="screenshot", expected_frame_id=observation["frame_id"])
    result = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        x=100,
        y=80,
    )

    assert result["ok"] is True
    assert ("mouse_click", 100, 80) in api.page.calls


def test_visual_point_click_rejects_a_changed_screenshot_viewport():
    controller, api = _controller()
    observation = controller.execute(action="observe")
    controller.execute(action="screenshot", expected_frame_id=observation["frame_id"])
    api.page.scroll_y = 10

    result = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        x=100,
        y=80,
    )

    assert result == {"ok": False, "reason_code": "stale_observation"}
    assert not any(call[0] == "mouse_click" for call in api.page.calls)


def test_screenshot_rejects_viewport_change_during_capture():
    controller, api = _controller()
    observation = controller.execute(action="observe")
    api.page.mutate_during_screenshot = True

    result = controller.execute(
        action="screenshot",
        expected_frame_id=observation["frame_id"],
    )

    assert result == {"ok": False, "reason_code": "stale_observation"}
    assert controller._screenshot_frame == ""


@pytest.mark.parametrize("x,y", [(-1, 10), (10, -1), (960, 10), (10, 640)])
def test_visual_point_click_rejects_out_of_bounds_coordinates(x, y):
    controller, api = _controller()
    observation = controller.execute(action="observe")
    controller.execute(action="screenshot", expected_frame_id=observation["frame_id"])

    result = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        x=x,
        y=y,
    )

    assert result == {"ok": False, "reason_code": "invalid_coordinate"}
    assert not any(call[0] == "mouse_click" for call in api.page.calls)


def test_dom_verification_after_the_last_write_is_completion_authority():
    controller, _api = _controller()
    first = controller.execute(action="observe")
    controller.execute(action="click", expected_frame_id=first["frame_id"], ref="e1")
    second = controller.execute(action="observe")

    verified = controller.execute(
        action="verify",
        expected_frame_id=second["frame_id"],
        assertion="text_contains",
        value="Saved",
    )

    assert verified["passed"] is True
    result = controller.final_result(summary="form submitted")
    assert result["status"] == "succeeded"
    assert result["reason_code"] == "verified"
    assert result["completion_evidence"] == [verified["evidence"]]


@pytest.mark.parametrize("replacement", ["failed", "empty", "unsupported", "stale"])
def test_rejected_verification_replaces_previous_completion_authority(replacement):
    controller, api = _controller()
    try:
        observation = controller.execute(action="observe")
        assert (
            controller.execute(
                action="verify",
                expected_frame_id=observation["frame_id"],
                assertion="text_contains",
                value="Name",
            )["passed"]
            is True
        )
        if replacement == "failed":
            assertion, value, frame = (
                "text_contains",
                "Missing",
                observation["frame_id"],
            )
        elif replacement == "empty":
            assertion, value, frame = "text_contains", "", observation["frame_id"]
        elif replacement == "unsupported":
            assertion, value, frame = (
                "unknown_assertion",
                "Name",
                observation["frame_id"],
            )
        else:
            assertion, value, frame = "text_contains", "Name", "stale-frame"
        rejected = controller.execute(
            action="verify", expected_frame_id=frame, assertion=assertion, value=value
        )
        assert rejected.get("passed") is not True
        result = controller.final_result(summary="claimed complete")
        assert result["status"] == "failed"
        assert result["completion_evidence"] == []
    finally:
        controller.close()


@pytest.mark.parametrize("change", ["navigation", "document", "content"])
def test_final_completion_rechecks_browser_evidence_after_external_page_change(change):
    controller, api = _controller()
    try:
        observation = controller.execute(action="observe")
        assert (
            controller.execute(
                action="verify",
                expected_frame_id=observation["frame_id"],
                assertion="text_contains",
                value="Name",
            )["passed"]
            is True
        )
        if change == "navigation":
            api.page.url = "https://example.com/replacement"
        elif change == "document":
            api.page.navigation_time_origin += 1
        else:
            api.page.body_text = "Saved confirmation was removed"
        result = controller.final_result(summary="claimed complete")
        assert result["status"] == "failed"
        assert result["completion_evidence"] == []
    finally:
        controller.close()


def test_verify_uses_latest_observation_when_frame_id_is_omitted():
    controller, _api = _controller()
    first = controller.execute(action="observe")
    controller.execute(action="click", expected_frame_id=first["frame_id"], ref="e1")
    controller.execute(action="observe")

    verified = controller.execute(
        action="verify",
        assertion="text_contains",
        value="Saved",
    )

    assert verified["passed"] is True
    controller.close()


@pytest.mark.parametrize("value", ["", "   "])
def test_verify_rejects_empty_values_without_recording_evidence(value):
    controller, _api = _controller()
    observation = controller.execute(action="observe")

    verified = controller.execute(
        action="verify",
        expected_frame_id=observation["frame_id"],
        assertion="text_contains",
        value=value,
    )

    assert verified["ok"] is False
    assert verified["reason_code"] == "invalid_assertion"
    assert "value" in verified["message"]
    assert controller.final_result(summary="done")["status"] == "failed"


def test_verify_reads_current_dynamic_dom_and_keeps_matching_refs_usable():
    controller, api = _controller()
    observation = controller.execute(action="observe")
    api.page.body_text = "Saved by an asynchronous page update"

    verified = controller.execute(
        action="verify",
        expected_frame_id=observation["frame_id"],
        assertion="text_contains",
        value="Saved",
    )

    assert verified["passed"] is True
    follow_up_write = controller.execute(
        action="click",
        expected_frame_id=observation["frame_id"],
        ref="e1",
    )
    assert follow_up_write["ok"] is True


def test_model_summary_cannot_claim_success_without_runtime_verification():
    controller, _api = _controller()
    controller.execute(action="observe")

    result = controller.final_result(summary="I completed the task successfully")

    assert result["status"] == "failed"
    assert result["reason_code"] == "verification_missing"


def test_controller_closes_only_its_own_browser_session():
    controller, api = _controller()
    controller.execute(action="observe")

    controller.close()

    assert api.closed == ["br_test"]
    assert controller.session_id == ""


def test_controller_owns_browser_session_on_one_dedicated_thread():
    controller, api = _controller()
    caller_thread = threading.get_ident()
    controller.execute(action="observe")

    controller.close()

    assert api.closed == ["br_test"]
    assert "br_test" not in api._sessions
    assert len(set(api.threads)) == 1
    assert api.threads[0] != caller_thread
    assert controller.session_id == ""


def test_bound_surface_actions_use_the_turn_access_grant():
    controller, _api = _controller()
    controller.initial_url = "https://example.com/form"

    assert isinstance(controller._requires_approval(action="click"), str)

    controller.binding_id = "surface-binding"
    assert controller._requires_approval(action="click") is False


def test_bound_controller_open_forwards_exact_page_revisions():
    controller, api = _controller()
    controller.binding_id = "surface-binding"
    controller.page_revision = 31
    controller.access_revision = 32
    controller.geometry_revision = 33

    controller.execute(action="observe")

    assert api.open_arguments == {
        "engine": "app",
        "url": None,
        "binding_id": "surface-binding",
        "expected_page_revision": 31,
        "expected_access_revision": 32,
        "expected_geometry_revision": 33,
    }


def test_browser_open_forwards_exact_page_revisions_to_app_session(monkeypatch):
    from openprogram.programs.applications.browser.engine import browser as browser_api
    from openprogram.programs.applications.browser.engine._actions import open_action

    captured = {}

    def fake_open(**arguments):
        captured.update(arguments)
        return "opened"

    monkeypatch.setattr(open_action, "_open", fake_open)

    result = browser_api.execute(
        action="open",
        engine="app",
        binding_id="surface-binding",
        expected_page_revision=31,
        expected_access_revision=32,
        expected_geometry_revision=33,
    )

    assert result == "opened"
    assert captured["binding_id"] == "surface-binding"
    assert captured["expected_page_revision"] == 31
    assert captured["expected_access_revision"] == 32
    assert captured["expected_geometry_revision"] == 33


@pytest.mark.parametrize("scale", [0.125, 0.5, 1.0])
def test_bound_pointer_inputs_use_native_presentation_scale(monkeypatch, scale):
    from openprogram.interfaces.server.ws_actions import webtab

    controller, api = _controller()
    controller.binding_id = "fixed-preview"
    controller.geometry_revision = 9
    queries = []
    monkeypatch.setattr(
        webtab,
        "request_bound_tab",
        lambda binding_id, **kwargs: queries.append((binding_id, kwargs))
        or {"ok": True, "input_scale": scale},
    )
    monkeypatch.setattr(
        webtab,
        "request_bound_screenshot",
        lambda *_a, **_k: {
            "ok": True,
            "image_data_url": "data:image/png;base64,"
            + base64.b64encode(b"png").decode(),
        },
    )
    observed = controller.execute(action="observe")
    controller.execute(action="screenshot", expected_frame_id=observed["frame_id"])
    result = controller.execute(
        action="click", expected_frame_id=observed["frame_id"], x=480, y=320
    )
    assert result["ok"] is True
    assert ("mouse_click", 480 * scale, 320 * scale) in api.page.calls
    observed = controller.execute(action="observe")
    result = controller.execute(
        action="scroll", expected_frame_id=observed["frame_id"], amount=600
    )
    assert result["ok"] is True
    assert ("wheel", 0, 600) in api.page.calls
    assert all(
        binding == "fixed-preview" and kwargs["expected_geometry_revision"] == 9
        for binding, kwargs in queries
    )


def test_bound_pointer_rejects_stale_native_geometry(monkeypatch):
    from openprogram.interfaces.server.ws_actions import webtab

    controller, api = _controller()
    controller.binding_id = "fixed-preview"
    monkeypatch.setattr(webtab, "request_bound_tab", lambda *_a, **_k: {"ok": False})
    observed = controller.execute(action="observe")
    result = controller.execute(
        action="scroll", expected_frame_id=observed["frame_id"], amount=600
    )
    assert result == {"ok": False, "reason_code": "stale_observation"}
    assert not any(call[0] == "wheel" for call in api.page.calls)


def test_controller_cleanup_preserves_calling_conversation(monkeypatch):
    from openprogram.runtime.execution.run_control import (
        set_current_session_id,
        reset_current_session_id,
        get_current_session_id,
    )
    controller, api = _controller()
    original = api.execute
    identities = []
    def execute(action, **kwargs):
        identities.append((action, get_current_session_id()))
        return original(action, **kwargs)
    monkeypatch.setattr(api, 'execute', execute)
    token = set_current_session_id('conversation-one')
    closed = False
    try:
        controller.execute(action='observe')
        controller.close()
        closed = True
        assert identities == [('open', 'conversation-one'), ('close', 'conversation-one')]
    finally:
        reset_current_session_id(token)
        if not closed:
            controller.close()


def test_web_use_does_not_expose_backend_or_session_handles():
    import inspect
    from openprogram.programs._host import services as _services

    _services.load_programs()
    from openprogram.programs.applications.browser.web_use import web_use

    for name in ("backend", "web_session_id", "page_context_token"):
        assert web_use.input_meta[name]["hidden"]
        assert inspect.signature(web_use).parameters[name].default == ""
