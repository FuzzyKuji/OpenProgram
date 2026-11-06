"""Real DOM observation privacy, using an owned headless Chromium instance."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from openprogram.programs.applications.browser.web_use import BrowserPageController

pytestmark = pytest.mark.browser

_SECRET = "fixture-password-7359"


class _OwnedBrowserAPI:
    def __init__(self, attributes, *, secret=_SECRET, iframe=False):
        self.attributes, self.secret, self.iframe = attributes, secret, iframe
        self._sessions = {}
        self.playwright = self.browser = None

    def execute(self, *, action, **kwargs):
        if action == "open":
            from playwright.sync_api import sync_playwright
            self.playwright = sync_playwright().start()
            try:
                self.browser = self.playwright.chromium.launch(headless=True)
            except BaseException:
                self.playwright.stop()
                raise
            page = self.browser.new_page()
            page.set_content(f'<input type="password" {self.attributes}>'
                             '<input type="text" value="ordinary-input">')
            page.locator('input[type=password]').fill(self.secret)
            if self.iframe:
                page.evaluate("""() => { const frame = document.createElement('iframe');
                    frame.srcdoc = '<input type="password" value="frame-secret">';
                    document.body.append(frame); }""")
                page.frame_locator("iframe").locator("input").wait_for()
            self._sessions["br_private"] = {"page": page}
            return "Opened `br_private`"
        if action == "close":
            self._sessions.clear()
            self.browser.close()
            self.playwright.stop()
            return "Closed br_private"
        raise AssertionError(action)


@pytest.mark.parametrize("attributes", ["", 'aria-label="Password"', 'placeholder="Password"'])
@pytest.mark.parametrize("secret", [_SECRET, 'pāss"word\\line'])
def test_public_observation_and_accessibility_hide_passwords(monkeypatch, attributes, secret):
    from openprogram.programs.applications.browser.engine import browser as browser_tool
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(attributes, secret=secret))
    try:
        observation = controller.execute(action="observe")
        visible_strings = [observation["text"], observation["title"], observation["aria_snapshot"],
                           *(element["name"] for element in observation["elements"])]
        assert all(secret not in text for text in visible_strings)
        assert "ordinary-input" in json.dumps(observation)
        if attributes:
            assert "Password" in json.dumps(observation)
        rejected = controller.execute(action="verify", expected_frame_id=observation["frame_id"],
                                      assertion="element_present", value=secret)
        assert rejected["passed"] is False

        def accessibility():
            monkeypatch.setitem(browser_tool._sessions, "br_private", {"page": controller._page()})
            return browser_tool.execute(action="accessibility", session_id="br_private")
        tree = controller._owner.submit(accessibility).result()
        assert secret not in tree
        assert "ordinary-input" in tree
    finally:
        controller.close()


@pytest.mark.parametrize("backend", ["playwright_mcp", "chrome_devtools_mcp"])
def test_official_upstream_snapshot_hides_passwords(monkeypatch, backend):
    from openprogram.programs.applications.browser.web_use.mcp_backends import OfficialMCPPageBackend
    from openprogram.programs.applications.browser.web_use.runtime import WebUseSession
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI("", iframe=True))
    client = SimpleNamespace(call=lambda *args: SimpleNamespace(
        content=[SimpleNamespace(text=f'- textbox: {_SECRET}\n- textbox: frame-secret\n- textbox: ordinary-input')]))
    adapter = OfficialMCPPageBackend(backend, lambda: controller)
    monkeypatch.setattr(adapter, "_ensure_bound", lambda session: client)
    session = WebUseSession("private", backend, "binding")
    session.controller = controller
    session.state["upstream_page"] = 0
    try:
        observation = adapter.observe(session, {})
        assert _SECRET not in json.dumps(observation)
        assert "frame-secret" not in json.dumps(observation)
        assert "ordinary-input" in observation["aria_snapshot"]
    finally:
        controller.close()


def test_public_controller_browser_primitives_against_real_dom():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    html = b"""<body style="height:2200px">
      <textarea aria-label="Report"></textarea>
      <div contenteditable="true" aria-label="Summary">old</div>
      <select aria-label="Week"><option value="1">One</option><option value="2">Two</option></select>
      <button aria-label="Save" onmouseenter="document.body.dataset.hover='yes'"
        onclick="document.querySelector('#status').innerText='Saved'">Save</button>
      <p id="status">Draft</p></body>"""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))

    def act(action, label=None, **arguments):
        observed = controller.execute(action="observe")
        if label:
            arguments["ref"] = next(element["ref"] for element in observed["elements"]
                                    if element["name"] == label)
        result = controller.execute(action=action, expected_frame_id=observed["frame_id"], **arguments)
        assert result["ok"] is True, result
        return result

    try:
        act("navigate", url=f"http://127.0.0.1:{server.server_port}/form")
        assert "/form" in requests
        act("type", "Report", text="weekly progress")
        act("press", "Report", key="End")
        act("press", "Report", key="Enter")
        assert controller.evaluate_bound_page("() => document.querySelector('textarea').value") == "weekly progress\n"
        act("type", "Summary", text="completed work")
        assert controller.evaluate_bound_page("() => document.querySelector('[contenteditable]').innerText") == "completed work"
        act("select", "Week", value="2")
        assert controller.evaluate_bound_page("() => document.querySelector('select').value") == "2"
        act("hover", "Save")
        assert controller.evaluate_bound_page("() => document.body.dataset.hover") == "yes"
        act("click", "Save")
        verified = act("verify", assertion="text_contains", value="Saved")
        assert verified["passed"] is True
        assert controller.final_result(summary="Saved fixture")["status"] == "succeeded"
        act("scroll", amount=350)
        controller._owner.submit(lambda: controller._page().wait_for_function("scrollY > 0")).result()
        act("navigate", url=f"http://127.0.0.1:{server.server_port}/reset")
        observed = controller.execute(action="observe")
        screenshot = controller.execute(action="screenshot", expected_frame_id=observed["frame_id"])
        assert screenshot.images[0].startswith(b"\x89PNG\r\n\x1a\n")
        point = controller.evaluate_bound_page("""() => { const rect = document.querySelector('button').getBoundingClientRect();
            return {x: rect.x+rect.width/2, y: rect.y+rect.height/2}; }""")
        result = controller.execute(action="click", expected_frame_id=observed["frame_id"], **point)
        assert result["ok"] is True
        assert act("verify", assertion="text_contains", value="Saved")["passed"] is True
    finally:
        try:
            controller.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


@pytest.mark.parametrize("mode", ["open", "closed"])
def test_shadow_password_is_redacted_from_public_observation_and_accessibility(monkeypatch, mode):
    from openprogram.programs.applications.browser.engine import browser as browser_tool
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    secret = "shadow-secret-9843"
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""mode => { const host=document.createElement('div');
            document.body.append(host); host.attachShadow({mode}).innerHTML =
            '<input type="password" aria-label="Shadow password" value="shadow-secret-9843">'; }""", mode)
        observed = controller.execute(action="observe")
        assert secret not in json.dumps(observed)
        assert "ordinary-input" in observed["aria_snapshot"]

        def accessibility():
            monkeypatch.setitem(browser_tool._sessions, "br_private", {"page": controller._page()})
            return browser_tool.execute(action="accessibility", session_id="br_private")
        assert secret not in controller._owner.submit(accessibility).result()
    finally:
        controller.close()


