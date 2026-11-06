"""web_use parity actions: argument parsing, MCP mapping, and the page scripts in a real Chromium."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from openprogram.programs.applications.browser.web_use import page_actions as pa
from openprogram.programs.applications.browser.web_use.mcp_backends import OfficialMCPPageBackend
from openprogram.programs.applications.browser.contract import normalize_web_use_arguments, web_use_parameters


# ----------------------------------------------------------------- arguments

def test_modifiers_accept_mac_and_pc_names_once_each():
    assert pa.modifiers("cmd+shift") == ["Meta", "Shift"]
    assert pa.modifiers("Ctrl, alt, ctrl") == ["Control", "Alt"]
    with pytest.raises(pa.ActionError) as error:
        pa.modifiers("hyper")
    assert error.value.reason_code == "invalid_modifiers"


def test_scroll_amount_keeps_its_old_meaning_without_a_direction():
    assert pa.scroll_delta({}) == (0, 500)
    assert pa.scroll_delta({"amount": -300}) == (0, -300)
    assert pa.scroll_delta({"amount": -300, "direction": "left"}) == (-300, 0)
    assert pa.scroll_delta({"amount": 200, "direction": "up"}) == (0, -200)


@pytest.mark.parametrize("arguments, code", [
    ({"mouse_button": "back"}, "invalid_mouse_button"),
    ({"click_count": 4}, "invalid_click_count"),
    ({"click_count": "two"}, "invalid_click_count"),
])
def test_click_options_are_checked(arguments, code):
    with pytest.raises(pa.ActionError) as error:
        pa.click_options(arguments)
    assert error.value.reason_code == code


def test_paste_offers_markdown_as_html_and_html_with_a_plain_fallback():
    assert pa.paste_payload({"text": "**hi**", "format": "md"})["html"].strip() == "<p><strong>hi</strong></p>"
    assert pa.paste_payload({"text": "<b>a</b> &amp; b", "format": "html"})["text"] == "a & b"
    assert pa.paste_payload({"text": "plain"}) == {"text": "plain", "html": ""}


def test_new_actions_and_fields_are_in_the_schema_and_lifted_from_the_top_level():
    act = web_use_parameters()["allOf"][0]["then"]["properties"]["arguments"]["properties"]
    for action in pa.PARITY_ACTIONS:
        assert action in act["action"]["enum"]
    assert {"mouse_button", "click_count", "modifiers", "to_ref", "direction", "format", "selection_type",
            "duration"} <= set(act)
    lifted = normalize_web_use_arguments({"command": "act", "action": "drag", "ref": "e1", "to_ref": "e2"})
    assert lifted["arguments"] == {"action": "drag", "ref": "e1", "to_ref": "e2"}


# ----------------------------------------------------------------- MCP mapping

def _adapter(name):
    adapter = OfficialMCPPageBackend.__new__(OfficialMCPPageBackend)
    adapter.name = name
    return adapter, SimpleNamespace(state={"upstream_page": 3})


def test_playwright_maps_clicks_drags_and_history_to_native_tools():
    adapter, session = _adapter("playwright_mcp")
    assert adapter._action_call(session, {"action": "click", "ref": "e4", "mouse_button": "right",
                                          "modifiers": "shift"}) == (
        "browser_click", {"target": "e4", "button": "right", "modifiers": ["Shift"]})
    assert adapter._action_call(session, {"action": "click", "ref": "e4"}) == ("browser_click", {"target": "e4"})
    assert adapter._action_call(session, {"action": "drag", "ref": "e1", "to_ref": "e2"}) == (
        "browser_drag", {"startTarget": "e1", "endTarget": "e2"})
    assert adapter._action_call(session, {"action": "back"}) == ("browser_navigate_back", {})
    assert adapter._action_call(session, {"action": "scroll", "amount": 120, "direction": "right"}) == (
        "browser_mouse_wheel", {"deltaX": 120, "deltaY": 0})


def test_devtools_dispatches_a_right_click_in_the_page_and_navigates_history_natively():
    adapter, session = _adapter("chrome_devtools_mcp")
    name, params = adapter._action_call(session, {"action": "click", "ref": "e4", "mouse_button": "right"})
    assert name == "evaluate_script" and params["args"] == ["e4"] and '"button": "right"' in params["function"]
    assert adapter._action_call(session, {"action": "reload"}) == ("navigate_page", {"type": "reload", "pageId": 3})


@pytest.mark.parametrize("name, arguments", [
    ("playwright_mcp", {"action": "click", "ref": "e1", "click_count": 3}),
    ("playwright_mcp", {"action": "click", "x": 1, "y": 2, "modifiers": "cmd"}),
    ("chrome_devtools_mcp", {"action": "drag", "x": 1, "y": 2, "to_x": 3, "to_y": 4}),
    ("chrome_devtools_mcp", {"action": "press", "key": "a", "duration": 1}),
])
def test_options_a_backend_cannot_honour_fail_before_anything_is_sent(name, arguments):
    adapter, session = _adapter(name)
    with pytest.raises(pa.ActionError) as error:
        adapter._action_call(session, arguments)
    assert error.value.reason_code == "unsupported_option"


def test_inlined_scripts_throw_when_the_page_reports_failure():
    source = pa.bound_call(pa.SELECT_TEXT_SCRIPT, {"text": "x", "prefix": "", "suffix": "", "kind": "text"},
                           require="ok")
    assert source.startswith("(element) => { const r = ") and "throw new Error" in source
    assert json.dumps({"text": "x", "prefix": "", "suffix": "", "kind": "text"}, ensure_ascii=False) in source


# ----------------------------------------------------------------- scripts in Chromium

_PAGE = """
<input id=field value="hello world">
<div id=box style="height:60px;overflow:auto"><div id=inner style="height:600px">inside</div></div>
<p id=para>alpha <b>beta</b> gamma</p>
<div id=rich contenteditable>start</div>
<button id=btn>go</button>
<script>
  window.events = [];
  for (const type of ["click", "dblclick", "contextmenu", "auxclick", "mousedown"])
    btn.addEventListener(type, e => events.push([type, e.detail, e.button, e.shiftKey]));
