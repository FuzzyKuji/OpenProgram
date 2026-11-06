"""The built-in browser's tab driver: which tab an action goes to, and how a ref is found again."""
from __future__ import annotations

import pytest

from openprogram.programs.applications.browser import tabs


def _surface(tab_id, **extra):
    return {"window_id": "main", "tab_id": tab_id, "target_id": f"T{tab_id}", "binding_id": f"b{tab_id}",
            "title": tab_id.upper(), "origin": "https://x.test", **extra}


@pytest.fixture
def driver(monkeypatch):
    from openprogram.runtime.conversation import surface_context

    value = tabs.Driver()
    listed = {"surfaces": [_surface("a"), _surface("b", visible=True, focused=True)]}
    monkeypatch.setattr(surface_context, "current", lambda: None)
    monkeypatch.setattr(surface_context, "capture_pages_for_listing", lambda _context=None: listed)
    value.listed = listed
    yield value
    value._owner.shutdown()


A = tabs._tab_name("main", "a", set())
B = tabs._tab_name("main", "b", set())


def test_an_action_goes_to_the_named_tab_then_the_last_used_then_the_focused(driver):
    assert driver._tab("", "s1").title == "B"
    first = driver._tab(A, "s1")
    assert first.title == "A" and driver._tab(None, "s1") is first
    # Ids stay with their tabs when the App lists them again, in any order.
    driver.listed["surfaces"].reverse()
    driver._refresh()
    assert driver._tab(A, "s2").title == "A"
    with pytest.raises(tabs.BrowserError) as missing:
        driver._tab("t9", "s1")
    assert missing.value.reason_code == "tab_not_found"
    assert [row["tab"] for row in missing.value.extra["tabs"]] == [B, A]


def test_every_process_names_a_tab_alike_and_a_moved_tab_keeps_its_name(driver):
    assert A == tabs._tab_name("main", "a", set()) != B and A.startswith("t") and len(A) == 5
    # A name another tab already has grows by a letter.
    longer = tabs._tab_name("main", "a", {A})
    assert longer.startswith(A) and len(longer) == 6
    driver._refresh()
    moved = _surface("a", window_id="second", binding_id="b-moved")
    driver.listed["surfaces"] = [moved, _surface("b")]
    driver._refresh()
    assert driver._find(A).window_id == "second"


def test_a_new_listing_releases_the_binding_it_replaces_and_a_new_page_forgets_the_old(driver, monkeypatch):
    from openprogram.interfaces.server.ws_actions import webtab
    released = []
    monkeypatch.setattr(webtab, "release_binding", released.append)
    driver._refresh()
    tab = driver._find(A)
    tab.roles, tab.shots = {"e1": ("button", "Go")}, {"x": (1.0, 0, "", 0, 0)}
    driver.listed["surfaces"][0] = _surface("a", binding_id="b-new", target_id="T-new")
    driver._refresh()
    assert released == ["ba"] and tab.binding_id == "b-new"
    assert tab.roles == {} and tab.shots == {}


def test_snapshot_lines_give_each_ref_its_role_and_name():
    text = '- generic [ref=e1]:\n  - button "Say \\"hi\\"" [ref=e2] [cursor=pointer]\n- <changed> radio "A" [checked] [ref=f1e3]'
    assert tabs._REF_LINE.findall(text) == [("generic", "", "e1"), ("button", 'Say \\"hi\\"', "e2"),
                                            ("radio", "A", "f1e3")]


class _Locator:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count


class _Page:
    url = "https://x.test/form"

    def __init__(self, refs=(), roles=()):
        self.refs, self.roles = set(refs), dict(roles)

    def locator(self, selector):
        return _Locator(1 if selector.removeprefix("aria-ref=") in self.refs else 0)

    def get_by_role(self, role, name=None, exact=False):
        return _Locator(self.roles.get((role, name), 0))

    def title(self):
        return "Form"


