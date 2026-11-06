"""computer_use_agent routing and the browser and vm targets, without a host screen."""
import json

import pytest

from openprogram.programs.tools.computer_use.computer_use_agent.desktop import backends
from openprogram.programs._host.execution import ToolReturn
from openprogram.programs.tools.computer_use.computer_use_agent import fresh
from openprogram.programs.tools.computer_use.computer_use_agent import tool as entry
from openprogram.programs.tools.computer_use.computer_use_agent.targets import browser, vm

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


# ----------------------------------------------------------------- routing

def test_steps_take_nested_or_flat_arguments():
    assert entry._steps("click", {"ref": "e1"}, None) == [("click", {"ref": "e1"})]
    steps = entry._steps("", {}, [{"action": "type", "args": {"ref": "e3", "text": "hi"}},
                                  {"action": "press", "key": "Enter"}])
    assert steps == [("type", {"ref": "e3", "text": "hi"}), ("press", {"key": "Enter"})]
    assert entry._steps("", {}, None) == []


def test_code_and_actions_are_one_or_the_other(monkeypatch):
    monkeypatch.setattr(browser, "run", lambda *a: ToolReturn(text="ran"))
    result = entry.computer_use_agent(target="browser", action="observe", code="pass")
    assert result.is_error and "not both" in result.text


def test_a_target_that_is_not_set_up_says_how(monkeypatch):
    monkeypatch.setattr(vm, "url", lambda: "")
    result = entry.computer_use_agent(target="vm")
    assert result.is_error and "computer_use.vm_url" in result.text


def test_json_results_keep_their_data(monkeypatch):
    monkeypatch.setattr(browser, "open_target", lambda args, session: ToolReturn(json_data={"pages": []}))
    result = entry.computer_use_agent(target="browser")
    assert result.json_data == {"pages": []}


def test_a_spawned_agent_holds_the_marked_guides_in_its_brief(monkeypatch):
    from openprogram.programs._authoring import guides
    seen = {}

    def spawn(target, args, brief, guide, session, **kwargs):
        seen.update(target=target, guide=guide, kwargs=kwargs)
        return ToolReturn(text="done")
    monkeypatch.setattr(fresh, "run", spawn)
    # The app target is available whatever the host is.
    monkeypatch.setattr(backends, "support", lambda: {"available": True})
    assert entry.computer_use_agent(target="app", context="fresh", brief="b", args={"app": "Notes"}).text == "done"
    assert seen["kwargs"]["needs_grant"] is True
    # The spawned agent's first call finds every guide in its request already.
    for name in ("computer_use_agent.app", "computer_use_agent.code"):
        assert guides.marker(name) in seen["guide"]
    token = guides.begin_loop()
    try:
        guides.observe_request([{"content": seen["guide"]}])
        assert guides.due("computer_use_agent", {"target": "app", "code": "pass"}, failed=False) == []
        assert guides.missing_required("computer_use_agent", {"target": "app", "code": "pass"}) == []
    finally:
        guides.end_loop(token)


def test_fresh_needs_a_brief_and_cannot_nest(monkeypatch):
    monkeypatch.setattr(fresh, "nested", lambda: False)
    result = fresh.run("app", {"app": "Notes"}, "  ", "guide", "s", needs_grant=True)
    assert result.is_error and "needs brief" in result.text
    monkeypatch.setattr(fresh, "nested", lambda: True)
    result = fresh.run("app", {"app": "Notes"}, "do it", "guide", "s", needs_grant=True)
    assert result.is_error and "inherit" in result.text


def test_fresh_prompt_names_the_target_and_carries_the_guide():
    text = fresh.prompt("app", {"app": "Numbers"}, "Sum column B.", "GUIDE")
    assert text.startswith("Sum column B.") and 'target="app", args={"app": "Numbers"}' in text
    assert "GUIDE" in text


# ----------------------------------------------------------------- browser

def test_browser_actions_reach_the_tab_driver_and_read_as_text(monkeypatch):
    from openprogram.programs.applications.browser import tabs

    calls = []

    class _Driver:
        def run(self, action, args, session):
            calls.append((action, args, session))
            return {"ok": True, "tab": "t2", "url": "https://a.test/", "title": "A", "done": "clicked e2",
                    "changes": '- <changed> button "Go" [ref=e2]'}

    monkeypatch.setattr(tabs, "driver", lambda: _Driver())
    result = browser.run([("click", {"ref": "e2"})], {"tab": "t2"}, "s")
    assert calls == [("click", {"tab": "t2", "ref": "e2"}, "s")]
    assert result.text.splitlines()[:3] == ["clicked e2", "tab t2 · A · https://a.test/", "changes:"]


