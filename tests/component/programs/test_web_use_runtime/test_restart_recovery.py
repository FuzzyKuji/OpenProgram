"""web_use recovery from ended turns, restarts and frame-independent actions."""

from __future__ import annotations
import pytest


class _FrameAdapter:
    """Each observe issues a new frame; a write invalidates it, like the controller."""

    supports_operation_guard = True

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple] = []
        self.frames = 0
        self.current = ""

    def observe(self, session, arguments, *, before_dispatch=None):
        self.frames += 1
        self.current = f"frame-{self.frames}"
        self.calls.append(("observe", self.current))
        return {
            "frame_id": self.current,
            "url": "https://example.test/",
            "target": {"kind": "web_tab", "tab_id": "tab-1", "target_id": "target-1"},
        }

    def act(self, session, arguments, *, before_dispatch=None):
        from openprogram.programs import ToolReturn

        action = arguments.get("action")
        frame_id = arguments.get("expected_frame_id")
        self.calls.append(("act", action, frame_id))
        if frame_id != self.current:
            self.current = ""
            return {"ok": False, "reason_code": "stale_observation"}
        if action == "screenshot":
            return ToolReturn(
                text=f"Current viewport screenshot for {frame_id}.",
                images=[b"png"],
                json_data={"frame_id": frame_id, "viewport": {"width": 10, "height": 10}},
            )
        if action == "wait":
            return {"ok": True, "frame_id": frame_id}
        self.current = ""
        return {"ok": True, "detail": action, "observe_required": True}

    def verify(self, session, arguments, *, before_dispatch=None):
        self.calls.append(("verify", arguments.get("expected_frame_id")))
        return {"ok": True, "passed": True}

    def close(self, session):
        self.calls.append(("close",))

    def writes(self) -> list[tuple]:
        return [call for call in self.calls if call[0] == "act"]


def _context(binding="binding-1", tab="tab-1", window="main"):
    return {
        "context_id": f"ctx-{binding}",
        "window_id": window,
        "surfaces": [{
            "surface_key": "p1", "binding_id": binding, "tab_id": tab,
            "window_id": window, "page_key": f"page-{binding}",
        }],
    }


def _registry():
    from openprogram.programs.applications.browser.web_use.runtime import (
        SUPPORTED_BACKENDS,
        WebUseSessionRegistry,
    )

    adapters = {name: _FrameAdapter(name) for name in SUPPORTED_BACKENDS}
    registry = WebUseSessionRegistry(
        adapters=adapters,
        binding_validator=lambda _binding: {"ok": True},
        binding_revision_resolver=lambda _binding: {},
        page_key_resolver=lambda binding: f"page-{binding}",
        release_context=lambda _context: None,
    )
    return registry, adapters["playwright_mcp"]


def _token(registry, owner, **context):
    return registry.list_pages(
        context=_context(**context), owner_id=owner,
    )["pages"][0]["page_context_token"]


OWNER = "turn:chat-1:turn-1"
NEXT_TURN = "turn:chat-1:turn-2"


def test_act_navigate_with_only_a_token_opens_the_session_first():
    registry, adapter = _registry()
    token = _token(registry, OWNER)

    result = registry.execute(
        command="act", owner_id=OWNER, page_context_token=token,
        arguments={"action": "navigate", "url": "https://next.test/"},
    )

    assert result["ok"] is True
    assert result["web_session_id"].startswith("cs_")
    assert adapter.calls == [("observe", "frame-1"), ("act", "navigate", "frame-1")]
    registry.close_all()


def test_act_click_with_only_a_token_returns_the_observation_unperformed():
    registry, adapter = _registry()
    token = _token(registry, OWNER)

    result = registry.execute(
        command="act", owner_id=OWNER, page_context_token=token,
        arguments={"action": "click", "ref": "e1"},
    )

    assert result["action_performed"] is False
    assert result["frame_id"] == "frame-1"
    assert "was not performed" in result["message"]
    assert adapter.writes() == []
    # The caller read this observation, so its refs are usable next.
    clicked = registry.execute(
        command="act", owner_id=OWNER, web_session_id=result["web_session_id"],
        arguments={"action": "click", "ref": "e1"},
    )
    assert clicked["ok"] is True
    registry.close_all()