def test_a_ref_whose_element_was_rendered_again_is_found_by_role_and_name(driver, monkeypatch):
    tab = tabs.Tab(id="t1", window_id="main", tab_id="a", roles={"e4": ("button", "Next")})
    _, label = driver._locate(_Page(refs={"e4"}), tab, {"ref": "e4"})
    assert label == "e4"
    _, label = driver._locate(_Page(roles={("button", "Next"): 1}), tab, {"ref": "e4"})
    assert label == 'button "Next"'
    monkeypatch.setattr(driver, "_snapshot", lambda page, tab, full: ('- button "Back" [ref=e9]', ""))
    with pytest.raises(tabs.BrowserError) as gone:
        driver._locate(_Page(), tab, {"ref": "e4"})
    assert gone.value.reason_code == "element_gone" and "Back" in gone.value.extra["page"]


def test_a_result_carries_the_changes_or_the_whole_page_after_moving(driver, monkeypatch):
    tab = tabs.Tab(id="t1", window_id="main", tab_id="a")
    monkeypatch.setattr(driver, "_snapshot", lambda page, tab, full: (None, "- <changed> part") if not full
                        else ("- full", ""))
    assert driver._state(_Page(), tab, full=False, before_url="https://x.test/form")["changes"] == "- <changed> part"
    assert driver._state(_Page(), tab, full=False, before_url="https://x.test/start")["page"] == "- full"
    monkeypatch.setattr(driver, "_snapshot", lambda page, tab, full: ("- new document", None))
    assert driver._state(_Page(), tab, full=False, before_url="https://x.test/form")["page"] == "- new document"


class _Impl:
    """Playwright 1.60's page: the AI snapshot is Frame.ariaSnapshot(mode="ai"), incremental with track."""

    def __init__(self):
        self.calls = []
        self._main_frame = self
        self._timeout = None
        self._channel = self

    def aria_snapshot(self, timeout=None, depth=None, mode=None, boxes=None):
        raise AssertionError("the channel is used")

    def send(self, method, timeout, params):
        self.calls.append(params)
        if "track" in params:
            return '- button "Go" [ref=e1]' if len(self.calls) == 1 else '- <changed> button "Gone" [ref=e2]'
        return '- button "Go" [ref=e1]\n- button "Gone" [ref=e2]'


def test_playwright_160_snapshots_track_changes_and_read_the_whole_page_apart(driver, monkeypatch):
    from openprogram.programs.applications.browser import privacy as _privacy

    monkeypatch.setattr(_privacy, "password_values", lambda page: ())
    impl = _Impl()
    page = type("P", (), {"_impl_obj": impl, "_sync": staticmethod(lambda value: value)})()
    tab = tabs.Tab(id="t1", window_id="main", tab_id="a", target_id="T")
    driver._watches["T"] = tabs._Watch()
    # The first snapshot of a document is the whole page.
    assert driver._snapshot(page, tab, full=False) == ('- button "Go" [ref=e1]', None)
    assert driver._snapshot(page, tab, full=False) == (None, '- <changed> button "Gone" [ref=e2]')
    assert tab.roles == {"e1": ("button", "Go"), "e2": ("button", "Gone")}
    whole, _ = driver._snapshot(page, tab, full=True)
    assert "Gone" in whole and impl.calls[-1] == {"mode": "ai"}
    driver._watches["T"].documents += 1
    assert driver._snapshot(page, tab, full=False)[1] is None


def _as(viewer):
    token = tabs._VIEWER.set(viewer)
    return lambda: tabs._VIEWER.reset(token)


def test_two_agents_of_one_conversation_keep_their_own_current_tab(driver):
    reset = _as("s1/exec-a")
    driver._tab(A, "s1")
    reset()
    reset = _as("s1/exec-b")
    driver._tab(B, "s1")
    reset()
    # A new agent of the conversation starts from the tab the conversation used last.
    reset = _as("s1/exec-c")
    assert driver._tab(None, "s1").id == B
    reset()
    reset = _as("s1/exec-a")
    assert driver._tab(None, "s1").id == A
    reset()


