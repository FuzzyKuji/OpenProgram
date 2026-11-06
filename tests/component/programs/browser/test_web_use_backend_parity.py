from __future__ import annotations

from types import SimpleNamespace

import pytest


BACKENDS = (
    "playwright_mcp",
    "chrome_devtools_mcp",
    "open_claude_chrome",
)

ACTION_ARGUMENTS = {
    "navigate": {"url": "https://example.test/next"},
    "click": {"ref": "e1"},
    "type": {"ref": "e1", "text": "hello"},
    "press": {"ref": "e1", "key": "Enter"},
    "scroll": {"amount": 240},
    "hover": {"ref": "e1"},
    "select": {"ref": "e1", "value": "one"},
}

EXPECTED_MCP_WRITES = {
    "playwright_mcp": {
        "browser_navigate",
        "browser_click",
        "browser_type",
        "browser_press_key",
        "browser_mouse_wheel",
        "browser_hover",
        "browser_select_option",
    },
    "chrome_devtools_mcp": {
        "navigate_page",
        "click",
        "fill",
        "press_key",
        "evaluate_script",
        "hover",
    },
}


class _Result:
    def __init__(self, text="", *, structured=None, error=False):
        self.content = [SimpleNamespace(text=text)] if text else []
        self.structuredContent = structured
        self.isError = error


class _Page:
    marker_value = ""

    def evaluate(self, script, argument=None):
        if script.lstrip().startswith("() => Array.from("):
            return []
        if "Object.defineProperty" in script:
            self.marker_value = argument[1]
        return None


class _Controller:
    def __init__(self, backend):
        self.backend = backend
        self.binding_id = ""
        self.page_revision = 0
        self.access_revision = 0
        self.geometry_revision = 0
        self.page = _Page()
        self.frame_number = 0
        self.frame = None
        self.mutations = []
        self.write_attempts = 0
        self.invalidated = 0
        self.closed = 0
        self.fail_writes = False
        self.agent_cursor_states = []
        self.fail_agent_cursor = False

    def _new_frame(self):
        self.frame_number += 1
        self.frame = {
            "frame_id": f"frame-{self.frame_number}",
            "url": "https://example.test/",
            "title": "Parity",
            "elements": [{"ref": "e1", "role": "button", "name": "Save"}],
            "aria_snapshot": '- button "Save"',
            "target": {"tab_id": "tab-1", "target_id": "target-1"},
        }
        return dict(self.frame)

    def capture_observation(self, capture):
        return capture()

    def execute(self, **arguments):
        from openprogram.programs import ToolReturn

        action = arguments["action"]
        if action == "observe":
            return self._new_frame()
        frame_id = arguments.get("expected_frame_id")
        if self.frame is None or frame_id != self.frame["frame_id"]:
            return {"ok": False, "reason_code": "stale_observation"}
        if action == "verify":
            passed = arguments.get("value") == "done"
            return {
                "ok": True,
                "passed": passed,
                "evidence": {
                    "assertion": arguments.get("assertion"),
                    "value": arguments.get("value"),
                    "frame_id": frame_id,
                    "passed": passed,
                },
            }
        if action == "screenshot":
            return ToolReturn(
                images=[b"\x89PNG\r\n\x1a\nfake"],
                json_data={
                    "frame_id": frame_id,
                    "viewport": {"width": 960, "height": 640},
                },
            )
        if action not in ACTION_ARGUMENTS:
            return {"ok": False, "reason_code": "unsupported_action"}
        self.write_attempts += 1
        if self.fail_writes:
            if isinstance(self.fail_writes, BaseException):
                raise self.fail_writes
            raise RuntimeError("backend write failed")
        self.mutations.append(action)
        self.frame = None
        return {"ok": True, "observe_required": True}

    def prepare_external_action(self, arguments):
        frame_id = arguments.get("expected_frame_id")
        if self.frame is None or frame_id != self.frame["frame_id"]:
            return {"ok": False, "reason_code": "stale_observation"}
        return None

    def set_agent_cursor_armed(self, armed):
        self.agent_cursor_states.append(bool(armed))
        if self.fail_agent_cursor:
            raise RuntimeError("cursor injection failed")

    def evaluate_bound_page(self, script, argument=None):
        return self.page.evaluate(script, argument)

    def record_external_mutation(self, detail, keep_frame=False):
        action = detail.rsplit(":", 1)[-1]
        self.mutations.append(action)
        self.frame = None
        return {"ok": True, "observe_required": True}

    def invalidate_external_frame(self):
        self.invalidated += 1
        self.frame = None

    def revoke_screenshot(self):
        pass

    def close(self):
        self.closed += 1