def test_token_routes_to_its_own_page_never_the_latest_session():
    registry, _adapter = _registry()
    first = _token(registry, OWNER, binding="binding-1", tab="tab-1")
    session_a = registry.execute(
        command="observe", owner_id=OWNER, page_context_token=first,
    )["web_session_id"]
    second = _token(registry, OWNER, binding="binding-2", tab="tab-2")

    other_page = registry.execute(
        command="act", owner_id=OWNER, page_context_token=second,
        arguments={"action": "wait"},
    )
    same_page = registry.execute(
        command="act", owner_id=OWNER, page_context_token=first,
        arguments={"action": "wait"},
    )

    assert other_page["ok"] is True
    assert other_page["web_session_id"] != session_a
    assert same_page["web_session_id"] == session_a
    registry.close_all()


def test_screenshot_after_navigation_observes_first():
    registry, adapter = _registry()
    session_id = registry.execute(
        command="observe", owner_id=OWNER, page_context_token=_token(registry, OWNER),
    )["web_session_id"]
    registry.execute(
        command="act", owner_id=OWNER, web_session_id=session_id,
        arguments={"action": "navigate", "url": "https://next.test/"},
    )

    shot = registry.execute(
        command="act", owner_id=OWNER, web_session_id=session_id,
        arguments={"action": "screenshot"},
    )

    assert shot.json_data["frame_id"] == "frame-2"
    assert shot.images == [b"png"]
    assert adapter.calls[-2:] == [
        ("observe", "frame-2"), ("act", "screenshot", "frame-2"),
    ]
    registry.close_all()


def test_screenshot_retries_once_when_the_frame_changed_underneath():
    registry, adapter = _registry()
    session_id = registry.execute(
        command="observe", owner_id=OWNER, page_context_token=_token(registry, OWNER),
    )["web_session_id"]
    adapter.current = ""  # The page navigated on its own after the observe.

    shot = registry.execute(
        command="act", owner_id=OWNER, web_session_id=session_id,
        arguments={"action": "screenshot"},
    )

    assert shot.json_data["frame_id"] == "frame-2"
    assert adapter.calls[1:] == [
        ("act", "screenshot", "frame-1"),
        ("observe", "frame-2"),
        ("act", "screenshot", "frame-2"),
    ]
    registry.close_all()


def test_refs_need_an_explicit_observe_after_an_automatic_frame():
    registry, adapter = _registry()
    session_id = registry.execute(
        command="observe", owner_id=OWNER, page_context_token=_token(registry, OWNER),
    )["web_session_id"]
    registry.execute(
        command="act", owner_id=OWNER, web_session_id=session_id,
        arguments={"action": "navigate", "url": "https://next.test/"},
    )
    registry.execute(
        command="act", owner_id=OWNER, web_session_id=session_id,
        arguments={"action": "screenshot"},
    )
    writes = len(adapter.writes())

    by_ref = registry.execute(
        command="act", owner_id=OWNER, web_session_id=session_id,
        arguments={"action": "click", "ref": "e1"},
    )
    assert by_ref["reason_code"] == "stale_observation"
    assert by_ref["observe_required"] is True
    assert "Refs come only from an observe result" in by_ref["message"]
    assert len(adapter.writes()) == writes

    # Coordinates come from the screenshot the caller saw: allowed.
    by_point = registry.execute(
        command="act", owner_id=OWNER, web_session_id=session_id,
        arguments={"action": "click", "x": 3, "y": 4},
    )
    assert by_point["ok"] is True

    registry.execute(command="observe", owner_id=OWNER, web_session_id=session_id)
    assert registry.execute(
        command="act", owner_id=OWNER, web_session_id=session_id,
        arguments={"action": "click", "ref": "e1"},
    )["ok"] is True
    registry.close_all()


def test_write_after_a_write_asks_for_observe_instead_of_a_stale_frame():
    registry, adapter = _registry()
    session_id = registry.execute(
        command="observe", owner_id=OWNER, page_context_token=_token(registry, OWNER),
    )["web_session_id"]
    registry.execute(
        command="act", owner_id=OWNER, web_session_id=session_id,
        arguments={"action": "click", "ref": "e1"},
    )
    writes = len(adapter.writes())

    again = registry.execute(
        command="act", owner_id=OWNER, web_session_id=session_id,
        arguments={"action": "click", "ref": "e2"},
    )

    assert again["reason_code"] == "invalid_arguments"
    assert again["missing_arguments"] == ["expected_frame_id"]
    assert again["observe_required"] is True
    assert "Call observe" in again["message"]
    assert len(adapter.writes()) == writes
    registry.close_all()