def test_secret_absence_assertion_cannot_succeed_after_observation_redaction():
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""secret => { const p=document.createElement('p');
            p.innerText=secret; document.body.append(p); }""", _SECRET)
        observed = controller.execute(action="observe")
        result = controller.execute(action="verify", expected_frame_id=observed["frame_id"],
                                    assertion="text_not_contains", value=_SECRET)
        assert result["passed"] is False
        assert _SECRET not in json.dumps(result)
        assert controller.final_result(summary="Password absent")["status"] == "failed"
        ordinary = controller.execute(action="verify", expected_frame_id=observed["frame_id"],
                                      assertion="text_not_contains", value="never-seen-text")
        assert ordinary["passed"] is True
    finally:
        controller.close()


@pytest.mark.parametrize("ensure_ascii", [False, True])
def test_encoded_secret_assertion_and_final_evidence_never_leak(ensure_ascii):
    secret = 'pāss"word\\line'
    escaped = json.dumps(secret, ensure_ascii=ensure_ascii)[1:-1]
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI("", secret=secret))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""value => { const p=document.createElement('p');
            p.innerText=value; document.body.append(p); }""", escaped)
        observed = controller.execute(action="observe")
        result = controller.execute(action="verify", expected_frame_id=observed["frame_id"],
                                    assertion="text_contains", value=escaped)
        final = controller.final_result(summary=escaped)
        assert escaped not in [item.get("value") for item in final["completion_evidence"]]
        assert result.get("passed") is False
        assert result.get("reason_code") == "sensitive_assertion"
        assert final["status"] == "failed"
        assert final["summary"] == "[redacted]"
    finally:
        controller.close()