</script>
"""


@pytest.fixture(scope="module")
def page():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as runner:
        try:
            browser = runner.chromium.launch()
        except Exception as exc:  # no browser downloaded on this machine
            pytest.skip(f"Chromium is not available: {exc}")
        tab = browser.new_page()
        yield tab
        browser.close()


@pytest.fixture
def fresh(page):
    page.set_content(_PAGE)
    return page


def test_pointer_script_dispatches_double_right_and_modifier_clicks(fresh):
    button = fresh.locator("#btn")
    button.evaluate(pa.POINTER_SCRIPT, {"button": "left", "count": 2, "flags": {"shiftKey": True}})
    button.evaluate(pa.POINTER_SCRIPT, {"button": "right", "count": 1, "flags": {}})
    events = fresh.evaluate("events")
    assert ["click", 1, 0, True] in events and ["click", 2, 0, True] in events
    assert ["dblclick", 2, 0, True] in events and ["contextmenu", 1, 2, False] in events


def test_scroll_script_scrolls_the_nearest_scrollable_container(fresh):
    result = fresh.locator("#inner").evaluate(pa.SCROLL_SCRIPT, {"dx": 0, "dy": 100})
    assert result == {"moved": True, "container": "div"}
    assert fresh.evaluate("box.scrollTop") == 100


def test_insert_text_appends_at_the_caret_and_needs_a_focus(fresh):
    field = fresh.locator("#field")
    field.evaluate("el => { el.focus(); el.setSelectionRange(5, 5); }")
    assert field.evaluate(pa.INSERT_TEXT_SCRIPT, {"text": ","}) == {"ok": True}
    assert fresh.evaluate("field.value") == "hello, world"
    fresh.evaluate("document.activeElement.blur()")
    assert fresh.evaluate(f"(o) => ({pa.INSERT_TEXT_SCRIPT.strip()})(null, o)", {"text": "x"}) == {
        "ok": False, "reason_code": "focus_required"}


def test_paste_inserts_rich_text_or_lets_the_page_handle_it(fresh):
    rich = fresh.locator("#rich")
    rich.evaluate("el => { el.focus(); getSelection().selectAllChildren(el); getSelection().collapseToEnd(); }")
    result = rich.evaluate(pa.PASTE_SCRIPT, pa.paste_payload({"text": "**bold**", "format": "md"}))
    assert result == {"ok": True, "handled_by_page": False, "rich": True}
    assert "<strong>bold</strong>" in fresh.evaluate("rich.innerHTML")
    fresh.evaluate("rich.addEventListener('paste', e => { window.pasted = e.clipboardData.getData('text/plain'); e.preventDefault(); })")
    assert rich.evaluate(pa.PASTE_SCRIPT, {"text": "via page", "html": ""}) == {"ok": True, "handled_by_page": True}
    assert fresh.evaluate("window.pasted") == "via page"


def test_select_text_spans_inline_elements_and_honours_prefix(fresh):
    assert fresh.locator("#para").evaluate(pa.SELECT_TEXT_SCRIPT, {
        "text": "beta gam", "prefix": "", "suffix": "", "kind": "text"}) == {"ok": True}
    assert fresh.evaluate("getSelection().toString()") == "beta gam"
    field = fresh.locator("#field")
    assert field.evaluate(pa.SELECT_TEXT_SCRIPT, {"text": "o", "prefix": "w", "suffix": "", "kind": "cursor_after"}) == {"ok": True}
    assert fresh.evaluate("[field.selectionStart, field.selectionEnd]") == [8, 8]
    assert field.evaluate(pa.SELECT_TEXT_SCRIPT, {"text": "zzz", "prefix": "", "suffix": "", "kind": "text"}) == {
        "ok": False, "reason_code": "text_not_found"}


# ----------------------------------------------------------------- evaluate

@pytest.mark.parametrize("script, source", [
    ("document.title", "() => (document.title)"),
    ("({a: 1})", "() => (({a: 1}))"),
    ("() => location.href", "() => location.href"),
    ("async () => 2", "async () => 2"),
    ("function () { return 3 }", "function () { return 3 }"),
])
def test_evaluate_takes_an_expression_or_a_function(script, source):
    assert pa.evaluate_source({"script": script}) == source


def test_evaluate_needs_a_bounded_script_and_bounds_its_result():
    for script, code in (("", "script_required"), ("x" * (pa.MAX_SCRIPT_CHARS + 1), "script_too_long")):
        with pytest.raises(pa.ActionError) as error:
            pa.evaluate_source({"script": script})
        assert error.value.reason_code == code
    assert pa.evaluation_text({"k": "值"}) == '{"k": "值"}' and pa.evaluation_text(None) == "undefined"
    assert pa.evaluation_text("x" * (pa.MAX_RESULT_CHARS + 5)).endswith("[truncated, 5 more characters]")


def test_evaluate_is_in_the_schema_and_its_script_is_lifted():
    act = web_use_parameters()["allOf"][0]["then"]["properties"]["arguments"]["properties"]
    assert "evaluate" in act["action"]["enum"] and act["script"]["maxLength"] == pa.MAX_SCRIPT_CHARS
    lifted = normalize_web_use_arguments({"command": "act", "action": "evaluate", "script": "1 + 1"})
    assert lifted["arguments"] == {"action": "evaluate", "script": "1 + 1"}


def test_mcp_backends_evaluate_through_the_controller_so_the_result_is_redacted():
    adapter, session = _adapter("playwright_mcp")
    calls = []

    class Controller:
        def execute(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "result": "2"}

    adapter._controller = lambda _session: Controller()
    assert adapter.act(session, {"action": "evaluate", "script": "1 + 1", "expected_frame_id": "f1"}) == {
        "ok": True, "result": "2"}
    assert calls == [{"action": "evaluate", "expected_frame_id": "f1", "script": "1 + 1"}]


@pytest.fixture
def decide(monkeypatch):
    """permission_decision for web_use with authority and recovery stubbed out."""
    from openprogram.runtime.permissions import tool_authority
    from openprogram.runtime.permissions import policy, recovery
    from openprogram.programs._host.runtime import get

    monkeypatch.setattr(policy, "_hard_constraint_violation", lambda *a, **k: None)
    monkeypatch.setattr(tool_authority, "decide_tool_authority",
                        lambda *a, **k: SimpleNamespace(allowed=True, reason_code="", capability=""))
    monkeypatch.setattr(recovery, "approval_context", lambda *a, **k: None)
    agent_tool = get("web_use")

    def run(args, *, mode="bypass", allow=(), source="web"):
        rules = SimpleNamespace(allow=list(allow), ask=[], deny=[])
        req = SimpleNamespace(permission_mode=mode, permission_rules=rules, session_id="s-test",
                              source=source, surface_context=None)
        return policy.permission_decision(agent_tool, req, args)[:2]
    return run


@pytest.mark.parametrize("args", [
    {"command": "act", "arguments": {"action": "evaluate", "script": "document.cookie"}},
    {"command": "act", "action": "Evaluate", "script": "document.cookie"},
])
def test_evaluate_runs_in_bypass_and_asks_elsewhere_unless_allowed(decide, args):
    assert decide(args) == ("allow", "BYPASS")
    assert decide(args, mode="default") == ("ask", "PAGE_SCRIPT_APPROVAL")
    assert decide(args, mode="default", allow=["web_use"]) == ("allow", "PERMISSION_RULE_ALLOW")
    assert decide(args, source="cron")[0] == "deny"
    assert decide({"command": "act", "arguments": {"action": "click", "ref": "e1"}}, allow=["web_use"])[0] == "allow"


def test_an_evaluate_approval_is_never_one_shot_but_never_project_wide():
    from openprogram.runtime.permissions.policy import one_shot_approval, page_script
    assert page_script("web_use", {"command": "act", "arguments": {"action": "evaluate"}})
    assert not page_script("web_use", {"command": "act", "arguments": {"action": "click"}})
    assert not one_shot_approval("web_use", {"command": "act", "arguments": {"action": "evaluate"}})
    assert one_shot_approval("self_update", {"action": "prepare"})
    assert not one_shot_approval("self_update", {})


# ----------------------------------------------------------------- console and network

from openprogram.programs.applications.browser.web_use import page_logs as logs


def test_request_urls_lose_their_query_fragment_and_data():
    assert logs.short_url("https://api.example.com/v1/me?token=abc#x") == "https://api.example.com/v1/me?…"
    assert logs.short_url("https://example.com/a") == "https://example.com/a"
    assert logs.short_url("data:image/png;base64,AAAA") == "data:image/png;base64,…"


def test_log_options_are_checked():
    assert logs.options({}) == ("", False, logs.DEFAULT_LIMIT)
    assert logs.options({"pattern": " API ", "only_errors": True, "limit": "5"}) == ("api", True, 5)
    for bad in (0, 201, "many"):
        with pytest.raises(logs.LogError):
            logs.options({"limit": bad})


def test_console_and_requests_render_newest_last_with_filters():
    rows = [{"type": "log", "text": "boot", "where": ""}, {"type": "error", "text": "API failed", "where": "a.js:3"},
            {"type": "pageerror", "text": "boom", "where": ""}]
    assert logs.render_console(rows, "", True, 50).splitlines()[1:] == ["[error] API failed  (a.js:3)", "[pageerror] boom"]
    assert logs.render_console(rows, "", False, 1).startswith("1 of 3 console message(s)")
    assert logs.render_console([], "", False, 50) == "No console messages yet."
    requests = [{"method": "GET", "url": "https://x/a", "type": "fetch", "status": 200, "failure": ""},
                {"method": "POST", "url": "https://x/b", "type": "xhr", "status": 500, "failure": ""},
                {"method": "GET", "url": "https://x/c", "type": "image", "status": None, "failure": "net::ERR_FAILED"}]
    assert logs.render_requests(requests, "", True, 50).splitlines()[1:] == [
        "POST https://x/b → 500 [xhr]", "GET https://x/c → failed: net::ERR_FAILED [image]"]
    assert logs.render_requests(requests, "zzz", False, 50) == "No requests match."


def test_log_actions_are_in_the_schema_and_go_through_the_controller():
    act = web_use_parameters()["allOf"][0]["then"]["properties"]["arguments"]["properties"]
    assert {"console_messages", "network_requests"} <= set(act["action"]["enum"])
    assert {"pattern", "only_errors", "limit"} <= set(act)
    adapter, session = _adapter("chrome_devtools_mcp")
    calls = []
    adapter._controller = lambda _session: type("C", (), {"execute": lambda self, **kw: calls.append(kw) or {"ok": True}})()
    adapter.act(session, {"action": "network_requests", "only_errors": True, "expected_frame_id": "f2"})
    assert calls == [{"action": "network_requests", "expected_frame_id": "f2", "only_errors": True}]


def test_controller_reads_console_and_requests_without_invalidating_the_frame(page):
    from openprogram.programs.applications.browser.web_use.controller import BrowserPageController

    class Api:
        _sessions = {"br_x": {"page": page}}
    page.set_content("<input type=password value='pw-123'><script>console.error('leak pw-123')</script>")
    controller = BrowserPageController(Api(), url="http://localhost/")
    controller.session_id = "br_x"
    controller._owner.shutdown(wait=True)  # run on the test's own thread, which owns the page
    controller._submit = lambda fn, *a, **k: fn(*a, **k)
    frame = controller.execute(action="observe")["frame_id"]
    result = controller.execute(action="console_messages", expected_frame_id=frame, only_errors=True)
    assert result["ok"] and "[error] leak [redacted]" in result["result"] and "pw-123" not in result["result"]
    assert controller._frame and controller._frame["frame_id"] == frame


@pytest.mark.parametrize("visible, background", [(None, True), (False, True), (True, False)])
def test_observe_opens_a_url_in_the_background_unless_the_user_asked_to_watch(monkeypatch, visible, background):
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs.applications.browser.web_use import execute as web_use
    opened = []
    monkeypatch.setattr(surface_context, "current", lambda: None)
    monkeypatch.setattr(surface_context, "open_page",
                        lambda url, **kw: opened.append((url, kw)) or {"ok": False, "reason_code": "desktop_unavailable"})
    args = {"url": "https://example.com/", **({} if visible is None else {"visible": visible})}
    result = web_use._execute_web_use("observe", arguments=args)
    assert opened == [("https://example.com/", {"background": background})] and result["ok"] is False
    lifted = normalize_web_use_arguments({"command": "observe", "url": "https://example.com/", "visible": True})
    assert lifted["arguments"] == {"url": "https://example.com/", "visible": True}


from openprogram.programs.applications.browser.web_use import observe_diff


def _frame(elements, text="body", url="https://example.com/"):
    return {"frame_id": "f", "url": url, "text": text, "aria_snapshot": "- tree", "elements": elements}


def test_changes_only_lists_new_and_changed_elements_and_names_removed_ones():
    before = _frame([{"ref": "e1", "role": "button", "name": "Save"},
                     {"ref": "e2", "role": "textbox", "name": "Title", "value": "a"},
                     {"ref": "e3", "role": "link", "name": "Help"}])
    after = _frame([{"ref": "e1", "role": "button", "name": "Save"},
                    {"ref": "e2", "role": "textbox", "name": "Title", "value": "ab"},
                    {"ref": "e3", "role": "dialog", "name": "Saved"}])
    out = observe_diff.changes(before, after)
    assert out["changes_only"] is True
    assert [e["ref"] for e in out["elements"]] == ["e2", "e3"]
    assert out["unchanged_elements"] == ["e1 button 'Save'"]
    assert out["removed_elements"] == ["link 'Help'"]
    assert "text" not in out and out["text_unchanged"] and out["aria_snapshot_unchanged"]


def test_changes_only_shows_the_whole_frame_without_an_earlier_one_of_the_page():
    frame = _frame([{"ref": "e1", "role": "button", "name": "Go"}])
    for previous in (None, _frame([], url="https://other.example/")):
        out = observe_diff.changes(previous, frame)
        assert out["changes_only"] is False and out["elements"] == frame["elements"] and out["text"] == "body"


def test_controller_observes_changes_with_refs_of_the_new_frame(page):
    from openprogram.programs.applications.browser.web_use.controller import BrowserPageController

    class Api:
        _sessions = {"br_x": {"page": page}}
    page.set_content("<button>Save</button><input aria-label=Title value=a>")
    controller = BrowserPageController(Api(), url="http://localhost/")
    controller.session_id = "br_x"
    controller._owner.shutdown(wait=True)
    controller._submit = lambda fn, *a, **k: fn(*a, **k)
    controller.execute(action="observe")
    page.fill("input", "ab")
    out = controller.execute(action="observe", changes_only=True)
    assert out["changes_only"] and [e.get("value") for e in out["elements"]] == ["ab"]
    assert len(out["unchanged_elements"]) == 1 and "Save" in out["unchanged_elements"][0]
    assert controller._frame["frame_id"] == out["frame_id"] and len(controller._frame["elements"]) == 2
    assert set(controller._refs) == {e["ref"] for e in controller._frame["elements"]}
    lifted = normalize_web_use_arguments({"command": "observe", "changes_only": True})
    assert lifted["arguments"] == {"changes_only": True}
