"""Turn-scoped context bindings — pipeline step 3 (dispatcher-split).

Attach Runtime and Context to the session's GraphStore. Agent methods,
managed source functions and legacy entries record into the same DAG.
The ``_current_runtime`` ContextVar shares the Runtime with nested calls.

``TurnBindings.bind`` sets every per-turn ContextVar (session id, turn
id, worktree cwd, GraphStore, DAG runtime), installs the session-scoped
deferred-tool set and optionally snapshots the project auto-commit baseline.
``release`` resets the tokens — the caller runs it in a ``finally`` so
success, exception and early-return paths all unwind identically.
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from openprogram.runtime.execution.run_control import (
    get_current_execution_id as _get_execution_id,
    get_current_session_id as _get_session_id,
    reset_current_execution_id as _reset_execution_id,
    reset_current_session_id as _reset_session_id,
    set_current_execution_id as _set_execution_id,
    set_current_session_id as _set_session_id,
)

if TYPE_CHECKING:
    from openprogram.runtime.agent.turn_request import TurnRequest

_log = logging.getLogger(__name__)


def _unavailable_runtime(error, *, model: str = "unavailable", provider=None):
    """Defer model setup failure while retaining non-model Runtime APIs."""
    from openprogram.runtime.agent.runtime import Runtime

    class UnavailableRuntime(Runtime):
        def exec(self, *args, **kwargs):
            raise self.setup_error

        async def async_exec(self, *args, **kwargs):
            raise self.setup_error

    unavailable = UnavailableRuntime(model="unavailable")
    unavailable.model = model
    unavailable.setup_error = error
    unavailable.provider_id = provider
    return unavailable


class TurnBindings:
    """Holds the ContextVar tokens for one turn, plus the project baseline."""

    def __init__(self) -> None:
        self.project_baseline = None
        self._runtime_token = None
        self._context_binding = None
        self._call_id_token = None
        self._store_token = None
        self._turn_id_token = None
        self._worktree_token = None
        self._session_id_token = None
        self._turn_request_token = None
        self._render_range_token = None
        self._surface_token = None
        self._web_use_owner_id = None
        self._sandbox_token = None
        self._environment_token = None
        self._req_session_id: Optional[str] = None
        self._execution_id_token = None
        self._deferred_token = None
        self._frozen_tools_token = None
        self._open_applications_token = None
        self._deferred_names = set()
        self._deferred_writer = None
        self._assistant_msg_id = None
        self._request = None

    @classmethod
    def bind(
        cls,
        *,
        req: "TurnRequest",
        assistant_msg_id: str,
        db,
        snapshot_project_baseline: bool = True,
    ) -> "TurnBindings":
        self = cls()
        self._req_session_id = req.session_id
        self._request = req
        # Restore only the selected predecessor branch, never another session
        # or a sibling execution. Names cannot widen the resolved tool policy.
        for message in reversed(db.get_branch(req.session_id, req.user_msg_id or None)):
            names = message.get("loaded_deferred_tools")
            if (message.get("role") == "assistant" and isinstance(names, list)
                    and all(isinstance(name, str) for name in names)):
                self._deferred_names.update(names)
                break
        # A normal foreground turn has no outer execution owner. Bind its
        # assistant reply id so every question emitted during this turn is
        # cancellable by exact execution identity. An outer job/subprocess
        # already owns the context and must remain authoritative.
        if not _get_execution_id():
            self._execution_id_token = _set_execution_id(assistant_msg_id)
        # Critical: we use ``create_runtime`` with the chat's selected model
        # (real provider) instead
        # of a stub. Agent method's _inject_runtime would otherwise
        # pick up our stub and any ``runtime.exec`` inside the function
        # body would return whatever the stub's ``call`` does (a fixed
        # string or empty) rather than actually calling an LLM. If
        # runtime construction fails, internal model calls retain that
        # error rather than auto-detecting a different provider.
        from openprogram.state.store import (
            SessionNodeWriter as _GraphStore,
            _store as _store_var,
            _current_turn_id as _turn_id_var,
        )
        from openprogram.runtime.agent.call_state import (
            _current_runtime as _current_runtime_var,
            _render_range_override as _render_range_var,
        )
        # Tag this turn so file-mutating tools can attribute backups to
        # the right assistant message via checkpoint.helpers.
        self._turn_id_token = _turn_id_var.set(assistant_msg_id)
        # The execution context an inner AgentSession inherits. A program
        # spawned from this turn derives its own request from this one, so
        # its tools carry the same authority, source and permission mode
        # rather than running ungated (see turn_request_context).
        from openprogram.runtime.agent.turn_request import set_turn_request
        self._turn_request_token = set_turn_request(req)
        # The session half of the pair every collaboration tool reads
        # (agent, send_message, todo, worktree_*, read_conversation).
        # Their error text already promises "the dispatcher sets the
        # session + turn ContextVars on entry", and until now only the
        # turn half was true here: the session id was bound by whichever
        # entry point happened to run the turn. A new thread starts with
        # empty ContextVars, so the paths that call process_user_turn off
        # their own thread (the job runner's follow-up, merge, the CLI
        # /goal turn) left it unbound and every one of those tools failed
        # with "no active parent turn".
        #
        # Fill in only when nothing is bound. An entry point that binds
        # the id for a scope WIDER than the turn (webui exec thread, task
        # runner worker, channel adapter) stays in charge of it, so a
        # nested turn for another session cannot repoint the cancel hook
        # or runtime.ask at a session that registered no turn token.
        if _get_session_id() is None:
            self._session_id_token = _set_session_id(req.session_id)
        # Bind the session's active agent worktree (if any) to the
        # _current_worktree_path ContextVar for the duration of this turn.
        # bash / edit / write / read consult that var to default their cwd
        # to the worktree root. The binding is per-turn so a worktree
        # created mid-turn is picked up by the next turn entry — within
        # the same turn the tool that ran worktree_create also calls
        # set_worktree explicitly so the rest of that turn sees it.
        # Bind the session's environment (local / ssh / docker) so every
        # tool in this turn runs where the conversation was created to
        # run. A removed environment binds nothing: the backend lookup
        # then reports it instead of silently running locally.
        _env = None
        try:
            from openprogram.host.environments import (
                EnvironmentError as _EnvError,
                bind_turn_environment,
                resolve_for_session,
            )
            try:
                _env = resolve_for_session(req.session_id)
            except _EnvError:
                _env = None
            if _env is not None:
                self._environment_token = bind_turn_environment(_env)
        except Exception:
            self._environment_token = None
        try:
            from openprogram.state.worktree.context import set_worktree as _set_wt
            from openprogram.state.worktree.manager import get_manager as _get_wt_mgr
            _wt_mgr = _get_wt_mgr()
            _active_wt = _wt_mgr.find_active_for_session(req.session_id)
            if _env is not None and _env.kind == "ssh":
                # An SSH conversation's files live on the remote host:
                # its tools start in the environment's remote folder,
                # never in a local project path.
                from openprogram.host.environments.remote import remote_workdir
                self._worktree_token = _set_wt(remote_workdir(_env))
            elif _active_wt is not None:
                self._worktree_token = _set_wt(_active_wt.worktree_path)
            else:
                # No explicit worktree → default this turn's tool cwd to the
                # session's bound (non-default) project path. Resolved fresh
                # every turn, so a mid-chat set_session_project takes effect
                # on the next turn without moving the session repo.
                from openprogram.runtime.conversation.workdir import project_workdir_for
                _proj_wd = project_workdir_for(req.session_id)
                if _proj_wd is not None:
                    self._worktree_token = _set_wt(str(_proj_wd))
        except Exception:
            self._worktree_token = None
        # Layer 6 (Claude Code's shouldDefer / ToolSearch): install a
        # session-scoped "loaded deferred tools" set so tool_search can
        # mutate it and subsequent turns see the updated set.
        from openprogram.programs._host import runtime as tool_runtime
        self._deferred_token = tool_runtime.install_loaded_deferred(self._deferred_names)
        self._frozen_tools_token = tool_runtime._frozen_turn_tools.set(None)
        # Exposure tiers: an application open in a window for this session
        # has its deferred entries resident for the session's requests.
        try:
            from openprogram.programs._host.ui.bindings import open_application_ids
            open_ids = open_application_ids(req.session_id)
        except Exception:
            _log.debug("could not read the session's open applications", exc_info=True)
            open_ids = set()
        self._open_applications_token = tool_runtime.install_open_applications(open_ids)
        self._deferred_writer = _GraphStore(db, req.session_id)
        self._assistant_msg_id = assistant_msg_id

        # Project auto-commit (entity layer): snapshot which paths are
        # already dirty in the session's bound project BEFORE the agent
        # touches anything, so the turn-end commit can tell the user's
        # uncommitted work apart from the agent's edits (Strategy A). None
        # when disabled / ad-hoc session. Best-effort — never blocks a turn.
        # Continuation must not re-snapshot: auto-init can commit a
        # not-yet-git project, and a second snapshot treats post-pause
        # agent dirt as the user's.
        if snapshot_project_baseline:
            try:
                from openprogram.state.store.project import project_commit as _pc
                self.project_baseline = _pc.snapshot_baseline(req.session_id)
            except Exception:
                self.project_baseline = None
        else:
            self.project_baseline = None
        # Expose the GraphStore via ContextVar so deep code (Runtime.exec,
        # ask_user, Agent method decorator, and the file-checkpoint
        # helper behind write/edit/apply_patch) writes land in the same DAG
        # without threading the store through every layer.
        #
        # Bound BEFORE — and independently of — the DAG runtime below. It
        # used to live inside that try, so a create_runtime() failure (no
        # provider configured, or an exhausted auth pool, which is routine
        # when the chat runtime is a different provider entirely) left
        # _store unbound for the whole turn. checkpoint_before_edit needs
        # _store AND _current_turn_id, so it silently no-op'd: no
        # file_backups/, hence no per-turn file list, no diff, no undo.
        # The store needs a session, not a provider — so it binds regardless.
        from openprogram.runtime.context import Context
        ambient = Context.current()
        writer = (ambient.store if ambient is not None and ambient.store is not None
                  else _GraphStore(db, req.session_id))
        self._store_token = _store_var.set(writer)
        from openprogram.runtime.context.scope import _call_id
        self._call_id_token = _call_id.set(assistant_msg_id)
        active = (ambient if ambient is not None else Context()).derive(
            store=writer, call_id=assistant_msg_id)
        self._context_binding = active.bind()
        self._context_binding.__enter__()
        model = None
        try:
            from openprogram.runtime.agent.runtime.factory import create_runtime as _create_rt
            from openprogram.runtime.conversation import turn_runtime as dispatcher
            from openprogram.runtime.conversation.session_model import (
                ensure_session_chat_model, read_session_chat_model, override_string,
            )

            profile = (req.profile_snapshot if req.profile_snapshot is not None
                       else dispatcher._load_agent_profile(req.agent_id))
            override = req.model_override
            if not override:
                if req.profile_snapshot is not None:
                    provider, model_id = read_session_chat_model(req.session_id)
                else:
                    provider, model_id = ensure_session_chat_model(
                        req.session_id, req.agent_id,
                    )
                override = override_string(provider, model_id)
                if override:
                    req.model_override = override
            # Nested model calls must honour the same selection as the chat
            # loop, not auto-detect a separately authenticated default provider.
            model = dispatcher._resolve_model(profile, override)
            req.model_override = f"{model.provider}/{model.id}"
            _dag_runtime = _create_rt(provider=model.provider, model=model.id)
            self._runtime_token = _current_runtime_var.set(_dag_runtime)
        except Exception as exc:
            # Preserve the setup error until an internal model call needs it.
            # Leaving this unbound would select an unrelated global provider,
            # or inherit another turn's runtime. Non-model tools still work.
            # Runtime parses colons in constructor model strings. Tagged
            # local models must not trigger a second provider lookup here.
            unavailable = _unavailable_runtime(
                exc, model=req.model_override or "unavailable",
                provider=model.provider if model is not None else None,
            )
            self._runtime_token = _current_runtime_var.set(unavailable)
            _log.debug("nested runtime unavailable for selected turn model", exc_info=True)
        self._render_range_token = _render_range_var.set(req.render_range)
        from openprogram.runtime.conversation.surface_context import bind as _bind_surface
        self._surface_token = _bind_surface(req.surface_context)
        from openprogram.runtime.conversation.surface_context import web_use_owner_id
        self._web_use_owner_id = web_use_owner_id(req.surface_context)
        # Freeze the effective SandboxPolicy for this turn. Nested
        # (subagent) binds inherit and cannot relax the parent snapshot.
        try:
            from openprogram.runtime.conversation.session_config import (
                load_session_run_config,
                sandbox_override_from_config,
            )
            from openprogram.host.sandbox import bind_turn_policy
            _cfg = load_session_run_config(req.session_id)
            # The host sandbox governs host paths only. An SSH or Docker
            # environment is its own boundary, so it runs unsandboxed.
            self._sandbox_token = bind_turn_policy(
                False if _env is not None and not _env.is_local
                else sandbox_override_from_config(_cfg, req.session_id),
            )
        except Exception:
            self._sandbox_token = None
        return self

    def release(self, *, suspended: bool = False) -> None:
        """Reset every ContextVar bound by :meth:`bind`.

        ``suspended`` means the execution handed off at a durable wait (an
        approval) and resumes in a new frame of the same turn, so its Web
        Use sessions are kept for that frame instead of released.

        Guarded because attach may have silently failed (no provider
        configured). ValueError is what ContextVar.reset raises when the
        token came from a different context — the only failure worth
        tolerating here.
        """
        from openprogram.state.store import (
            _store as _store_var,
            _current_turn_id as _turn_id_var,
        )
        from openprogram.runtime.agent.call_state import (
            _current_runtime as _current_runtime_var,
            _render_range_override as _render_range_var,
        )
        try:
            if self._request is not None:
                self._request._loaded_deferred_tools = sorted(self._deferred_names)
            if self._deferred_writer is not None and self._assistant_msg_id:
                try:
                    self._deferred_writer.update(
                        self._assistant_msg_id,
                        loaded_deferred_tools=sorted(self._deferred_names),
                    )
                except Exception:
                    _log.warning("could not persist deferred discoveries", exc_info=True)
            from openprogram.programs._host import runtime as tool_runtime
            if self._deferred_token is not None:
                tool_runtime._loaded_deferred.reset(self._deferred_token)
            if self._frozen_tools_token is not None:
                tool_runtime._frozen_turn_tools.reset(self._frozen_tools_token)
            if self._open_applications_token is not None:
                tool_runtime._open_applications.reset(self._open_applications_token)
            if self._web_use_owner_id is not None:
                from openprogram.programs._host import services as _services
                browser = _services.lookup("browser")
                if browser is None:
                    pass
                elif suspended:
                    browser.park_owner(self._web_use_owner_id)
                else:
                    browser.release_owner(self._web_use_owner_id)
            if self._surface_token is not None:
                from openprogram.runtime.conversation.surface_context import (
                    current as _current_surface,
                    release_bindings as _release_surface_bindings,
                    reset as _reset_surface,
                )
                _release_surface_bindings(_current_surface())
                _reset_surface(self._surface_token)
            if self._context_binding is not None:
                self._context_binding.__exit__(None, None, None)
                self._context_binding = None
            if self._call_id_token is not None:
                from openprogram.runtime.context.scope import _call_id
                _call_id.reset(self._call_id_token)
                self._call_id_token = None
            if self._runtime_token is not None:
                _current_runtime_var.reset(self._runtime_token)
            if self._store_token is not None:
                _store_var.reset(self._store_token)
            if self._turn_id_token is not None:
                _turn_id_var.reset(self._turn_id_token)
            if self._turn_request_token is not None:
                from openprogram.runtime.agent.turn_request import reset_turn_request
                reset_turn_request(self._turn_request_token)
            if self._render_range_token is not None:
                _render_range_var.reset(self._render_range_token)
            if self._session_id_token is not None:
                _reset_session_id(self._session_id_token)
            if self._execution_id_token is not None:
                _reset_execution_id(self._execution_id_token)
            if self._worktree_token is not None:
                from openprogram.state.worktree.context import reset_worktree
                reset_worktree(self._worktree_token)
            if self._sandbox_token is not None:
                from openprogram.host.sandbox import reset_turn_policy
                reset_turn_policy(self._sandbox_token)
            if self._environment_token is not None:
                from openprogram.host.environments import reset_turn_environment
                reset_turn_environment(self._environment_token)
        except ValueError:
            _log.debug(
                "context var teardown ran in a foreign context for session %s",
                self._req_session_id, exc_info=True,
            )