def test_a_result_says_when_another_agent_acted_on_the_tab(driver, monkeypatch):
    tab = tabs.Tab(id="t1", window_id="main", tab_id="a")
    monkeypatch.setattr(driver, "_snapshot", lambda page, tab, full: (None, "- <changed> part"))
    for viewer in ("a", "b"):
        reset = _as(viewer)
        driver._state(_Page(), tab, full=False)
        reset()
    tab.writes.append((next(tabs._writes), "b"))
    reset = _as("b")
    assert "note" not in driver._state(_Page(), tab, full=False)
    reset()
    reset = _as("a")
    assert "another agent acted on this tab 1 time(s)" in driver._state(_Page(), tab, full=False)["note"]
    assert "note" not in driver._state(_Page(), tab, full=False)
    reset()


def test_an_action_already_sent_is_never_sent_again_when_the_tab_goes_away(driver, monkeypatch):
    sent = []

    def operate(tab, action, args):
        sent.append(action)
        return tabs._Acted(done="clicked Next", before_url="", documents=0, pending=set(), created=0)

    def settle(tab, acted):
        raise tabs.BrowserError("tab_gone", "the tab is no longer in the App")
    monkeypatch.setattr(driver, "_operate", operate)
    monkeypatch.setattr(driver, "_settle", settle)
    monkeypatch.setattr(driver, "_catch_choosers", lambda tab: {})
    result = driver.run("click", {"tab": A, "ref": "e1"}, "s1")
    assert sent == ["click"] and result["ok"] and "closed or left the App" in result["note"]


class _Scrolled(_Page):
    def __init__(self, scroll):
        super().__init__()
        self.scroll = scroll

    def evaluate(self, script, *args):
        return [800, 0, self.scroll]


def test_coordinates_stop_working_once_the_page_was_acted_on_or_scrolled(driver):
    tab = tabs.Tab(id="t1", window_id="main", tab_id="a")
    with pytest.raises(tabs.BrowserError) as missing:
        driver._click_point(_Scrolled(0), tab, {"x": 1, "y": 1})
    assert missing.value.reason_code == "screenshot_required"
    tab.shots[""] = (1.0, 0, _Page.url, 0, 0)
    with pytest.raises(tabs.BrowserError) as scrolled:
        driver._click_point(_Scrolled(40), tab, {"x": 1, "y": 1})
    assert scrolled.value.reason_code == "screenshot_stale"
    tab.writes.append((next(tabs._writes), "other"))
    with pytest.raises(tabs.BrowserError) as acted:
        driver._click_point(_Scrolled(0), tab, {"x": 1, "y": 1})
    assert acted.value.reason_code == "screenshot_stale"


def test_a_list_of_actions_holds_its_tab_until_it_ends(driver, monkeypatch):
    monkeypatch.setattr(tabs, "TAB_WAIT_SECONDS", 0.0)
    tab = driver._tab(A, "s1")
    with tabs.batch():
        assert driver._hold(tab) is False and tab.lock.locked()
        assert driver._hold(tab) is False
    assert not tab.lock.locked()
    tab.lock.acquire()
    try:
        with pytest.raises(tabs.BrowserError) as busy:
            driver._hold(tab)
        assert busy.value.reason_code == "tab_busy"
    finally:
        tab.lock.release()


def test_the_browser_is_refused_while_the_user_turned_off_agent_access(driver, monkeypatch):
    from openprogram.runtime.conversation import surface_context
    monkeypatch.setattr(surface_context, "current", lambda: {"surfaces": [{"preview_status": "disabled"}]})
    assert driver.run("read", {}, "s1")["reason_code"] == "page_access_disabled"


def test_a_forked_subprocess_starts_its_own_driver(monkeypatch):
    parent = object()
    monkeypatch.setattr(tabs, "_driver", parent)
    tabs._forget_in_child()
    assert tabs._driver is None and not tabs._driver_lock.locked()


def test_a_tab_the_action_opened_is_reported_and_not_switched_to(driver):
    tab = driver._tab(A, "s1")
    driver.listed["surfaces"].append(_surface("c", opener_tab_id="a", title="Popup"))
    opened = driver._opened(tab)
    assert [row["title"] for row in opened] == ["Popup"]
    assert driver._current("s1") == A


