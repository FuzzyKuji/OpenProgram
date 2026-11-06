"""Runtime / provider / model switch endpoints + agent_settings.

Routes here mutate `_user_pinned_*` and `runtime_management.*` on the
server module. Reads of those module-level singletons inside server
(e.g. `_get_or_create_session` reads `_user_pinned_provider`) keep
working because we write back via `setattr(_s, ...)`, which targets the
exact same module-level name the readers resolve.

Endpoints:
  GET  /api/providers
  POST /api/provider/{name}
  GET  /api/models
  POST /api/model
  GET  /api/agent_settings
  POST /api/agent_settings
"""
from __future__ import annotations

import logging
import asyncio

from fastapi.responses import JSONResponse

from openprogram.runtime.events import emit_ws_frame

_log = logging.getLogger(__name__)


def _runtime_build_error_response(exc: Exception, provider: str | None = None):
    """Turn a runtime-construction failure into a graceful structured 4xx
    instead of a 500 traceback.

    Building a runtime acquires the provider credential (codex/anthropic
    refresh OAuth in ``__init__``). When that credential is expired with a
    dead refresh token, CredentialProvider raises ``AuthNeedsReauthError`` /
    ``AuthReadOnlyError`` / ``AuthPoolExhaustedError`` / ``AuthConfigError``;
    the anthropic runtime instead raises ``ValueError("No Anthropic
    credential …")`` once resolution comes back empty. A failed/expired
    login is an expected state — return ``needs_reauth`` with the provider
    so the UI can prompt re-login, not crash the whole panel.

    Any other build failure (unknown model, no registry entry) is a
    request-level problem too, so it returns a 400 with the message rather
    than a 500."""
    from openprogram.models.auth.types import (
        AuthConfigError,
        AuthError,
        AuthNeedsReauthError,
        AuthPoolExhaustedError,
        AuthReadOnlyError,
    )
    needs_reauth = isinstance(
        exc,
        (AuthNeedsReauthError, AuthReadOnlyError,
         AuthPoolExhaustedError, AuthConfigError),
    )
    if not needs_reauth and isinstance(exc, ValueError) and "credential" in str(exc).lower():
        needs_reauth = True
    prov = (getattr(exc, "provider_id", "") if isinstance(exc, AuthError) else "") or provider or None
    return JSONResponse(
        content={
            "error": str(exc),
            "needs_reauth": needs_reauth,
            "provider": prov,
        },
        status_code=401 if needs_reauth else 400,
    )