def test_final_result_fails_closed_if_password_capture_is_unavailable():
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        observed = controller.execute(action="observe")
        assert controller.execute(action="verify", expected_frame_id=observed["frame_id"],
                                  assertion="text_not_contains", value="unseen-text")["passed"]
        def block_capture():
            frame = controller._page().main_frame
            evaluate = frame.evaluate
            def blocked(expression, *args, **kwargs):
                if "input[type=password]" in expression:
                    raise RuntimeError("capture unavailable")
                return evaluate(expression, *args, **kwargs)
            frame.evaluate = blocked
        controller._owner.submit(block_capture).result()
        final = controller.final_result(summary=_SECRET)
        assert final["status"] == "failed"
        assert final["reason_code"] == "observation_privacy_unavailable"
        assert final["completion_evidence"] == []
        assert _SECRET not in json.dumps(final)
        assert final["target"]["url"] == ""
    finally:
        controller.close()


def test_public_mutation_metadata_hides_known_passwords():
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("value => document.title=value", _SECRET)
        observed = controller.execute(action="observe")
        assert observed["title"] == "[redacted]"
        result = controller.execute(action="scroll", expected_frame_id=observed["frame_id"], amount=1)
        assert result["ok"] is True
        assert _SECRET not in json.dumps(result)
        assert result["title"] == "[redacted]"
    finally:
        controller.close()


def test_stable_secret_url_uses_raw_identity_for_freshness():
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("value => location.hash=value", _SECRET)
        observed = controller.execute(action="observe")
        assert _SECRET not in observed["url"]
        result = controller.execute(action="verify", expected_frame_id=observed["frame_id"],
                                    assertion="text_not_contains", value="unseen-marker")
        assert result.get("passed") is True
        assert controller.final_result(summary="Stable page verified")["status"] == "succeeded"
        controller.evaluate_bound_page("() => location.hash='a different page state'")
        assert controller.execute(action="verify", expected_frame_id=observed["frame_id"],
                                  assertion="text_not_contains", value="unseen-marker")["reason_code"] == "stale_observation"
    finally:
        controller.close()


@pytest.mark.parametrize("selector", ['[', '[data-token="%s"]'])
def test_public_accessibility_errors_hide_known_passwords(monkeypatch, selector):
    from openprogram.programs.applications.browser.engine import browser as browser_tool
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        controller.execute(action="observe")
        selector = selector % _SECRET if "%s" in selector else selector + _SECRET
        def accessibility():
            monkeypatch.setitem(browser_tool._sessions, "br_private", {"page": controller._page()})
            return browser_tool.execute(action="accessibility", session_id="br_private", selector=selector)
        result = controller._owner.submit(accessibility).result()
        assert _SECRET not in result
        assert "[redacted]" in result
    finally:
        controller.close()


@pytest.mark.parametrize("secret", ["e1", "frame", "a"])
def test_password_collision_does_not_corrupt_public_control_identifiers(secret):
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI("", secret=secret))
    try:
        observed = controller.execute(action="observe")
        ref = observed["elements"][0]["ref"]
        assert ref != "[redacted]"
        assert secret not in ref
        assert secret not in observed["frame_id"]
        result = controller.execute(action="type", expected_frame_id=observed["frame_id"],
                                    ref=ref, text="updated-password")
        assert result["ok"] is True
    finally:
        controller.close()


