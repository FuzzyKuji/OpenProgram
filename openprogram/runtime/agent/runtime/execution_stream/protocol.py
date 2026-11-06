"""execution_stream.v1 protocol constants and helpers."""
from __future__ import annotations

from typing import Any, Final, Mapping

SCHEMA_VERSION: Final[int] = 1
PROTOCOL_NAME: Final[str] = "execution_stream.v1"

# Visible block kinds (design §4). Opaque signatures never use these.
BlockKind = str  # text | reasoning_summary | tool_ref | tool_arguments | parallel_group | refusal | unsupported

STREAM_OPS: Final[frozenset[str]] = frozenset(
    {
        "attempt_started",
        "block_started",
        "block_delta",
        "block_finished",
        "attempt_finished",
        "snapshot",
        "node_finished",
        "sync_required",
    }
)

StreamOp = str

ATTEMPT_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "running",
        "completed",
        "failed",
        "cancelled",
        "superseded",
    }
)

NODE_PHASES: Final[frozenset[str]] = frozenset(
    {
        "created",
        "running",
        "retry_wait",
        "validating",
        "finalizing",
        "completed",
        "cancelling",
        "cancelled",
        "failed",
        "paused",
        "reconciliation_required",
    }
)

TERMINAL_PHASES: Final[frozenset[str]] = frozenset(
    {"completed", "cancelled", "failed"}
)

# Frame budgets (design §6 / §10) — engineering targets.
MAX_FRAME_BYTES: Final[int] = 64 * 1024
MAX_INLINE_PREVIEW_BYTES: Final[int] = 32 * 1024
MAX_IDENTITY_HEADER_BYTES: Final[int] = 16 * 1024
DELTA_MERGE_MS: Final[int] = 25
DELTA_MERGE_BYTES: Final[int] = 16 * 1024
CHECKPOINT_DIRTY_BYTES: Final[int] = 64 * 1024
CHECKPOINT_INTERVAL_S: Final[float] = 0.25


def attempt_status_values() -> frozenset[str]:
    return ATTEMPT_STATUSES


def is_terminal_phase(phase: str | None) -> bool:
    return (phase or "") in TERMINAL_PHASES


def version_tuple(generation: int, revision: int) -> tuple[int, int]:
    return (int(generation), int(revision))


def compare_version(
    a_gen: int, a_rev: int, b_gen: int, b_rev: int
) -> int:
    """Return -1 / 0 / 1 for a ? b. Generation dominates revision."""
    if a_gen != b_gen:
        return -1 if a_gen < b_gen else 1
    if a_rev != b_rev:
        return -1 if a_rev < b_rev else 1
    return 0


def envelope_identity_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    """Extract required identity fields for validation / logging."""
    return {
        "session_id": data.get("session_id"),
        "execution_id": data.get("execution_id"),
        "node_id": data.get("node_id"),
        "generation": data.get("generation"),
        "display_msg_id": data.get("display_msg_id"),
    }


def build_chat_response_envelope(
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Wrap protocol payload in the WS ``chat_response`` envelope."""
    payload = dict(data)
    payload.setdefault("type", "execution_stream")
    payload.setdefault("schema_version", SCHEMA_VERSION)
    return {"type": "chat_response", "data": payload}