class _Chooser:
    def __init__(self):
        self.files = None

    def set_files(self, payload):
        self.files = payload


def test_upload_without_ref_answers_the_file_chooser_the_last_action_opened(driver, tmp_path, monkeypatch):
    from openprogram.host import sandbox
    monkeypatch.setattr(sandbox, "validate_read_path", lambda path: None)
    tab = tabs.Tab(id="t1", window_id="main", tab_id="a")
    with pytest.raises(tabs.BrowserError) as none:
        driver._answer_chooser(tab, {"path": str(tmp_path / "cv.pdf")})
    assert none.value.reason_code == "no_file_chooser"
    (tmp_path / "cv.pdf").write_bytes(b"%PDF")
    tab.chooser = chooser = _Chooser()
    with pytest.raises(tabs.BrowserError):
        driver._answer_chooser(tab, {"path": str(tmp_path / "missing.pdf")})
    # A bad path leaves the chooser waiting for a good one, which answers it once.
    assert driver._answer_chooser(tab, {"path": str(tmp_path / "cv.pdf")}) == "chose cv.pdf in the file chooser"
    assert chooser.files["name"] == "cv.pdf" and tab.chooser is None


class _Field:
    def __init__(self, index):
        self.index, self.files = index, None

    def set_input_files(self, payload):
        self.files = payload


class _FieldPage:
    def __init__(self):
        self.made = {}

    def locator(self, selector):
        assert selector == 'input[type="file"]'
        page = self

        class All:
            def nth(self, index):
                return page.made.setdefault(index, _Field(index))
        return All()


class _Button:
    def __init__(self, state, fields):
        self.state, self.fields = state, fields

    def evaluate(self, script):
        return self.state if script == tabs.ELEMENT_STATE_SCRIPT else self.fields


def test_a_button_that_opens_no_chooser_lists_the_file_fields_for_upload_by_number(driver, tmp_path, monkeypatch):
    from openprogram.host import sandbox
    monkeypatch.setattr(sandbox, "validate_read_path", lambda path: None)
    (tmp_path / "cv.pdf").write_bytes(b"%PDF")
    tab, page = tabs.Tab(id="t1", window_id="main", tab_id="a"), _FieldPage()
    fields = [{"index": 0, "id": "resumeKey", "name": "", "accept": ".pdf", "multiple": False, "disabled": False,
               "near": "Resume", "beside": True},
              {"index": 1, "id": "", "name": "old", "accept": "", "multiple": False, "disabled": True,
               "near": "", "beside": False}]
    message = driver._no_chooser_message(page, tab, _Button({"text": "Uploading... 100%", "disabled": True}, fields),
                                         "e90")
    assert "it reads 'Uploading... 100%'; it is disabled" in message and "reload it" in message
    # A disabled field is not offered; the one beside the button says so.
    assert "field 1: #resumeKey, accept=.pdf, near 'Resume', the only one in the button's section" in message
    assert "field 2" not in message and list(tab.file_fields) == [1]
    assert driver._upload_to_field(tab, {"field": 1, "path": str(tmp_path / "cv.pdf")}) == "chose cv.pdf in file field 1"
    assert page.made[0].files["name"] == "cv.pdf"
    with pytest.raises(tabs.BrowserError) as unknown:
        driver._upload_to_field(tab, {"field": 2, "path": str(tmp_path / "cv.pdf")})
    assert unknown.value.reason_code == "no_file_field"
    tab.forget_page()
    assert tab.file_fields == {}


def test_a_page_with_no_file_field_says_only_how_to_get_past_a_stuck_upload(driver):
    tab = tabs.Tab(id="t1", window_id="main", tab_id="a")
    message = driver._no_chooser_message(_FieldPage(), tab, _Button({"text": "", "disabled": False}, []), "e5")
    assert message.startswith("clicked e5, but it opened no file chooser and the page has no file field")
    assert tab.file_fields == {}