def test_public_observation_reads_exact_editable_values_and_labels():
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    textarea_value = "  first line\n\nsecond\tline  \n"
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""value => {
            document.body.innerHTML = '<label for="report">Weekly report</label><textarea id="report"></textarea>' +
                '<span id="identity">Research summary</span><input aria-labelledby="identity" value="text value">' +
                '<div contenteditable="true" aria-label="Details"><div> first </div><div> second </div></div>';
            document.querySelector('textarea').value = value;
        }""", textarea_value)
        observed = controller.execute(action="observe")
        report, text_input, editable = observed["elements"]
        assert report["label"] == "Weekly report"
        assert report["value"] == textarea_value
        assert report["value_truncated"] is False
        assert report["value_redacted"] is False
        assert text_input["label"] == "Research summary"
        assert text_input["value"] == "text value"
        assert editable["name"] == "Details"
        expected = controller.evaluate_bound_page("() => document.querySelector('[contenteditable]').innerText")
        assert editable["value"] == expected
        changed = controller.execute(action="type", expected_frame_id=observed["frame_id"],
                                     ref=report["ref"], text="  updated\nreport  ")
        assert changed["ok"] is True
        fresh = controller.execute(action="observe")
        assert fresh["frame_id"] != observed["frame_id"]
        assert fresh["elements"][0]["value"] == "  updated\nreport  "
    finally:
        controller.close()


def test_public_observation_marks_field_and_frame_value_truncation():
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""() => {
            document.body.innerHTML = '<textarea aria-label="Unicode"></textarea>' +
                Array.from({length:5}, (_,i) => `<textarea aria-label="Report ${i}"></textarea>`).join('');
            document.querySelector('textarea').value = '😀'.repeat(9000);
            document.querySelectorAll('textarea').forEach((el,i) => {if(i) el.value = 'x'.repeat(9000);});
        }""")
        observed = controller.execute(action="observe")
        fields = observed["elements"]
        assert fields[0]["value"] == "😀" * 8192
        assert all(field["value_truncated"] is True for field in fields)
        assert sum(len(field["value"].encode("utf-8")) for field in fields) <= 32768
        assert fields[-1]["value"] == ""
    finally:
        controller.close()


@pytest.mark.parametrize("secret", [_SECRET, "known-secret-" * 750])
def test_public_observation_omits_password_and_matching_field_values(secret):
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI("", secret=secret))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""secret => {
            document.querySelector('input[type=text]').value = secret;
        }""", secret)
        observed = controller.execute(action="observe")
        assert secret not in json.dumps(observed)
        for field in observed["elements"]:
            assert "value" not in field
            assert field["value_redacted"] is True
            assert field["name"] in {"", "[redacted]"}
    finally:
        controller.close()


def test_readonly_field_context_reports_dom_relationships_without_guessing_labels():
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""() => {document.body.innerHTML = '<h1>Form</h1>' +
            '<section id="work" class="form-row"><span class="title">本周工作</span>' +
            '<div contenteditable="true"><p>Existing field value</p></div></section>' +
            '<section id="plans"><span>下周计划</span><div contenteditable="true"></div></section>'; }""")
        observed = controller.execute(action="observe")
        first = observed["elements"][0]
        assert first["label"] == ""
        context = first["field_context"]
        assert context["diagnostic_only"] is True
        assert context["source"] == "dom_structure"
        assert context["element"]["tag"] == "div"
        parent = context["ancestors"][0]
        assert parent["id"] == "work"
        assert parent["editable_count"] == 1
        assert any(node["text"] == "本周工作" for node in parent["text_nodes"])
        assert all("Existing field value" not in node["text"] for node in parent["text_nodes"])
        assert context["ancestors"][1]["editable_count"] == 2
    finally:
        controller.close()