class _Client:
    def __init__(self, backend, controller):
        self.backend = backend
        self.controller = controller
        self.calls = []
        self.write_calls = []
        self.fail_writes = False
        self.closed = 0

    def call(self, name, arguments):
        arguments = dict(arguments)
        self.calls.append((name, arguments))
        if name == "list_pages":
            return _Result(structured={"pages": [{"id": 7}]})
        if name == "browser_snapshot":
            return _Result('- button "Save" [ref=e1]')
        if name == "take_snapshot":
            return _Result('- button "Save" [uid=e1]')
        if (
            name == "evaluate_script"
            and "globalThis" in str(arguments.get("function") or "")
        ):
            return _Result(self.controller.page.marker_value)
        if arguments.get("function") == "(element) => element.focus()":
            # press with a ref focuses it first; the key is the write.
            return _Result("done")
        assert name in EXPECTED_MCP_WRITES[self.backend]
        self._validate_write(name, arguments)
        self.write_calls.append((name, arguments))
        if isinstance(self.fail_writes, BaseException):
            raise self.fail_writes
        return _Result("failed" if self.fail_writes else "done", error=self.fail_writes)

    def _validate_write(self, name, arguments):
        if self.backend == "playwright_mcp":
            expected = {
                "browser_navigate": {"url": "https://example.test/next"},
                "browser_click": {"target": "e1"},
                "browser_type": {"target": "e1", "text": "hello"},
                "browser_press_key": {"key": "Enter"},
                "browser_mouse_wheel": {"deltaY": 240, "deltaX": 0},
                "browser_hover": {"target": "e1"},
                "browser_select_option": {"target": "e1", "values": ["one"]},
            }
            assert arguments == expected[name]
            return
        assert arguments.get("pageId") == 7
        if name == "navigate_page":
            assert arguments == {
                "type": "url", "url": "https://example.test/next", "pageId": 7,
            }
        elif name == "click":
            assert arguments == {"uid": "e1", "pageId": 7}
        elif name == "fill":
            assert arguments == {"uid": "e1", "value": arguments["value"], "pageId": 7}
            assert arguments["value"] in {"hello", "one"}
        elif name == "press_key":
            assert arguments == {"key": "Enter", "pageId": 7}
        elif name == "evaluate_script":
            assert "window.scrollBy(0, 240)" in arguments["function"]
        elif name == "hover":
            assert arguments == {"uid": "e1", "pageId": 7}

    def close(self):
        self.closed += 1


def _registry(monkeypatch):
    from openprogram.programs.applications.browser.web_use.runtime import (
        WebUseSessionRegistry,
        ControllerBackend,
    )
    from openprogram.programs.applications.browser.web_use.mcp_backends import (
        OfficialMCPPageBackend,
    )
    from openprogram.programs.applications.browser import chrome as _chrome_bootstrap

    monkeypatch.setattr(_chrome_bootstrap, "desktop_app_ws_url", lambda: "ws://cdp")
    controllers = {name: _Controller(name) for name in BACKENDS}
    clients = {
        name: _Client(name, controllers[name])
        for name in BACKENDS[:2]
    }
    adapters = {
        name: OfficialMCPPageBackend(
            name,
            lambda name=name: controllers[name],
            client_factory=lambda _command, name=name: clients[name],
        )
        for name in BACKENDS[:2]
    }
    adapters["open_claude_chrome"] = ControllerBackend(
        "open_claude_chrome", lambda: controllers["open_claude_chrome"],
    )
    released = []
    registry = WebUseSessionRegistry(
        adapters=adapters,
        binding_validator=lambda _binding: {"ok": True},
        binding_revision_resolver=lambda _binding: {},
        release_context=lambda context: released.append(context),
    )
    return registry, controllers, clients, released