def test_a_finished_request_logs_its_status_without_asking_the_closed_page(driver):
    class Request:
        method, url, resource_type, frame = "GET", "https://x.test/api", "fetch", None
        existing_response = type("Response", (), {"status": 204})()

        def is_navigation_request(self):
            return False

        def response(self):
            raise AssertionError("a round trip races the page closing")

    class Page:
        main_frame = object()

        def __init__(self):
            self.handlers = {}

        def set_default_timeout(self, _ms):
            pass

        def on(self, event, handler):
            self.handlers[event] = handler

    page, finished, failed = Page(), Request(), Request()
    driver._watch(page, "T")
    for item in (finished, failed):
        page.handlers["request"](item)
    page.handlers["requestfinished"](finished)
    failed.failure = "net::ERR_ABORTED"
    page.handlers["requestfailed"](failed)
    watch = driver._watches["T"]
    assert not watch.pending
    assert [entry["status"] for entry in watch.network] == [204, 0]
    assert watch.network[1]["error"] == "net::ERR_ABORTED"
    assert tabs._response_status(type("Old", (), {"_impl_obj": type("I", (), {"_response": None})()})()) == 0


# -- what the conversation's preview follows --------------------------------


@pytest.fixture
def reports(driver, monkeypatch):
    """Operations the driver reports, as (page_key, operation, follow)."""
    from openprogram.programs.applications.browser import pages
    reported = []
    monkeypatch.setattr(pages, "publish_bound_page", lambda *args, **kwargs: None)
    monkeypatch.setattr(pages, "report_browser_operation",
                        lambda key, operation, *, follow, execution_id=None: reported.append((key, operation, follow)))
    monkeypatch.setattr(driver, "_catch_choosers", lambda tab: {})
    monkeypatch.setattr(driver, "_settle", lambda tab, acted: None)
    monkeypatch.setattr(driver, "_report", lambda tab, before_url: {"ok": True, "tab": tab.id, "url": "https://x.test/"})
    driver.listed["surfaces"][0]["page_key"] = "page:a"
    return reported


def _clicks(tab, action, args):
    tab.aim = {"point": {"x": 120.0, "y": 40.0}, "viewport": {"width": 800, "height": 600}}
    return tabs._Acted(done="clicked e1", before_url="", documents=0, pending=set(), created=0)


def test_a_click_is_followed_from_before_its_input_and_its_outcome_shows_where_it_landed(driver, reports, monkeypatch):
    monkeypatch.setattr(driver, "_operate", _clicks)
    assert driver.run("click", {"tab": A, "ref": "e1"}, "s1")["ok"]
    (key, dispatched, follow), (_, done, done_follow) = reports
    assert key == "page:a" and dispatched["phase"] == "dispatched" and follow is True
    assert "point" not in dispatched
    assert done["phase"] == "acknowledged" and done_follow is True and done["id"] == dispatched["id"]
    assert done["point"] == {"x": 120.0, "y": 40.0, "width": 800.0, "height": 600.0}


def test_each_step_of_a_list_reports_on_its_own(driver, reports, monkeypatch):
    monkeypatch.setattr(driver, "_operate", _clicks)
    with tabs.batch():
        driver.run("click", {"tab": A, "ref": "e1"}, "s1")
        driver.run("click", {"tab": A, "ref": "e2"}, "s1")
    assert [operation["phase"] for _, operation, _ in reports] == ["dispatched", "acknowledged"] * 2
    assert reports[0][1]["id"] != reports[2][1]["id"]


def test_a_read_is_followed_without_marking_the_page_operated(driver, reports, monkeypatch):
    monkeypatch.setattr(driver, "_operate", lambda tab, action, args: {"ok": True, "tab": tab.id, "page": "- x"})
    driver.run("read", {"tab": A}, "s1")
    [(key, operation, follow)] = reports
    assert key == "page:a" and operation["action"] == "read" and operation["phase"] == "acknowledged"
    assert follow is False


