"""
Tier 5 Reactive compaction — emergency recovery when the LLM returns
a context overflow error (413 / prompt_too_long).

Installs a summary through ``engine.compact``, then signals the caller to
retry the LLM call, which renders the shortened context from the DAG. At
most one reactive attempt per turn.
"""
from __future__ import annotations

import asyncio
import logging


log = logging.getLogger(__name__)


def is_overflow_error(exc: Exception) -> bool:
    """Check if an exception wraps a context overflow error."""
    msg_text = str(exc)
    from openprogram.models.providers.utils.overflow import OVERFLOW_PATTERNS, _STATUS_CODE_RE
    for p in OVERFLOW_PATTERNS:
        if p.search(msg_text):
            return True
    if _STATUS_CODE_RE.match(msg_text):
        return True
    return False


def reactive_compact(
    *,
    agent_profile: dict,
    session_id: str,
    model: str,
    on_event,
) -> list[dict] | None:
    """Attempt emergency compaction after a context overflow error.

    Returns the compacted history if successful, None if compaction
    failed or didn't free enough space.
    """
    log.warning("Tier 5 Reactive: context overflow detected, attempting emergency compact")

    on_event({"type": "chat_response",
              "data": {"type": "reactive_compact_started",
                       "session_id": session_id}})

    try:
        from openprogram.models.providers.utils.http_client import shutdown_loop_clients
        from openprogram.runtime.context import resolve_engine_for
        engine = resolve_engine_for(agent_profile)
        loop = asyncio.new_event_loop()
        try:
            compact_res = loop.run_until_complete(
                engine.compact(
                    agent=agent_profile,
                    session_id=session_id,
                    model=model,
                    on_event=on_event,
                    user_initiated=False,
                )
            )
        finally:
            # The provider clients the summary call built are keyed by this
            # loop; left open, they count against the shared cache for good.
            shutdown_loop_clients(loop)
            loop.close()

        if compact_res.summary_id:
            log.info("Reactive auto-compact succeeded: %s", compact_res.summary_id)
            on_event({"type": "chat_response",
                      "data": {"type": "reactive_compact_done",
                               "session_id": session_id,
                               "summary_id": compact_res.summary_id}})
            from openprogram.runtime.context.session_db import default_db
            from openprogram.runtime.context.persistence import rendered_history
            db = default_db()
            # The retry must see the post-compaction view (summary +
            # kept tail), not the raw walk that just overflowed.
            new_history = rendered_history(db, session_id)
            if new_history:
                return new_history
    except Exception as e:
        log.warning("Reactive auto-compact failed: %s", e)

    on_event({"type": "chat_response",
              "data": {"type": "reactive_compact_failed",
                       "session_id": session_id}})
    return None