def _observe(registry, backend):
    return registry.execute(
        command="observe",
        backend=backend,
        binding_id="binding-1",
        page_key=f"page-{backend}",
        owner_id="owner-1",
        page_context={"context_id": f"ctx-{backend}"},
    )


def _write_count(backend, controllers, clients):
    return (
        len(clients[backend].write_calls)
        if backend in clients
        else controllers[backend].write_attempts
    )


@pytest.mark.parametrize("backend", BACKENDS)
def test_backend_parity_lifecycle(monkeypatch, backend):
    from openprogram.programs import ToolReturn
    from openprogram.programs.applications.browser.web_use import _result_for_prompt

    registry, controllers, clients, released = _registry(monkeypatch)
    observed = _observe(registry, backend)
    session_id = observed["web_session_id"]
    frame_id = observed["frame_id"]
    assert observed["backend"] == backend
    assert observed["aria_snapshot"]

    writes_before_rejections = _write_count(backend, controllers, clients)
    missing = registry.execute(
        command="act", web_session_id=session_id, owner_id="owner-1",
        arguments={"ref": "e1"},
    )
    assert missing == {
        "ok": False,
        "reason_code": "invalid_arguments",
        "missing_arguments": ["action"],
        "web_session_id": session_id,
        "backend": backend,
    }
    assert _write_count(backend, controllers, clients) == writes_before_rejections

    stale = registry.execute(
        command="act", web_session_id=session_id, owner_id="owner-1",
        arguments={"action": "click", "expected_frame_id": "old", "ref": "e1"},
    )
    assert stale["reason_code"] == "stale_observation"
    assert _write_count(backend, controllers, clients) == writes_before_rejections

    # A drag with no endpoints is refused before anything is sent; the fake
    # native controller does not implement drag at all.
    endless = registry.execute(
        command="act", web_session_id=session_id, owner_id="owner-1",
        arguments={"action": "drag", "expected_frame_id": frame_id},
    )
    assert endless["reason_code"] == (
        "unsupported_action" if backend == "open_claude_chrome" else "invalid_arguments")
    assert _write_count(backend, controllers, clients) == writes_before_rejections

    acted = registry.execute(
        command="act", web_session_id=session_id, owner_id="owner-1",
        arguments={"action": "click", "expected_frame_id": frame_id, "ref": "e1"},
    )
    assert acted["ok"] is True
    assert acted["observe_required"] is True

    observed = registry.execute(
        command="observe", web_session_id=session_id, owner_id="owner-1",
    )
    frame_id = observed["frame_id"]
    passed = registry.execute(
        command="verify", web_session_id=session_id, owner_id="owner-1",
        arguments={
            "expected_frame_id": frame_id,
            "assertion": "text_contains",
            "value": "done",
        },
    )
    failed = registry.execute(
        command="verify", web_session_id=session_id, owner_id="owner-1",
        arguments={
            "expected_frame_id": frame_id,
            "assertion": "text_contains",
            "value": "missing",
        },
    )
    assert passed["passed"] is True
    assert failed["passed"] is False
    assert passed["evidence"]["frame_id"] == frame_id

    screenshot = registry.execute(
        command="act", web_session_id=session_id, owner_id="owner-1",
        arguments={"action": "screenshot", "expected_frame_id": frame_id},
    )
    assert isinstance(screenshot, ToolReturn)
    assert len(screenshot.images) == 1
    assert screenshot.images[0].startswith(b"\x89PNG\r\n\x1a\n")
    assert set(_result_for_prompt(screenshot)) == {
        "frame_id", "viewport", "image_attached",
    }
    screenshot.images.clear()

    closed = registry.execute(
        command="close", web_session_id=session_id, owner_id="owner-1",
    )
    assert closed["ok"] is True
    assert closed["closed"] is True
    missing = registry.execute(
        command="observe", web_session_id=session_id, owner_id="owner-1",
    )
    assert missing["reason_code"] == "web_session_not_found"
    assert controllers[backend].closed == 1
    assert released == [{"context_id": f"ctx-{backend}"}]
    if backend in clients:
        assert clients[backend].closed == 1

    reacquired = _observe(registry, backend)
    assert reacquired["frame_id"]
    registry.execute(
        command="close",
        web_session_id=reacquired["web_session_id"],
        owner_id="owner-1",
    )
    assert released == [
        {"context_id": f"ctx-{backend}"},
        {"context_id": f"ctx-{backend}"},
    ]