def test_field_context_is_bounded_and_redacted_before_truncation():
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""secret => {
            const password = document.querySelector('input[type=password]');
            const sections = Array.from({length:15}, (_,i) => {
                const section=document.createElement('section');section.id=secret;section.className=secret;
                const title=document.createElement('span');title.innerText=secret + '界'.repeat(1000);
                section.append(title);section.append(document.createElement('div'));
                section.lastChild.contentEditable='true';return section;
            }); document.body.replaceChildren(password,...sections);
        }""", _SECRET)
        observed = controller.execute(action="observe")
        assert _SECRET not in json.dumps(observed)
        contexts = [field["field_context"] for field in observed["elements"] if "field_context" in field]
        assert sum(len(json.dumps(context, ensure_ascii=False).encode("utf-8")) for context in contexts) <= 32768
        assert any(field.get("field_context_truncated") for field in observed["elements"])
        assert all(len(context["ancestors"]) <= 4 for context in contexts)
        assert all(len(ancestor["text_nodes"]) <= 6 for context in contexts for ancestor in context["ancestors"])
    finally:
        controller.close()


def test_long_secret_value_name_is_hidden_even_with_associated_label():
    secret = "known-secret-" * 750
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI("", secret=secret))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""secret => {
            const input=document.querySelector('input[type=text]');input.id='copied';input.value=secret;
            const label=document.createElement('label');label.htmlFor='copied';label.innerText='Copied password';
            document.body.append(label);
            const copy=document.createElement('p');copy.innerText=secret + '\\n' + secret;
            document.body.append(copy);
        }""", secret)
        observed = controller.execute(action="observe")
        field = observed["elements"][1]
        assert field["label"] == "Copied password"
        assert field["value_redacted"] is True
        assert "value" not in field
        assert secret[:240] not in field["name"]
        assert secret[:240] not in json.dumps(observed, ensure_ascii=False)
        assert len(observed["text"]) <= 12000
    finally:
        controller.close()


@pytest.mark.parametrize("backend", ["playwright_mcp", "chrome_devtools_mcp"])
def test_upstream_truncated_long_password_is_hidden(backend, monkeypatch):
    from openprogram.programs.applications.browser.web_use.mcp_backends import OfficialMCPPageBackend
    from openprogram.programs.applications.browser.web_use.runtime import WebUseSession
    secret = "known-secret-" * 750
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI("", secret=secret))
    client = SimpleNamespace(call=lambda *args: SimpleNamespace(
        content=[SimpleNamespace(text=f'- textbox: {secret[:240]}...\n- textbox: ordinary-input')]))
    adapter = OfficialMCPPageBackend(backend, lambda: controller)
    monkeypatch.setattr(adapter, "_ensure_bound", lambda session: client)
    session = WebUseSession("private", backend, "binding")
    session.controller = controller
    session.state["upstream_page"] = 0
    try:
        observed = adapter.observe(session, {})
        assert secret[:240] not in json.dumps(observed, ensure_ascii=False)
        assert "ordinary-input" in observed["aria_snapshot"]
        rejected = controller.execute(action="verify", expected_frame_id=observed["frame_id"],
                                      assertion="text_not_contains", value=secret[:240])
        assert rejected["passed"] is False
        assert secret[:240] not in json.dumps(rejected, ensure_ascii=False)
    finally:
        controller.close()


