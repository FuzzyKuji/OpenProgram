"""Evidence that a suspended durable function left nothing unresolved.

A durable function (``openprogram.runtime.agent.durable_steps``) records its
admission as a ``function.admitted`` execution event and each external step
as an effect tagged with ``function_step.call``. Both live in this store, so
the control plane can prove from its own tables that an aggregate tool call
stopped at a durable boundary.
"""
from __future__ import annotations


def suspension_evidence(store, connection, execution_id, call_key):
    """Prove an aggregate tool invocation contains only settled durable steps."""
    admitted = connection.execute(
        "SELECT 1 FROM execution_events WHERE execution_id = ? AND kind = 'function.admitted' "
        "AND json_extract(payload_json, '$.call_key') = ? LIMIT 1",
        (execution_id, call_key),
    ).fetchone()
    if admitted is None:
        return False
    uncertain = connection.execute(
        "SELECT 1 FROM effects WHERE execution_id = ? AND status IN ('dispatched', 'uncertain') "
        "AND (json_extract(metadata_json, '$.function_step.call') = ? OR "
        "substr(json_extract(metadata_json, '$.function_step.call'), 1, ?) = ?) LIMIT 1",
        (execution_id, call_key, len(call_key) + 1, call_key + "/"),
    ).fetchone()
    return uncertain is None