@pytest.mark.parametrize("backend", BACKENDS)
def test_backend_parity_allows_each_action_once(monkeypatch, backend):
    registry, controllers, clients, _released = _registry(monkeypatch)
    observed = _observe(registry, backend)
    session_id = observed["web_session_id"]

    for action, extra in ACTION_ARGUMENTS.items():
        before = _write_count(backend, controllers, clients)
        result = registry.execute(
            command="act", web_session_id=session_id, owner_id="owner-1",
            arguments={
                "action": action,
                "expected_frame_id": observed["frame_id"],
                **extra,
            },
        )
        assert result["ok"] is True
        assert result["observe_required"] is True
        after = _write_count(backend, controllers, clients)
        assert after == before + 1
        observed = registry.execute(
            command="observe", web_session_id=session_id, owner_id="owner-1",
        )


@pytest.mark.parametrize("backend", BACKENDS[:2])
def test_official_mcp_click_arms_only_the_exact_page_cursor(monkeypatch, backend):
    registry, controllers, _clients, _released = _registry(monkeypatch)
    observed = _observe(registry, backend)

    result = registry.execute(
        command="act",
        web_session_id=observed["web_session_id"],
        owner_id="owner-1",
        arguments={
            "action": "click",
            "expected_frame_id": observed["frame_id"],
            "ref": "e1",
        },
    )

    assert result["ok"] is True
    assert controllers[backend].agent_cursor_states == [True, False]


def test_cursor_feedback_failure_does_not_change_official_mcp_click(monkeypatch):
    registry, controllers, _clients, _released = _registry(monkeypatch)
    backend = "playwright_mcp"
    observed = _observe(registry, backend)
    controllers[backend].fail_agent_cursor = True

    result = registry.execute(
        command="act",
        web_session_id=observed["web_session_id"],
        owner_id="owner-1",
        arguments={
            "action": "click",
            "expected_frame_id": observed["frame_id"],
            "ref": "e1",
        },
    )

    assert result["ok"] is True
    assert controllers[backend].agent_cursor_states == [True, False]


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize(
    "failure, reason_code",
    [(True, "backend_action_failed"), (TimeoutError("timed out"), "timeout")],
)
def test_backend_parity_normalizes_action_failure_without_fallback(
    monkeypatch, backend, failure, reason_code,
):
    registry, controllers, clients, _released = _registry(monkeypatch)
    observed = _observe(registry, backend)
    session_id = observed["web_session_id"]
    if backend in clients:
        clients[backend].fail_writes = failure
    else:
        controllers[backend].fail_writes = failure
    writes_before = _write_count(backend, controllers, clients)

    result = registry.execute(
        command="act", web_session_id=session_id, owner_id="owner-1",
        arguments={
            "action": "click",
            "expected_frame_id": observed["frame_id"],
            "ref": "e1",
        },
    )

    assert result["ok"] is False
    assert result["reason_code"] == reason_code
    assert result["observe_required"] is True
    assert controllers[backend].invalidated == 1
    assert _write_count(backend, controllers, clients) == writes_before + 1
    for other in BACKENDS:
        if other == backend:
            continue
        assert controllers[other].mutations == []
        if other in clients:
            assert clients[other].write_calls == []