def test_a_tab_the_agent_opens_becomes_the_one_followed(driver, reports, monkeypatch):
    from openprogram.runtime.conversation import surface_context
    monkeypatch.setattr(surface_context, "open_page", lambda url, background=True: {
        "ok": True, "surfaces": [_surface("n", page_key="page:n")]})
    monkeypatch.setattr(driver, "_operate", lambda tab, action, args: {"ok": True, "tab": tab.id})
    driver.run("open", {"url": "https://x.test/new"}, "s1")
    [(key, operation, follow)] = reports
    assert key == "page:n" and operation["action"] == "open" and follow is False


def test_a_failed_action_reports_failed_and_does_not_keep_the_page_operated(driver, reports, monkeypatch):
    def fails(tab, action, args):
        raise tabs.BrowserError("not_editable", "e1 does not take text")
    monkeypatch.setattr(driver, "_operate", fails)
    result = driver.run("type", {"tab": A, "ref": "e1", "text": "hi"}, "s1")
    assert result["reason_code"] == "not_editable"
    assert [(operation["phase"], follow) for _, operation, follow in reports] == [("dispatched", True),
                                                                                  ("failed", False)]
    assert reports[1][1]["error"] == "not_editable"


def test_reporting_that_fails_never_fails_the_action(driver, reports, monkeypatch):
    from openprogram.programs.applications.browser import pages

    def broken(*args, **kwargs):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(pages, "report_browser_operation", broken)
    monkeypatch.setattr(pages, "publish_bound_page", broken)
    monkeypatch.setattr(driver, "_operate", _clicks)
    assert driver.run("click", {"tab": A, "ref": "e1"}, "s1")["ok"]
    monkeypatch.setattr(driver, "_operate", lambda tab, action, args: {"ok": True, "tab": tab.id})
    assert driver.run("read", {"tab": A}, "s1")["ok"]


def test_a_click_aims_at_the_centre_of_its_element_once_in_view():
    class Located:
        scrolled = False

        def scroll_into_view_if_needed(self, timeout=None):
            self.scrolled = True

        def bounding_box(self, timeout=None):
            return {"x": 100, "y": 30, "width": 40, "height": 20}

    class Viewed:
        def evaluate(self, script, *args):
            return {"width": 1280, "height": 720}

    tab = tabs.Tab(id="t1", window_id="main", tab_id="a")
    locator = Located()
    tabs.Driver._aim(None, Viewed(), tab, locator)
    assert locator.scrolled
    assert tab.aim == {"point": {"x": 120.0, "y": 40.0}, "viewport": {"width": 1280, "height": 720}}
    tabs.Driver._aim(None, Viewed(), tab, None, (5.0, 6.0))
    assert tab.aim["point"] == {"x": 5.0, "y": 6.0}


def test_a_subprocess_hands_its_operations_to_the_worker(monkeypatch):
    from openprogram.programs.applications.browser import pages
    handed = []
    pages.forward_operations_to_parent(handed.append)
    try:
        operation = pages.sanitize_operation(action="click", arguments={}, result={"ok": True},
                                             phase="dispatched", operation_id="op_1")
        pages.report_browser_operation("page:a", operation, follow=True, execution_id="exec-child")
    finally:
        pages.forward_operations_to_parent(None)
    assert handed == [{"page_key": "page:a", "operation": operation, "follow": True, "execution_id": "exec-child"}]
    # The worker keeps only the operation's own fields, and names the run it launched when none is given.
    calls = []
    monkeypatch.setattr(pages, "report_browser_operation",
                        lambda key, operation, *, follow, execution_id=None: calls.append(
                            (key, operation, follow, execution_id)))
    pages.report_forwarded_operation({**handed[0], "execution_id": "", "operation": {**operation, "html": "<b>"}},
                                     execution_id="exec-parent")
    assert calls == [("page:a", operation, True, "exec-parent")]
    pages.report_forwarded_operation({"page_key": "page:a", "operation": {"id": "op_2", "phase": "made-up"}})
    assert len(calls) == 1