def test_explicit_old_frame_is_still_rejected_with_one_instruction():
    registry, adapter = _registry()
    session_id = registry.execute(
        command="observe", owner_id=OWNER, page_context_token=_token(registry, OWNER),
    )["web_session_id"]

    stale = registry.execute(
        command="act", owner_id=OWNER, web_session_id=session_id,
        arguments={"action": "navigate", "url": "https://next.test/",
                   "expected_frame_id": "frame-0"},
    )

    assert stale["reason_code"] == "stale_observation"
    assert stale["observe_required"] is True
    assert stale["recovery_command"] == "observe"
    assert "Call observe" in stale["message"]
    assert len(adapter.writes()) == 1  # The stale check sent nothing; no retry.
    registry.close_all()


def test_ended_turn_token_names_its_page_only_for_the_same_chat():
    registry, _adapter = _registry()
    token = _token(registry, OWNER)
    registry.release_owner(OWNER)

    same_chat = registry.execute(
        command="observe", owner_id=NEXT_TURN, page_context_token=token,
    )
    other_chat = registry.execute(
        command="observe", owner_id="turn:chat-2:turn-1", page_context_token=token,
    )

    assert same_chat["reason_code"] == "page_context_not_found"
    assert same_chat["recovery_tab_id"] == "tab-1"
    assert same_chat["recovery_window_id"] == "main"
    assert same_chat["recovery_command"] == "observe"
    assert "list_pages" in same_chat["message"]
    assert other_chat["reason_code"] == "page_context_not_found"
    assert "recovery_tab_id" not in other_chat


def test_ended_session_names_its_page_but_a_closed_session_does_not():
    registry, _adapter = _registry()
    ended = registry.execute(
        command="observe", owner_id=OWNER, page_context_token=_token(registry, OWNER),
    )["web_session_id"]
    registry.release_owner(OWNER)

    gone = registry.execute(
        command="act", owner_id=NEXT_TURN, web_session_id=ended,
        arguments={"action": "click", "ref": "e1"},
    )
    assert gone["reason_code"] == "web_session_not_found"
    assert gone["recovery_tab_id"] == "tab-1"
    assert gone["recovery_window_id"] == "main"

    closed = registry.execute(
        command="observe", owner_id=NEXT_TURN,
        page_context_token=_token(registry, NEXT_TURN),
    )["web_session_id"]
    registry.execute(command="close", owner_id=NEXT_TURN, web_session_id=closed)
    after_close = registry.execute(
        command="observe", owner_id=NEXT_TURN, web_session_id=closed,
    )
    assert after_close["reason_code"] == "web_session_not_found"
    assert "recovery_tab_id" not in after_close
    registry.close_all()


def test_unknown_session_next_to_a_live_token_observes_with_the_token():
    registry, adapter = _registry()
    token = _token(registry, OWNER)

    observed = registry.execute(
        command="observe", owner_id=OWNER, web_session_id="cs_from_before_restart",
        page_context_token=token,
    )

    assert observed["frame_id"] == "frame-1"
    assert observed["web_session_id"] != "cs_from_before_restart"
    registry.close_all()


def test_consumed_token_names_its_live_session():
    registry, _adapter = _registry()
    token = _token(registry, OWNER)
    session_id = registry.execute(
        command="observe", owner_id=OWNER, page_context_token=token,
    )["web_session_id"]

    again = registry.execute(
        command="observe", owner_id=OWNER, page_context_token=token,
    )

    assert again["reason_code"] == "page_context_consumed"
    assert again["live_web_session_id"] == session_id
    assert session_id in again["message"]
    registry.close_all()


@pytest.fixture
def wrapper(monkeypatch):
    """The public web_use tool over a real registry and a fake Desktop."""
    from openprogram.runtime.conversation import surface_context
    from openprogram.programs.applications.browser import web_use as browser
    from openprogram.programs.applications.browser.web_use import runtime as web_use_runtime

    registry, adapter = _registry()
    owner = {"id": NEXT_TURN}
    monkeypatch.setattr(web_use_runtime, "get_registry", lambda: registry)
    monkeypatch.setattr(
        surface_context, "web_use_owner_id", lambda _context=None: owner["id"],
    )
    monkeypatch.setattr(
        surface_context, "current",
        lambda: {"context_id": "turn-ctx", "origin_window_id": "main",
                 "window_id": "main", "surfaces": []},
    )
    monkeypatch.setattr(
        surface_context, "capture_pages", lambda _current=None: _context(),
    )
    monkeypatch.setattr(surface_context, "release_bindings", lambda _context: None)
    monkeypatch.setattr(
        surface_context, "open_page",
        lambda *args, **kwargs: pytest.fail("recovery must not open a page"),
    )
    yield browser, registry, adapter, owner
    registry.close_all()


