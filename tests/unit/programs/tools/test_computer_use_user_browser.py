"""The browser target reaches the user's Chrome or Edge with the built-in browser's actions."""
from types import SimpleNamespace

from openprogram.runtime.permissions.policy import _user_browser
from openprogram.runtime.permissions.rule import parse_command
from openprogram.programs.tools.computer_use.computer_use_agent import tool
from openprogram.programs.tools.computer_use.computer_use_agent.targets import browser
from openprogram.programs.applications.browser import extension as extension_browser


class FakeClient:
    def __init__(self):
        self.calls = []

    def is_alive(self):
        return True

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        if arguments.get("target") == "bad":
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="no such ref")], isError=True)
        if name == "browser_evaluate":
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="### Result\n\"Example Domain\"")],
                                   isError=False)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=f"ran {name}"),
                                        SimpleNamespace(type="image", data="aGk=")], isError=False)


def _install(monkeypatch, browser_name="chrome"):
    fake = FakeClient()
    monkeypatch.setattr(extension_browser, "_clients", {("s", browser_name): fake})
    return fake


def test_the_same_actions_reach_the_users_chrome(monkeypatch):
    fake = _install(monkeypatch)
    result = browser.run([("open", {"url": "https://example.com"}), ("click", {"ref": "e5"}),
                          ("type", {"ref": "e7", "text": "hi"}), ("press", {"key": "Enter"})],
                         {"browser": "chrome"}, "s")
    assert not result.is_error
    assert fake.calls == [
        ("browser_tabs", {"action": "new", "url": "https://example.com"}),
        ("browser_snapshot", {}),
        ("browser_click", {"target": "e5"}),
        ("browser_type", {"target": "e7", "text": "hi"}),
        ("browser_press_key", {"key": "Enter"}),
    ]


def test_edge_is_its_own_connection_and_screenshots_come_back(monkeypatch):
    fake = _install(monkeypatch, "edge")
    result = browser.run([("screenshot", {})], {"browser": "edge"}, "s")
    assert fake.calls == [("browser_take_screenshot", {"type": "png"})]
    assert result.images == [b"hi"]
    assert extension_browser._command("edge")[-6:-4] == ["--browser", "msedge"]


def test_a_failed_step_stops_the_rest(monkeypatch):
    fake = _install(monkeypatch)
    result = browser.run([("click", {"ref": "bad"}), ("click", {"ref": "e2"})], {"browser": "chrome"}, "s")
    assert result.is_error and len(fake.calls) == 1


def test_tabs_and_read_are_the_extensions_tab_list_and_snapshot(monkeypatch):
    fake = _install(monkeypatch)
    browser.run([("tabs", {}), ("read", {"tab": 1})], {"browser": "chrome"}, "s")
    assert fake.calls == [("browser_tabs", {"action": "list"}), ("browser_tabs", {"action": "select", "index": 1}),
                          ("browser_snapshot", {})]


def test_the_users_browser_is_one_grant_outside_the_page_grant():
    call = {"target": "browser", "action": "click", "args": {"browser": "chrome", "ref": "e1"}}
    assert parse_command("computer_use_agent", call) == "browser:chrome"
    assert parse_command("computer_use_agent", {"target": "browser", "args": {"ref": "e1"}}) is None
    assert tool.requires_approval(**call) == "computer_use_agent controls your Chrome"
    assert tool.requires_approval(target="browser", action="click", args={"ref": "e1"}) is False
    assert _user_browser(call) == "chrome" and _user_browser({"target": "browser", "args": {}}) == ""