def test_open_claude_backend_normalizes_real_playwright_timeout(monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    PlaywrightTimeoutError = playwright.TimeoutError

    registry, controllers, clients, _released = _registry(monkeypatch)
    backend = "open_claude_chrome"
    observed = _observe(registry, backend)
    controllers[backend].fail_writes = PlaywrightTimeoutError("timed out")

    result = registry.execute(
        command="act",
        web_session_id=observed["web_session_id"],
        owner_id="owner-1",
        arguments={
            "action": "click",
            "expected_frame_id": observed["frame_id"],
            "ref": "e1",
        },
    )

    assert result["reason_code"] == "timeout"
    assert result["observe_required"] is True
    assert controllers[backend].invalidated == 1
    assert controllers[backend].write_attempts == 1
    assert all(client.write_calls == [] for client in clients.values())


@pytest.mark.parametrize("backend", BACKENDS[:2])
@pytest.mark.parametrize("action", ["point", "ref", "scroll", "hover"])
def test_scaled_preview_preserves_mcp_reference_namespace(monkeypatch, backend, action):
    registry, controllers, clients, _ = _registry(monkeypatch)
    observed = _observe(registry, backend)
    controller = controllers[backend]
    controller.pointer_scale = lambda: 0.125
    hovered = []
    controller.hover_external_ref = lambda attr, frame: hovered.append((attr, frame)) or {"ok": True}
    calls = []
    clients[backend].call = lambda name, args: calls.append((name, dict(args))) or _Result("done")
    args = {"action": "click" if action in {"point", "ref"} else action,
            "expected_frame_id": observed["frame_id"]}
    if action == "point":
        args.update(x=960, y=540)
    elif action in {"ref", "hover"}:
        args["ref"] = "upstream-only-ref"
    else:
        args["amount"] = 600
    result = registry.execute(command="act", web_session_id=observed["web_session_id"],
                              owner_id="owner-1", arguments=args)
    assert result["ok"] is True
    name, params = calls[-1]
    if action == "point":
        assert params["x"] == 120
        assert params["y"] == 67.5
    elif action == "scroll":
        if backend == "playwright_mcp":
            assert params["deltaY"] == 600
        else:
            assert "window.scrollBy(0, 600)" in params["function"]
    else:
        if backend == "playwright_mcp":
            assert name == "browser_evaluate"
            assert params["target"] == "upstream-only-ref"
        else:
            assert name == "evaluate_script"
            assert params["args"] == ["upstream-only-ref"]
        if action == "ref":
            assert "element.click()" in params["function"]
        else:
            assert hovered[0][0] in params["function"]
            assert hovered[0][1] == observed["frame_id"]


@pytest.mark.parametrize('backend', BACKENDS)
def test_upload_delegates_to_owned_controller_without_upstream_file_access(monkeypatch, backend):
    registry, controllers, clients, _ = _registry(monkeypatch)
    original_frame = controllers[backend]._new_frame
    def file_frame():
        frame = original_frame()
        frame['elements'] = [{'ref': 'e1', 'input_type': 'file', 'name': 'Attachment'}]
        return frame
    monkeypatch.setattr(controllers[backend], '_new_frame', file_frame)
    observed = _observe(registry, backend)
    file_ref = observed['elements'][0]['ref']
    calls = []
    def select(**kwargs):
        kwargs['before_dispatch']()
        calls.append(kwargs)
        return {'ok': True, 'observe_required': True, 'server_acceptance_verified': False}
    monkeypatch.setattr(controllers[backend], 'execute', select)
    before = _write_count(backend, controllers, clients)
    try:
        result = registry.execute(command='act', web_session_id=observed['web_session_id'], owner_id='owner-1', before_dispatch=lambda: None,
            arguments={'action': 'upload', 'ref': file_ref, 'path': '/approved/fixture.txt', 'expected_frame_id': observed['frame_id']})
        assert result['ok'] is True, result
        assert result['server_acceptance_verified'] is False
        assert len(calls) == 1
        assert calls[0]['path'] == '/approved/fixture.txt'
        assert _write_count(backend, controllers, clients) == before
    finally:
        registry.release_owner('owner-1')