def test_shared_password_prefix_does_not_hide_longer_matches_from_redactor(monkeypatch):
    from openprogram.programs.applications.browser.web_use.mcp_backends import OfficialMCPPageBackend
    from openprogram.programs.applications.browser.web_use.runtime import WebUseSession
    header = "shared-password-header-0123456789"
    first, second = header + "A" * 10000, header + "B" * 9000
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI("", secret=first))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""secret => {
            const password=document.createElement('input');password.type='password';password.value=secret;
            document.body.append(password);
            const input=document.querySelector('input[type=text]');input.id='copy';input.value=secret;
            const label=document.createElement('label');label.htmlFor='copy';label.innerText='Copied password';
            const text=document.createElement('p');text.innerText=secret;
            document.body.append(label,text);
        }""", second)
        observed = controller.execute(action="observe")
        assert "B" * 64 not in json.dumps(observed, ensure_ascii=False)
        assert observed["elements"][1]["label"] == "Copied password"
        assert "value" not in observed["elements"][1]
        client = SimpleNamespace(call=lambda *args: SimpleNamespace(
            content=[SimpleNamespace(text=f'- textbox: {second[:240]}...')]))
        adapter = OfficialMCPPageBackend("playwright_mcp", lambda: controller)
        monkeypatch.setattr(adapter, "_ensure_bound", lambda session: client)
        session = WebUseSession("private", "playwright_mcp", "binding")
        session.controller = controller
        session.state["upstream_page"] = 0
        assert "B" * 64 not in json.dumps(adapter.observe(session, {}), ensure_ascii=False)
    finally:
        controller.close()


def test_overlapping_password_occurrences_are_redacted_in_public_observation():
    header = "a" * 32
    secret = header + "B" * 100 + header
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI("", secret=secret))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""text => {
            const paragraph=document.createElement('p');paragraph.innerText=text;
            document.body.append(paragraph);
        }""", secret + secret[32:])
        observed = controller.execute(action="observe")
        assert "B" * 64 not in json.dumps(observed, ensure_ascii=False)
        assert observed["text"] == "[redacted]"
    finally:
        controller.close()


def test_editable_ancestor_contents_are_excluded_from_context_direct_text():
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""() => {document.body.innerHTML =
            '<div id="outer" contenteditable="true">OUTER-FIELD-VALUE' +
            '<div id="inner" contenteditable="true">INNER-FIELD-VALUE</div></div>'; }""")
        observed = controller.execute(action="observe")
        inner = next(field for field in observed["elements"]
                     if field["field_context"]["element"]["id"] == "inner")
        ancestor = inner["field_context"]["ancestors"][0]
        assert ancestor["id"] == "outer"
        assert ancestor["direct_text"] == ""
        assert ancestor["text_nodes"] == []
        assert inner["value"] == "INNER-FIELD-VALUE"
    finally:
        controller.close()


@pytest.mark.parametrize("nested", [False, True])
def test_readonly_islands_inside_editable_values_are_excluded_from_field_context(nested):
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""nested => {document.body.innerHTML =
            '<section id="field"><span>Weekly report</span><div id="outer" contenteditable="true">' +
            '<div contenteditable="false">EDITABLE-VALUE-ISLAND' +
            (nested ? '<div id="inner" contenteditable="true">Inner value</div>' : '') +
            '</div></div></section>'; }""", nested)
        observed = controller.execute(action="observe")
        field = next(field for field in observed["elements"]
                     if field["field_context"]["element"]["id"] == ("inner" if nested else "outer"))
        assert "EDITABLE-VALUE-ISLAND" not in json.dumps(field["field_context"])
        assert "Weekly report" in json.dumps(field["field_context"])
        if not nested:
            assert field["value"] == "EDITABLE-VALUE-ISLAND"
    finally:
        controller.close()


