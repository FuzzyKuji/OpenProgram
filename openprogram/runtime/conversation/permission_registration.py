"""The session and turn facts the permission package reads.

``openprogram.runtime.permissions`` sits below conversations and never
imports them; it asks :func:`openprogram.runtime.permissions.session_facts.facts`
instead. On import, this package registers the implementation below, which
answers from run control, plan mode, session settings, surface context,
the Agent registry and the session's chat model. Each answer looks its
source up when asked, so a test that patches the source sees its patch.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from openprogram.runtime.permissions.session_facts import SessionFacts, register


class ConversationSessionFacts(SessionFacts):
    def current_session_id(self) -> str | None:
        from openprogram.runtime.execution.run_control import get_current_session_id
        return get_current_session_id()

    def current_execution_id(self) -> str | None:
        from openprogram.runtime.execution.run_control import get_current_execution_id
        return get_current_execution_id()

    @contextmanager
    def bind_execution(self, execution_id: str | None) -> Iterator[None]:
        from openprogram.runtime.execution.run_control import (
            reset_current_execution_id,
            set_current_execution_id,
        )
        token = set_current_execution_id(execution_id)
        try:
            yield
        finally:
            reset_current_execution_id(token)

    def preapproved_wait_id(self) -> str | None:
        from openprogram.runtime.conversation.run_control import get_preapproved_wait_id
        return get_preapproved_wait_id()

    def turn_running(self, session_id: str, execution_id: str | None) -> bool:
        from openprogram.runtime.execution.run_control import current_token
        return current_token(session_id, execution_id=execution_id) is not None

    def in_plan_mode(self, session_id: str | None) -> bool:
        from openprogram.runtime.conversation import plan_mode
        return plan_mode.is_plan_mode(session_id)

    def project_defaults(self, session_id: str) -> dict:
        from openprogram.runtime.conversation import session_config
        return session_config.project_defaults(session_id)

    def session_rules(self, session_id: str):
        from openprogram.runtime.conversation import session_config
        return session_config.load_session_run_config(session_id).permission_rules

    def save_session_rules(self, session_id: str, agent_id: Any, rules: dict) -> None:
        from openprogram.runtime.conversation import session_config
        session_config.save_session_run_config(
            session_id, agent_id=agent_id, permission_rules=rules,
        )

    def turn_request_for(self, store, execution) -> Any:
        from openprogram.runtime.conversation.production_driver import AgentActivationService
        resolver = AgentActivationService(
            lambda record: store.get_agent_turn_input(record.execution_id)
        )
        return resolver.build_request(execution, None)

    def web_use_available(self, surface_context: dict | None) -> bool:
        from openprogram.runtime.conversation import surface_context as surfaces
        return surfaces.web_use_available(surface_context)

    def holds_outbound(self, agent_id: str) -> bool:
        from openprogram.runtime.agent_registry import manager
        spec = manager.get(agent_id)
        return spec is None or getattr(spec, "hold_outbound", True) is not False

    def session_chat_model(self, session_id: str | None) -> tuple[Any, Any]:
        from openprogram.runtime.conversation import session_model
        return session_model.read_session_chat_model(session_id)

    def resolve_model(self, spec: str) -> Any:
        from openprogram.runtime.conversation import model_tools
        return model_tools.resolve_model({}, spec)


register(ConversationSessionFacts())