def test_wrapper_reobserves_the_page_named_by_an_expired_token(wrapper):
    browser, registry, adapter, _owner = wrapper
    token = _token(registry, OWNER)
    registry.release_owner(OWNER)

    result = browser.web_use(command="observe", page_context_token=token)

    assert isinstance(result, dict)
    assert result["recovered_page"] is True
    assert result["recovery_reason_code"] == "page_context_not_found"
    assert result["previous_action_replayed"] is False
    assert result["frame_id"] == "frame-1"
    assert result["web_session_id"].startswith("cs_")


def test_wrapper_never_replays_the_act_of_an_ended_session(wrapper):
    browser, registry, adapter, owner = wrapper
    owner["id"] = OWNER
    ended = browser.web_use(
        command="observe", page_context_token=_token(registry, OWNER),
    )["web_session_id"]
    registry.release_owner(OWNER)
    owner["id"] = NEXT_TURN

    result = browser.web_use(
        command="act", web_session_id=ended,
        arguments={"action": "click", "ref": "e1"},
    )

    assert result["recovered_page"] is True
    assert result["previous_action_replayed"] is False
    assert adapter.writes() == []


def test_wrapper_lists_current_pages_after_a_restart(wrapper):
    browser, _registry_, _adapter, _owner = wrapper

    failed = browser.web_use(
        command="observe", web_session_id="cs_before_restart",
        page_context_token="pct_before_restart",
    )

    assert failed.is_error is True
    failure = failed.json_data
    assert failure["reason_code"] == "page_context_not_found"
    assert failure["recovery_command"] == "observe"
    assert "page_context_token of the task page" in failure["message"]
    fresh = failure["pages"][0]["page_context_token"]
    # Following the instruction works in one call.
    observed = browser.web_use(command="observe", page_context_token=fresh)
    assert observed["frame_id"]


def test_wrapper_keeps_the_live_session_instruction_for_a_reused_token(wrapper):
    browser, registry, _adapter, _owner = wrapper
    token = _token(registry, NEXT_TURN)
    session_id = browser.web_use(
        command="observe", page_context_token=token,
    )["web_session_id"]

    again = browser.web_use(command="observe", page_context_token=token)

    assert again.is_error is True
    assert again.json_data["live_web_session_id"] == session_id
    assert "pages" not in again.json_data
    # Following the instruction reuses the same session.
    observed = browser.web_use(command="observe", web_session_id=session_id)
    assert observed["web_session_id"] == session_id


def test_list_pages_reports_a_restarting_desktop_instead_of_raising(wrapper, monkeypatch):
    from openprogram.runtime.conversation import surface_context

    browser = wrapper[0]

    def unavailable(_context=None):
        raise surface_context.DesktopUnavailableError(
            "originating Desktop window is unavailable"
        )

    monkeypatch.setattr(surface_context, "capture_pages", unavailable)
    monkeypatch.setattr(surface_context, "DESKTOP_RECONNECT_WAIT_SECONDS", 0.0)

    result = browser.web_use(command="list_pages")

    assert result.is_error is True
    assert result.json_data["reason_code"] == "desktop_unavailable"
    assert result.json_data["retry_command"] == "list_pages"
    assert "list_pages again" in result.json_data["message"]


def test_list_pages_lists_other_windows_when_the_origin_window_is_gone(wrapper, monkeypatch):
    from openprogram.runtime.conversation import surface_context

    browser = wrapper[0]

    def capture(context=None):
        if context is not None:
            raise surface_context.DesktopUnavailableError(
                "originating Desktop window is unavailable"
            )
        return _context(binding="binding-9", tab="tab-9", window="window-2")

    monkeypatch.setattr(surface_context, "capture_pages", capture)

    result = browser.web_use(command="list_pages")

    assert result["ok"] is True
    assert [page["window_id"] for page in result["pages"]] == ["window-2"]


def test_recovery_with_a_closed_tab_and_no_url_opens_nothing(wrapper):
    browser = wrapper[0]
    failure = {
        "ok": False, "reason_code": "web_session_not_found",
        "recovery_tab_id": "tab-closed", "recovery_window_id": "main",
    }

    assert browser._recover_web_use_page(failure, backend="") is failure