def _field_binding_observe(html):
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""html => {
            document.body.innerHTML = '<style>[contenteditable]{min-height:20px}</style>' + html;
        }""", html)
        before = controller.evaluate_bound_page("() => document.body.innerHTML")
        observed = controller.execute(action="observe")
        assert controller.evaluate_bound_page("() => document.body.innerHTML") == before
        return observed
    finally:
        controller.close()


def test_deep_container_labels_bind_all_six_fields_without_changing_native_labels():
    labels = ["姓名", "本周工作", "阅读的论文", "下周计划", "遇到的问题", "需要的支持"]
    rows = [f'<section><label>{label}</label>' + '<div>' * 10
            + f'<div contenteditable="true" id="field-{index}">value-{index}</div>'
            + '</div>' * 10 + '</section>' for index, label in enumerate(labels)]
    observed = _field_binding_observe('<form>' + ''.join(rows) + '</form>')
    fields = observed["elements"]
    assert len(fields) == 6
    for index, (field, label) in enumerate(zip(fields, labels)):
        assert field["label"] == ""
        assert field["value"] == f"value-{index}"
        assert len(field["field_context"]["ancestors"]) == 4
        assert field["field_context"]["label_binding"] == {
            "source": "visible_container_label", "label": label, "ancestor_depth": 11,
            "editable_count": 1, "label_count": 1, "truncated": False, "redacted": False,
        }


@pytest.mark.parametrize("html", [
    '<section><label>Work</label><div contenteditable="true">a</div><textarea>b</textarea></section>',
    '<section><label>Work</label><label>Plan</label><div contenteditable="true">a</div></section>',
    '<section><label><span>Work</span></label><div contenteditable="true">a</div></section>',
    '<section><label>Outer</label><div><label>One</label><label>Two</label><div contenteditable="true">a</div></div></section>',
    '<section>' + '<i></i>' * 121 + '<label>Work</label><div contenteditable="true">a</div></section>',
    '<section><label>Work</label>' + '<div>' * 12 + '<div contenteditable="true">a</div>' + '</div>' * 12 + '</section>',
    '<div contenteditable="true"><div contenteditable="false"><label>Value island</label></div>'
    '<div contenteditable="true">a</div></div>',
])
def test_container_labels_fail_closed_for_ambiguous_incomplete_or_editable_scopes(html):
    observed = _field_binding_observe(html)
    assert observed["elements"]
    assert all("label_binding" not in field.get("field_context", {}) for field in observed["elements"])


def test_hidden_labels_do_not_conflict_with_visible_native_label():
    observed = _field_binding_observe('<section><label style="display:none">Hidden</label>'
                                     '<label for="native">Visible</label><input id="native" value="original"></section>')
    field = observed["elements"][0]
    assert field["label"] == "Visible"
    assert field["value"] == "original"
    assert field["field_context"]["label_binding"]["label"] == "Visible"
    assert field["field_context"]["label_binding"]["label_count"] == 1


def test_container_label_binding_marks_full_secret_mask_and_label_truncation():
    observed = _field_binding_observe(f'<section><label>Password</label><input type="password" value="{_SECRET}"></section>'
                                     f'<section><label>{_SECRET}</label><div contenteditable="true">ordinary</div></section>'
                                     '<section><label>' + '界' * 401 + '</label><div contenteditable="true">ordinary</div></section>')
    password, copied, long_label = observed["elements"]
    assert "label_binding" not in password["field_context"]
    assert _SECRET not in json.dumps(observed)
    assert copied["field_context"]["label_binding"]["redacted"] is True
    assert long_label["field_context"]["label_binding"]["truncated"] is True
    assert len(long_label["field_context"]["label_binding"]["label"]) == 400


def test_compact_label_binding_survives_unrelated_diagnostic_budget_clipping():
    rows = [f'<section><label>Work-{index}</label>' + ('<div class="' + ' '.join(chr(97+n) * 400 for n in range(6)) + '">') * 10
            + '<div contenteditable="true">ordinary</div>' + '</div>' * 10 + '</section>' for index in range(12)]
    observed = _field_binding_observe(''.join(rows))
    contexts = [field["field_context"] for field in observed["elements"] if "field_context" in field]
    assert sum(len(json.dumps(context, ensure_ascii=False).encode("utf-8")) for context in contexts) <= 32768
    assert any(context["truncated"] for context in contexts)
    assert len(contexts) < 12
    assert all(context["label_binding"]["truncated"] is False for context in contexts)
    assert all(context["label_binding"]["redacted"] is False for context in contexts)


@pytest.mark.parametrize("html, mutation", [
    ('<section><label>Work</label><div id="target" contenteditable="true">old</div></section>',
     "document.querySelector('label').textContent='Plan'"),
    ('<section><label>Work</label><div id="target" contenteditable="true">old</div></section>',
     "document.querySelector('section').insertAdjacentHTML('beforeend','<label>Plan</label>')"),
    ('<section><label>Work</label><div id="target" contenteditable="true">old</div></section>',
     "document.querySelector('section').insertAdjacentHTML('beforeend','<textarea>second</textarea>')"),
    ('<section><label>Work</label><input id="target" value="old"></section>',
     "document.querySelector('label').textContent='Plan'"),
    ('<section><label for="target">Work</label><input id="target" value="old"></section>',
     "document.querySelector('label').textContent='Plan'"),
    ('<section><div id="target" contenteditable="true">old</div></section>',
     "document.querySelector('section').insertAdjacentHTML('afterbegin','<label>Work</label>')"),
])
def test_public_ref_write_rejects_changed_field_label_semantics_before_any_input(html, mutation):
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""html => {
            document.body.innerHTML = html; window.writeEvents=0;
            document.body.addEventListener('input', () => window.writeEvents++);
        }""", html)
        observed = controller.execute(action="observe")
        target = observed["elements"][0]
        controller.evaluate_bound_page("() => {" + mutation + "}")
        result = controller.execute(action="type", expected_frame_id=observed["frame_id"],
                                    ref=target["ref"], text="must not write")
        assert result["ok"] is False
        assert result["reason_code"] == "stale_observation"
        assert controller.evaluate_bound_page("() => window.writeEvents") == 0
        assert controller.evaluate_bound_page("() => document.getElementById('target').value || document.getElementById('target').innerText") == "old"
    finally:
        controller.close()


