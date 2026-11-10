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


def _acts(fake):
    """The calls that do something, without the check whether the tab is in front."""
    return [call for call in fake.calls if not call[1].get("function", "").endswith("visibilityState")]


def _install(monkeypatch, browser_name="chrome"):
    fake = FakeClient()
    monkeypatch.setattr(extension_browser, "installed", lambda name: True)
    monkeypatch.setattr(extension_browser, "_clients", {("s", browser_name): fake})
    return fake


def test_the_same_actions_reach_the_users_chrome(monkeypatch):
    fake = _install(monkeypatch)
    result = browser.run([("open", {"url": "https://example.com"}), ("click", {"ref": "e5"}),
                          ("type", {"ref": "e7", "text": "hi"}), ("press", {"key": "Enter"})],
                         {"browser": "chrome"}, "s")
    assert not result.is_error
    assert _acts(fake) == [
        ("browser_tabs", {"action": "list"}),
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
    assert result.is_error and len(_acts(fake)) == 1


def test_tabs_and_read_are_the_extensions_tab_list_and_snapshot(monkeypatch):
    fake = _install(monkeypatch)
    browser.run([("tabs", {}), ("read", {"tab": 1})], {"browser": "chrome"}, "s")
    assert fake.calls == [("browser_tabs", {"action": "list"}), ("browser_tabs", {"action": "select", "index": 1}),
                          ("browser_snapshot", {})]


def test_the_users_browser_is_one_grant_outside_the_page_grant(monkeypatch):
    monkeypatch.setattr(extension_browser, "installed", lambda name: True)
    call = {"target": "browser", "action": "click", "args": {"browser": "chrome", "ref": "e1"}}
    assert parse_command("computer_use_agent", call) == "browser:chrome"
    assert parse_command("computer_use_agent", {"target": "browser", "args": {"ref": "e1"}}) is None
    assert tool.requires_approval(**call) == "computer_use_agent controls your Chrome"
    assert tool.requires_approval(target="browser", action="click", args={"ref": "e1"}) is False
    assert _user_browser(call) == "chrome" and _user_browser({"target": "browser", "args": {}}) == ""


def test_the_extension_counts_as_installed_where_a_profile_holds_it(tmp_path, monkeypatch):
    monkeypatch.setattr(extension_browser, "_data_dir", lambda name: tmp_path / name)
    (tmp_path / "chrome" / "Profile 3" / "Extensions" / extension_browser.EXTENSION_ID).mkdir(parents=True)
    (tmp_path / "edge" / "Default" / "Extensions" / "someotherextension").mkdir(parents=True)
    assert extension_browser.installed_browsers() == ("chrome",)


def test_without_the_extension_the_guide_offers_only_the_built_in_browser(monkeypatch):
    monkeypatch.setattr(extension_browser, "installed", lambda name: False)
    text = browser.guide()
    assert 'args.browser' not in text
    assert "not reachable as web pages here" in text


def test_with_the_extension_the_guide_offers_that_browser_alone(monkeypatch):
    monkeypatch.setattr(extension_browser, "installed", lambda name: name == "edge")
    text = browser.guide()
    assert '- "edge": the user\'s own Edge' in text
    assert '"chrome"' not in text


def test_naming_a_browser_without_the_extension_starts_nothing(monkeypatch):
    monkeypatch.setattr(extension_browser, "installed", lambda name: False)
    monkeypatch.setattr(extension_browser, "_client", lambda *a: (_ for _ in ()).throw(AssertionError("started")))
    call = {"target": "browser", "action": "click", "args": {"browser": "chrome", "ref": "e1"}}
    assert tool.requires_approval(**call) is False
    result = tool.computer_use_agent(**call)
    assert result.is_error and "has no Playwright Extension" in result.text


class _HiddenTabClient:
    def __init__(self, visibility):
        self.visibility = visibility
        self.calls = []

    def call(self, name, arguments):
        from types import SimpleNamespace
        self.calls.append((name, arguments))
        text = f'### Result\n"{self.visibility}"' if arguments.get("function", "").endswith("visibilityState") else "done"
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], isError=False)


def _extension_browser(client):
    from openprogram.programs.applications.browser.extension import ExtensionBrowser
    browser = ExtensionBrowser.__new__(ExtensionBrowser)
    browser.browser, browser.client = "chrome", client
    return browser


def test_click_in_a_tab_behind_others_is_sent_in_the_page():
    client = _HiddenTabClient("hidden")
    assert _extension_browser(client).run("act", {"action": "click", "ref": "e5"})["ok"]
    assert [name for name, _ in client.calls] == ["browser_evaluate", "browser_evaluate"]
    assert client.calls[1][1]["target"] == "e5"


def test_click_in_the_front_tab_stays_a_real_click():
    client = _HiddenTabClient("visible")
    assert _extension_browser(client).run("act", {"action": "click", "ref": "e5"})["ok"]
    assert client.calls[-1][0] == "browser_click"


def test_the_connected_page_becomes_the_working_tab():
    class Client(_HiddenTabClient):
        def call(self, name, arguments):
            from types import SimpleNamespace
            self.calls.append((name, arguments))
            text = "- 0: (current) [Welcome](chrome-extension://x/connect.html?a=1)" if name == "browser_tabs" else "ok"
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], isError=False)

    client = Client("visible")
    _extension_browser(client).run("observe", {"url": "https://example.com"})
    assert [name for name, _ in client.calls] == ["browser_tabs", "browser_navigate", "browser_snapshot"]