def register(app):
    @app.get("/api/providers")
    async def get_providers():
        from openprogram.interfaces.server import server as _s
        return JSONResponse(content=_s._list_providers())

    @app.post("/api/provider/{name}")
    async def switch_provider(name: str, body: dict = None):
        from openprogram.interfaces.server import server as _s
        session_id = body.get("session_id") if body else None
        if session_id:
            with _s._sessions_lock:
                conv = _s._sessions.get(session_id)
            if conv and conv.get("provider_name") == name:
                return JSONResponse(content={"switched": False, "already_active": True, "provider": name})
        elif name == _s.runtime_management._default_provider:
            return JSONResponse(content={"switched": False, "already_active": True, "provider": name})
        try:
            _s._switch_runtime(name, session_id=session_id)
            return JSONResponse(content={"switched": True, "provider": name})
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=400)

    @app.get("/api/models")
    async def list_models():
        """List available models for the current provider."""
        from openprogram.interfaces.server import server as _s
        with _s.runtime_management._runtime_lock:
            if _s.runtime_management._default_provider is None:
                (_s.runtime_management._default_provider,
                 _s.runtime_management._default_runtime) = _s._detect_default_provider()

        provider = _s.runtime_management._default_provider or "none"
        runtime = _s.runtime_management._default_runtime
        current_model = runtime.model if runtime else None

        model_list = []
        if runtime and hasattr(runtime, "list_models"):
            try:
                model_list = runtime.list_models()
            except Exception as e:
                _log.warning("list_models for %s failed: %s", provider, e)
        if current_model and current_model not in model_list:
            model_list = [current_model] + model_list

        return JSONResponse(content={
            "provider": provider,
            "current": current_model,
            "models": model_list,
        })

    @app.post("/api/model")
    async def switch_model(body: dict = None):
        """Switch model (and optionally provider) for the active runtime.

        Body: {"model": str (bare id or "provider:id"), "provider": str?,
               "session_id": str?}
        """
        from openprogram.interfaces.server import server as _s
        _s._log(f"[/api/model] body={body!r}")
        if not body or "model" not in body:
            return JSONResponse(content={"error": "Missing model"}, status_code=400)
        model = body["model"].strip()
        explicit_provider = (body.get("provider") or "").strip() or None
        session_id = body.get("session_id")

        inferred_provider = None
        bare_model = model
        if explicit_provider is None and ":" in model:
            head, tail = model.split(":", 1)
            from openprogram.models.providers import get_providers as _get_providers
            known = set(_get_providers())
            known.update({"openai-codex", "gemini-cli",
                          "anthropic", "openai", "gemini"})
            if head in known:
                inferred_provider = head
                bare_model = tail
        target_provider = explicit_provider or inferred_provider

        async def _build_rt(provider: str):
            return await asyncio.to_thread(
                _s._create_runtime_for_visualizer, provider, bare_model
            )

        if session_id:
            with _s._sessions_lock:
                conv = _s._sessions.get(session_id)
            if conv is None:
                conv = await asyncio.to_thread(_s._get_or_create_session, session_id)
            _s._log(
                f"[/api/model] session_id={session_id!r} conv_found={conv is not None} "
                f"target_provider={target_provider!r} bare_model={bare_model!r}"
            )
            if conv:
                old_rt = conv.get("runtime")
                cur_prov = conv.get("provider_name", _s.runtime_management._default_provider)
                prov = target_provider or cur_prov
                need_new_rt = (target_provider and target_provider != cur_prov) or (old_rt is None)
                runtime_ready = old_rt is not None
                if need_new_rt:
                    try:
                        new_rt = await _build_rt(prov)
                    except Exception as e:
                        _s._log(f"[/api/model] runtime build skipped for {prov}: {e}")
                        new_rt = None
                    if new_rt is not None:
                        if old_rt and hasattr(old_rt, "close"):
                            try:
                                old_rt.close()
                            except Exception:
                                # The old runtime is being replaced; a failed
                                # close must not block the switch.
                                _log.debug(
                                    "closing replaced runtime for %s failed", prov, exc_info=True)
                        conv["runtime"] = new_rt
                    runtime_ready = new_rt is not None
                    conv["provider_name"] = prov
                else:
                    if old_rt is not None:
                        old_rt.model = bare_model
                conv["provider_override"] = prov
                conv["model_override"] = bare_model
                _s._log(
                    f"[/api/model] post-write conv id={id(conv)} "
                    f"provider_override={conv.get('provider_override')!r} "
                    f"model_override={conv.get('model_override')!r} "
                    f"sessions[sid] id={id(_s._sessions.get(session_id))}"
                )
                def _persist_override():
                    from openprogram.runtime.conversation.session_model import write_session_chat_model
                    from openprogram.models.providers.catalog.last_used import record_last_used_model
                    write_session_chat_model(session_id, prov, bare_model)
                    _s._save_session(session_id)
                    record_last_used_model(prov, bare_model)
                await asyncio.to_thread(_persist_override)
                info = _s._get_provider_info(session_id)
                emit_ws_frame({"type": "provider_changed", "data": info})
                from openprogram.models.listing.listing import supports_fast as _supports_fast
                emit_ws_frame({
                    "type": "agent_settings_changed",
                    "data": {
                        "chat": {
                            "provider": prov,
                            "model": bare_model,
                            "thinking": _s._get_thinking_config_for_model(prov, bare_model),
                            "fast": _supports_fast(prov, bare_model),
                        },
                    },
                })
                _s.refresh_context_stats(session_id)
                return JSONResponse(content={
                    "switched": True,
                    "provider": prov,
                    "model": bare_model,
                    "runtime_ready": runtime_ready,
                })

        if target_provider and target_provider != _s.runtime_management._default_provider:
            try:
                new_rt = await _build_rt(target_provider)
            except Exception as e:
                return _runtime_build_error_response(e, target_provider)
            if _s.runtime_management._default_runtime and hasattr(
                _s.runtime_management._default_runtime, "close"
            ):
                try:
                    _s.runtime_management._default_runtime.close()
                except Exception:
                    # The old runtime is being replaced; a failed close must
                    # not block the switch.
                    _log.debug("closing replaced default runtime failed", exc_info=True)
            _s.runtime_management._default_runtime = new_rt
            _s.runtime_management._default_provider = target_provider
        elif _s.runtime_management._default_runtime:
            _s.runtime_management._default_runtime.model = bare_model
        else:
            return JSONResponse(content={"error": "No active runtime"}, status_code=400)

        _s._user_pinned_provider = target_provider or _s.runtime_management._default_provider
        _s._user_pinned_model = bare_model

        # Persist the choice — without this the switch lived only in the
        # module globals, and a restart forgot what the user last picked.
        from openprogram.models.providers.catalog.last_used import record_last_used_model
        await asyncio.to_thread(
            record_last_used_model, _s._user_pinned_provider, bare_model,
        )

        info = _s._get_provider_info()
        emit_ws_frame({"type": "provider_changed", "data": info})
        return JSONResponse(content={
            "switched": True,
            "provider": target_provider or _s.runtime_management._default_provider,
            "model": bare_model,
        })

    @app.get("/api/agent_settings")
    async def get_agent_settings(session_id: str = None):
        """Return current chat/exec provider+model. Optionally per-session."""
        from openprogram.interfaces.server import server as _s
        from openprogram.models.listing.listing import (
            supports_fast as _supports_fast,
        )
        await asyncio.to_thread(_s._init_providers)

        chat_session_id = None
        chat_locked = False
        conv = None
        if session_id:
            with _s._sessions_lock:
                conv = _s._sessions.get(session_id)
            if conv is None:
                conv = await asyncio.to_thread(_s._get_or_create_session, session_id)
            if conv:
                rt = conv.get("runtime")
                if rt:
                    chat_session_id = getattr(rt, "_session_id", None)
        if conv:
            chat_provider, chat_model = _s.runtime_management._resolve_session_provider_model(conv)
        elif _s._user_pinned_provider and _s._user_pinned_model:
            chat_provider, chat_model = _s._user_pinned_provider, _s._user_pinned_model
        else:
            chat_provider, chat_model = _s.runtime_management._last_used_chat_model()

        # Gate on the user-enabled set — the same source the model picker
        # reads — so a model disabled in Settings is never advertised.
        _rm = _s.runtime_management
        if not _rm._default_is_enabled(chat_provider, chat_model):
            chat_provider, chat_model = None, None
        exec_provider = _rm._exec_provider
        exec_model = _rm._exec_model
        if not _rm._default_is_enabled(exec_provider, exec_model):
            exec_provider, exec_model = None, None

        from openprogram.models.providers.settings.fast import fast_capability

        return JSONResponse(content={
            "chat": {
                "provider": chat_provider,
                "model": chat_model,
                "session_id": chat_session_id,
                "locked": chat_locked,
                "thinking": _s._get_thinking_config_for_model(chat_provider, chat_model),
                # 当前模型有无 Fast（service_tier）档——composer 据此
                # 显隐"高速"开关，与 thinking 显隐同一模式。
                "fast": _supports_fast(chat_provider, chat_model),
                "fast_capability": fast_capability(chat_provider, chat_model),
            },
            "exec": {
                "provider": exec_provider,
                "model": exec_model,
                "thinking": _s._get_thinking_config_for_model(
                    exec_provider, exec_model,
                ),
            },
            "available": _s.runtime_management._available_providers,
        })

    @app.post("/api/agent_settings")
    async def set_agent_settings(body: dict = None):
        """Update chat and/or exec agent provider/model."""
        from openprogram.interfaces.server import server as _s
        _s._init_providers()
        changed = False

        if body and "chat" in body:
            chat = body["chat"]
            new_provider = chat.get("provider", _s.runtime_management._chat_provider)
            new_model = chat.get("model", _s.runtime_management._chat_model)
            if (new_provider != _s.runtime_management._chat_provider
                    or new_model != _s.runtime_management._chat_model):
                try:
                    await asyncio.to_thread(
                        _s._create_runtime_for_visualizer, new_provider, new_model
                    )
                except Exception as e:
                    return _runtime_build_error_response(e, new_provider)
                _s.runtime_management._chat_provider = new_provider
                _s.runtime_management._chat_model = new_model
                _s._user_pinned_provider = new_provider
                _s._user_pinned_model = new_model
                from openprogram.models.providers.catalog.last_used import record_last_used_model
                await asyncio.to_thread(record_last_used_model, new_provider, new_model)
                changed = True

        if body and "exec" in body:
            exec_cfg = body["exec"]
            _s.runtime_management._exec_provider = exec_cfg.get(
                "provider", _s.runtime_management._exec_provider
            )
            _s.runtime_management._exec_model = exec_cfg.get(
                "model", _s.runtime_management._exec_model
            )
            changed = True

        if changed:
            emit_ws_frame({
                "type": "agent_settings_changed",
                "data": {
                    "chat": {"provider": _s.runtime_management._chat_provider,
                             "model": _s.runtime_management._chat_model},
                    "exec": {"provider": _s.runtime_management._exec_provider,
                             "model": _s.runtime_management._exec_model},
                },
            })


        return JSONResponse(content={
            "chat": {"provider": _s.runtime_management._chat_provider,
                     "model": _s.runtime_management._chat_model},
            "exec": {"provider": _s.runtime_management._exec_provider,
                     "model": _s.runtime_management._exec_model},
        })
