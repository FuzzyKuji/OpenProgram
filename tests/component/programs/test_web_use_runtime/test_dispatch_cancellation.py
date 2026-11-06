"""Ordinary browser entries must recheck cancellation after acquiring a Page."""
from __future__ import annotations

import threading

import pytest

from openprogram.runtime.execution import run_control as execution_run_control
from openprogram.runtime.execution.run_control import binding as run_control_binding
from openprogram.host.cancellation import CancelledError
from openprogram.programs.applications.browser.web_use.execute import (
    _execute_web_use, execute_direct_web_use,
)
from openprogram.programs.applications.browser.web_use.runtime import (
    SUPPORTED_BACKENDS, WebUseSessionRegistry,
)


@pytest.mark.parametrize("entry", ["ordinary", "direct"])
@pytest.mark.parametrize("cancel", [True, False])
def test_cancel_while_waiting_for_page_never_dispatches(monkeypatch, entry, cancel):
    calls, results, failures = [], [], []

    class Adapter:
        supports_operation_guard = True

        def observe(self, session, arguments, *, before_dispatch=None):
            if before_dispatch:
                before_dispatch()
            return {"frame_id": "frame-1"}

        def act(self, session, arguments, *, before_dispatch=None):
            if before_dispatch:
                before_dispatch()
            calls.append(arguments["action"])
            return {"ok": True}

        def close(self, session):
            pass

    registry = WebUseSessionRegistry(
        adapters={name: Adapter() for name in SUPPORTED_BACKENDS},
        binding_validator=lambda _: {"ok": True},
        binding_revision_resolver=lambda _: {}, page_key_resolver=lambda _: "",
        release_context=lambda _: None,
    )
    monkeypatch.setattr("openprogram.programs.applications.browser.web_use.runtime.get_registry", lambda: registry)
    monkeypatch.setattr("openprogram.runtime.conversation.surface_context.web_use_owner_id", lambda _: "owner")
    observed = registry.execute(command="observe", owner_id="owner", backend="open_claude_chrome", binding_id="binding")
    session = registry._sessions[observed["web_session_id"]]
    operation_lock = session.operation_lock
    waiting = threading.Event()

    class ObservedLock:
        def __enter__(self):
            waiting.set()
            operation_lock.acquire()

        def __exit__(self, *_):
            operation_lock.release()

    session.operation_lock = ObservedLock()
    token = execution_run_control.CancellationToken("browser-cancel")

    def worker():
        bound = run_control_binding._current_token.set(token)
        try:
            request = {"command": "act", "web_session_id": observed["web_session_id"],
                       "arguments": {"action": "click", "ref": "button"}}
            result = (_execute_web_use(**request) if entry == "ordinary"
                      else execute_direct_web_use(request, owner_id="owner"))
            results.append(result)
        except BaseException as error:
            failures.append(error)
        finally:
            run_control_binding._current_token.reset(bound)

    thread = threading.Thread(target=worker)
    try:
        with operation_lock:
            thread.start()
            assert waiting.wait(30), "entry did not reach the real Page operation lock"
            if cancel:
                token.cancel()
        thread.join(30)
        assert not thread.is_alive()
        if cancel:
            assert calls == []
            assert results == []
            assert len(failures) == 1 and isinstance(failures[0], CancelledError)
        else:
            assert calls == ["click"]
            assert results[0]["ok"] is True and failures == []
    finally:
        if thread.ident is not None:
            thread.join(5)
        registry.close_all()


@pytest.mark.parametrize("entry", ["ordinary", "direct"])
@pytest.mark.parametrize("cancel_during_open", [True, False])
def test_new_page_acquisition_does_not_observe_after_cancel(monkeypatch, entry, cancel_during_open):
    from ._support import _NativeObserveAdapter

    adapter = _NativeObserveAdapter("open_claude_chrome")
    registry = WebUseSessionRegistry(
        adapters={name: adapter for name in SUPPORTED_BACKENDS},
        binding_validator=lambda _: {"ok": True},
        binding_revision_resolver=lambda _: {}, page_key_resolver=lambda _: "",
        release_context=lambda _: None,
    )
    context = {"context_id": "opened", "window_id": "window", "surfaces": [
        {"binding_id": "binding", "surface_key": "page", "window_id": "window", "tab_id": "tab"},
    ]}
    opened, released = [], []
    token = execution_run_control.CancellationToken("browser-open-cancel")

    def open_page(*args, **kwargs):
        opened.append(context)
        token.cancel()
        return context

    monkeypatch.setattr("openprogram.programs.applications.browser.web_use.runtime.get_registry", lambda: registry)
    monkeypatch.setattr("openprogram.runtime.conversation.surface_context.current", lambda: None)
    monkeypatch.setattr("openprogram.runtime.conversation.surface_context.web_use_owner_id", lambda _: "owner")
    monkeypatch.setattr("openprogram.runtime.conversation.surface_context.open_page", open_page)
    monkeypatch.setattr("openprogram.runtime.conversation.surface_context.release_bindings", released.append)
    bound = run_control_binding._current_token.set(token)
    try:
        if not cancel_during_open:
            token.cancel()
        request = {"command": "observe", "backend": "open_claude_chrome",
                   "arguments": {"url": "https://example.test"}}
        with pytest.raises(CancelledError):
            if entry == "ordinary":
                _execute_web_use(**request)
            else:
                execute_direct_web_use(request, owner_id="owner")
        assert "observe" not in adapter.calls
        assert opened == ([context] if cancel_during_open else [])
        if opened:
            assert context in released
        assert registry._sessions == {}
    finally:
        run_control_binding._current_token.reset(bound)
        registry.close_all()