def test_browser_steps_stop_at_the_first_failure(monkeypatch):
    from openprogram.programs.applications.browser import tabs

    replies = iter([{"ok": True, "done": "typed"}, {"ok": False, "reason_code": "element_gone", "error": "gone"},
                    {"ok": True}])
    monkeypatch.setattr(tabs, "driver", lambda: type("D", (), {"run": lambda self, *a: next(replies)})())
    result = browser.run([("type", {}), ("click", {}), ("press", {})], {}, "s")
    assert result.is_error and len(result.json_data) == 2
    assert result.text.endswith("step 2 failed; the steps after it did not run")


def test_browser_approval_asks_for_uploads_and_external_origins_only():
    assert browser.approval([("click", {"ref": "e1"})], {}) is False
    assert browser.approval([("navigate", {"url": "http://localhost:3000/"})], {}) is False
    assert "https://example.com" in browser.approval([("navigate", {"url": "https://example.com/a"})], {})
    assert "Upload" in browser.approval([("upload", {"path": "/tmp/x"})], {})


# ----------------------------------------------------------------- vm

def test_vm_steps_become_pyautogui_with_literal_values():
    assert "pyautogui.click(10, 20, button=\"right\", clicks=2" in vm._script(
        "click", {"x": 10.4, "y": 20, "mouse_button": "right", "click_count": 2})
    assert vm._script("type_text", {"text": "a\"); import os; ("}) == \
        'import pyautogui; pyautogui.write("a\\"); import os; (", interval=0.02)'
    assert vm._script("press_key", {"key": "Ctrl+Shift+T"}).endswith('hotkey(*["ctrl", "shift", "t"])')
    assert "pyautogui.scroll(-3)" in vm._script("scroll", {"direction": "down", "clicks": 3})
    with pytest.raises(vm.VMError):
        vm._script("click", {"x": "left"})


def test_vm_run_executes_then_returns_a_new_screenshot(monkeypatch):
    executed = []
    monkeypatch.setattr(vm, "url", lambda: "http://vm:5000")
    monkeypatch.setattr(vm, "screenshot", lambda base: PNG)
    monkeypatch.setattr(vm, "_execute", lambda base, script: executed.append(script))
    monkeypatch.setattr(vm.time, "sleep", lambda s: None)
    result = vm.run([("click", {"x": 1, "y": 2}), ("type_text", {"text": "x"})], {}, "s")
    assert not result.is_error and result.images == [PNG] and len(executed) == 2
    assert result.text.startswith("Done:\n1. click\n2. type_text")


def test_vm_rule_names_the_endpoint(monkeypatch):
    from openprogram.runtime.permissions.rule import parse_command
    monkeypatch.setattr(vm, "url", lambda: "http://vm:5000")
    assert parse_command("computer_use_agent", {"target": "vm", "action": "click"}) == "vm:http://vm:5000"
    assert entry.requires_approval(target="vm", action="screenshot") == "computer_use_agent controls vm:http://vm:5000"


def test_settings_validate_the_vm_url():
    from openprogram.state.settings import SETTINGS
    spec = next(item for item in SETTINGS if item.key == "computer_use.vm_url")
    assert spec.validate("") is None and spec.validate("http://10.0.0.2:5000") is None
    assert spec.validate("10.0.0.2:5000") and json.dumps(spec.default) == '""'


def test_the_guides_ship_in_the_wheel():
    import fnmatch
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    patterns = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["openprogram"]
    guides = sorted((root / "openprogram/programs/tools/computer_use/computer_use_agent/guides").glob("*.md"))
    assert guides
    for path in guides:
        rel = path.relative_to(root / "openprogram").as_posix()
        assert any(fnmatch.fnmatch(rel, pattern) for pattern in patterns), rel


def test_opening_the_app_target_without_an_app_only_lists_apps():
    from openprogram.host.system_access import _desktop_operation

    assert entry.requires_approval(target="app") is False
    assert entry.requires_approval(target="app", args={"app": "Notes"})
    assert _desktop_operation("computer_use_agent", {"target": "app"}) is None
    assert _desktop_operation("computer_use_agent", {"target": "app", "args": {"app": "Notes"}})
    assert _desktop_operation("computer_use_agent", {"target": "app", "context": "fresh", "brief": "b"})


def test_a_click_that_opened_a_file_chooser_tells_the_model_how_to_answer_it():
    text = browser.render({"ok": True, "done": "clicked e5", "tab": "t1", "url": "https://x.test/", "changes": "",
                           "file_chooser": {"multiple": False, "accept": ".pdf"}})
    assert "the page opened a file chooser for .pdf; upload(path) without ref answers it" in text
    assert "file chooser" not in browser.render({"ok": True, "done": "clicked e5", "tab": "t1"})
