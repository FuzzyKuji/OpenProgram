"""A web_use refusal says nothing reached the page; a stopped sub-agent ends its caller's wait."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("reason, dispatched", [
    ("desktop_response_timeout", False), ("stale_observation", False),
    ("page_in_use", False), ("backend_action_failed", None),
])
def test_refusals_carry_action_dispatched_false(monkeypatch, reason, dispatched):
    from openprogram.programs.applications.browser import web_use as browser

    monkeypatch.setattr(browser, "_execute_web_use",
                        lambda *args, **kwargs: {"ok": False, "reason_code": reason})
    result = browser.run_web_use("act", arguments={"action": "press", "key": "Tab"})
    assert result.is_error
    assert result.json_data.get("action_dispatched") is dispatched


@pytest.mark.parametrize("status, attempt, ends", [
    ("reconciliation_required", None, True), ("paused", None, True),
    ("running", "attempt-1", False),
])
def test_durable_wait_ends_when_the_execution_stops(status, attempt, ends):
    from openprogram.runtime.jobs.runner.service import JobRunner
    from openprogram.runtime.jobs.types import JobStatus

    runner = JobRunner.__new__(JobRunner)
    job = SimpleNamespace(status=JobStatus.RUNNING)
    runner.get_job = lambda job_id: job
    runner._execution_store = SimpleNamespace(get_execution=lambda job_id: SimpleNamespace(
        status=SimpleNamespace(value=status), current_attempt_id=attempt, reason_code=""))
    assert runner.await_job_durable("j_1", timeout=0.3) is job
    assert (runner.stopped_execution("j_1") is not None) is ends