@pytest.mark.parametrize("native", [False, True])
def test_public_ref_write_keeps_unchanged_binding_after_unrelated_diagnostic_change(native):
    html = ('<label for="target">Work</label><input id="target" value="old">' if native else
            '<label>Work</label><div id="target" contenteditable="true">old</div>')
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("html => document.body.innerHTML = '<section>' + html + '</section>'", html)
        observed = controller.execute(action="observe")
        target = observed["elements"][0]
        controller.evaluate_bound_page("() => document.querySelector('section').className='unrelated-layout-class'")
        result = controller.execute(action="type", expected_frame_id=observed["frame_id"],
                                    ref=target["ref"], text="new")
        assert result["ok"] is True
        assert controller.evaluate_bound_page("() => document.getElementById('target').value || document.getElementById('target').innerText") == "new"
    finally:
        controller.close()


@pytest.mark.parametrize("source", ["aria-label", "aria-labelledby", "native-label"])
@pytest.mark.parametrize("changed", [True, False])
def test_full_native_label_identity_is_private_and_rejects_suffix_changes(source, changed):
    prefix = "x" * 240
    label = prefix + "old"
    if source == "aria-label":
        html = f'<input id="target" aria-label="{label}" value="old">'
    elif source == "aria-labelledby":
        html = f'<span id="title">{label}</span><input id="target" aria-labelledby="title" value="old">'
    else:
        # Two controls prevent a compact container binding, isolating native-label identity.
        html = f'<label for="target">{label}</label><input id="target" value="old"><textarea>other</textarea>'
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(""))
    try:
        controller.execute(action="observe")
        controller.evaluate_bound_page("""html => {
            document.body.innerHTML = html; window.writeEvents=0;
            document.body.addEventListener('input', () => window.writeEvents++);
        }""", html)
        observed = controller.execute(action="observe")
        target = observed["elements"][0]
        assert target["label"] == prefix
        assert "label_binding" not in target["field_context"]
        assert "native_label_identity" not in target
        if changed:
            controller.evaluate_bound_page("""args => {
                if (args.source === 'aria-label') document.getElementById('target').setAttribute('aria-label', args.label);
                else document.querySelector(args.source === 'aria-labelledby' ? '#title' : 'label').textContent=args.label;
            }""", {"source": source, "label": prefix + "new"})
        result = controller.execute(action="type", expected_frame_id=observed["frame_id"],
                                    ref=target["ref"], text="new value")
        assert result["ok"] is (not changed)
        if changed:
            assert result["reason_code"] == "stale_observation"
        assert controller.evaluate_bound_page("() => window.writeEvents") == (0 if changed else 1)
        assert controller.evaluate_bound_page("() => document.getElementById('target').value") == ("old" if changed else "new value")
    finally:
        controller.close()
