from __future__ import annotations


















import pytest


from openprogram.runtime.jobs.resource_governance import (
    ResourceLimits,
    ResourceGovernor,
    resolve_resource_limits,
)




from openprogram.runtime.jobs.types import Job




from openprogram.models.usage.ledger import UsageLedger


from tests.component.agent import async_job_support as _async_job_support

# Shared pytest fixtures, bound at module level so pytest collects them here.
store_fixture = _async_job_support.store_fixture


@pytest.fixture(autouse=True)
def _worker_lock_is_held(monkeypatch):
    monkeypatch.setattr(
        "openprogram.operations.worker.lock.is_held_by", lambda _pid: True,
        raising=False,
    )


def _admit_fanout_process(db_path, index, start, output, fanout_limit=5) -> None:
    from openprogram.state import config as user_config

    user_config.read_config = lambda: {
        "agent": {"max_spawn_depth": 0, "max_spawn_fanout": fanout_limit}
    }
    start.wait()
    resolved = resolve_resource_limits(ResourceLimits(), scheduler_capacity=32)
    governor = ResourceGovernor(
        UsageLedger(db_path),
        limit_resolver=lambda _sid, _job: resolved,
    )
    decision = governor.admit_job(
        Job(
            id=f"process_{index}", parent_session_id="s1",
            prompt=str(index), agent_id="a", chain_generations=1,
        ),
        persist=lambda _job: None,
        caller_turn_id="turn_1",
    )
    output.put((decision.accepted, decision.reason_code))


def _migrate_admission_schema_process(db_path, start, output) -> None:
    start.wait()
    try:
        ledger = UsageLedger(db_path)
        columns = {
            row[1]
            for row in ledger.connection().execute(
                "PRAGMA table_info(job_admissions)"
            )
        }
        output.put(("ok", len(columns)))
        ledger.close()
    except Exception as exc:  # noqa: BLE001
        output.put(("error", type(exc).__name__, str(exc)))

