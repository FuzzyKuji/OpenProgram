"""Single source of truth for which chat model a session runs.

Display, dispatch, retry, and logs must all call these helpers. A session
pin always wins. A new session starts on its Agent's own model when the
Agent has one, otherwise on the model the user ran last; that choice is
copied onto the session at create (or once at first send if the pin was
lost) and then never re-read for that session — that is what stopped Sol
chips from silently answering on Grok. There is no default model: with
nothing used yet, a new session has no model until the user picks one.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

_log = logging.getLogger(__name__)


def new_session_chat_model(agent_id: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """Model a *new* session starts on; never consulted for a pinned turn.

    The Agent's own model when it has one, else the last used model, else
    nothing.
    """
    try:
        from openprogram.runtime.agent_registry.manager import DEFAULT_AGENT_ID, get as get_agent
        spec = get_agent(agent_id or DEFAULT_AGENT_ID)
        provider = (spec.model.provider or "").strip() or None if spec else None
        model = (spec.model.id or "").strip() or None if spec else None
        if provider and model:
            return provider, model
    except Exception as exc:
        _log.warning("agent chat model unavailable: %s", exc)
    try:
        from openprogram.models.providers.catalog.last_used import read_last_used_model
        pair = read_last_used_model()
        if pair:
            return pair
    except Exception as exc:
        _log.warning("last used model unavailable: %s", exc)
    return None, None


def read_session_chat_model(session_id: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Return the session pin, or (None, None). Does not consult agent.json."""
    if not session_id:
        return None, None
    from openprogram.runtime.context import Context
    context = Context.current()
    if context is not None and context.store is not None:
        return _read_db_pin(session_id)
    provider, model = _read_memory_pin(session_id)
    if provider and model:
        return provider, model
    return _read_db_pin(session_id)


def ensure_session_chat_model(
    session_id: Optional[str],
    agent_id: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Pin used for this turn.

    If the session already has a pin, return it. If the session exists
    but the pin was dropped, freeze the new-session choice onto it once so
    chip and dispatch cannot diverge again.
    """
    provider, model = read_session_chat_model(session_id)
    if provider and model:
        return provider, model
    provider, model = new_session_chat_model(agent_id)
    if session_id and provider and model:
        write_session_chat_model(session_id, provider, model)
    return provider, model


def write_session_chat_model(session_id: str, provider: str, model: str) -> None:
    from openprogram.runtime.context import Context
    context = Context.current()
    try:
        if context is None or context.store is None:
            from openprogram.runtime import interface_link
            conv = interface_link.live_session(session_id)
            if isinstance(conv, dict):
                conv["provider_override"] = provider
                conv["model_override"] = model
    except Exception as exc:
        _log.warning("session pin memory write failed session=%s: %s", session_id, exc)
    try:
        Context.turn_store(session_id).update_session(
            session_id,
            provider_override=provider,
            model_override=model,
        )
    except Exception as exc:
        _log.warning("session pin persist failed session=%s: %s", session_id, exc)
        raise


def override_string(provider: Optional[str], model: Optional[str]) -> Optional[str]:
    if provider and model:
        return f"{provider}/{model}"
    return model or None


def _read_memory_pin(session_id: str) -> tuple[Optional[str], Optional[str]]:
    try:
        from openprogram.runtime import interface_link
        conv = interface_link.live_session(session_id) or {}
        provider = conv.get("provider_override")
        model = conv.get("model_override")
        if provider:
            return provider, model
        if model:
            return None, model
    except Exception as exc:
        _log.warning("session pin memory read failed session=%s: %s", session_id, exc)
    return None, None


def _read_db_pin(session_id: str) -> tuple[Optional[str], Optional[str]]:
    try:
        from openprogram.runtime.context import Context
        meta = Context.turn_store(session_id).get_session(session_id) or {}
        extra = meta.get("extra_meta") or {}
        if isinstance(extra, str):
            extra = json.loads(extra)
        if not isinstance(extra, dict):
            extra = {}
        provider = meta.get("provider_override") or extra.get("provider_override")
        model = meta.get("model_override") or extra.get("model_override")
        if provider:
            return provider, model
        if model:
            return None, model
    except Exception as exc:
        _log.warning("session pin db read failed session=%s: %s", session_id, exc)
    return None, None
