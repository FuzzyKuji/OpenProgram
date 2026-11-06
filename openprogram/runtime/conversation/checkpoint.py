"""Resumable Agent loop input built on the durable Agent checkpoint.

The checkpoint payload, its codec and the runtime-contract check live in
``openprogram.runtime.execution.agent_checkpoint``, where the control plane
decodes them. This module holds the engine side: the runtime contract
snapshot taken from live tools and the turn request, and the continuation
that turns a checkpoint back into provider messages for a fresh attempt.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from types import CodeType
from typing import Any, Mapping, TYPE_CHECKING

from openprogram.models.providers.types import AssistantMessage, ToolResultMessage
from openprogram.runtime.execution.agent_checkpoint import (
    RUNTIME_CONTRACT_VERSION,
    AgentCheckpointError,
    AgentCheckpointV1,
    _json_safe,
    decode_turn_display,
    validate_runtime_contract,
)

if TYPE_CHECKING:
    from openprogram.runtime.execution.checkpoints import CheckpointManifest
    from openprogram.runtime.execution.store import ExecutionStore
    from openprogram.runtime.agent.turn_request import TurnRequest


def provider_context_from_effect(
    continuation: "AgentContinuation",
    store: Any,
) -> list[Any] | None:
    """Recover the exact pre-provider message context when it was saved.

    A continuation checkpoint identifies the provider action, while the
    corresponding effect retains the provider payload. Reuse it only when
    both identities match the checkpoint; older checkpoints fall back to
    graph rendering in the dispatcher.
    """
    action_id = continuation.provider_action_id
    execution_id = continuation.checkpoint.execution_id
    if not action_id or not execution_id:
        return None
    from openprogram.runtime.execution.effects import EffectStore, EffectStatus

    if not callable(getattr(store, "_connect", None)):
        return None
    effect = EffectStore(store).get(f"effect_{action_id[:32]}")
    if (
        effect is None
        or effect.execution_id != execution_id
        or effect.action_id != action_id
        or effect.metadata.get("kind") != "provider.before"
        or effect.status is not EffectStatus.COMMITTED
    ):
        return None
    metadata = effect.metadata
    payload = metadata.get("payload") if isinstance(metadata, Mapping) else None
    context = payload.get("context") if isinstance(payload, Mapping) else None
    values = context.get("messages") if isinstance(context, Mapping) else None
    if not isinstance(values, list):
        return None
    from openprogram.models.providers.types import UserMessage

    result: list[Any] = []
    for value in values:
        if not isinstance(value, Mapping):
            return None
        role = value.get("role")
        try:
            if role == "user":
                result.append(UserMessage.model_validate(value))
            elif role == "assistant":
                result.append(AssistantMessage.model_validate(value))
            elif role == "toolResult":
                result.append(ToolResultMessage.model_validate(value))
            else:
                return None
        except Exception:
            return None
    return result


def _code_material(value: Any) -> bytes:
    """What a code object does, in bytes that depend on nothing else.

    ``marshal.dumps`` is not that: it marks objects shared by reference only
    when something else holds them too, so the same function hashes
    differently as the process runs, and sets come out in hash-seed order.
    A continuation compared those bytes and refused tools that had not
    changed. Source location (file name, line numbers) is left out as well;
    moving a function does not change what it does.
    """
    if isinstance(value, CodeType):
        parts = [
            b"code", value.co_code,
            *(str(getattr(value, name)).encode() for name in (
                "co_argcount", "co_posonlyargcount", "co_kwonlyargcount",
                "co_flags", "co_names", "co_varnames", "co_freevars", "co_cellvars",
            )),
            *(_code_material(item) for item in value.co_consts),
        ]
    elif isinstance(value, (tuple, list)):
        parts = [type(value).__name__.encode(), *(_code_material(item) for item in value)]
    elif isinstance(value, (frozenset, set)):
        parts = [b"set", *sorted(_code_material(item) for item in value)]
    else:
        parts = [type(value).__name__.encode(), repr(value).encode("utf-8", "surrogatepass")]
    return b"".join(hashlib.sha256(part).digest() for part in parts)


def _callable_descriptor(value: Any) -> dict[str, str] | None:
    if not callable(value):
        return None
    code = getattr(value, "__code__", None)
    module = getattr(value, "__module__", None)
    qualname = getattr(value, "__qualname__", None)
    if not isinstance(code, CodeType) or not isinstance(module, str) or not isinstance(qualname, str):
        return None
    return {
        "module": module,
        "qualname": qualname,
        "code_sha256": hashlib.sha256(_code_material(code)).hexdigest(),
    }


def _implementation_descriptor(tool: Any) -> dict[str, Any] | None:
    declared = getattr(tool, "_runtime_implementation", None)
    if isinstance(declared, Mapping):
        value = _json_safe(declared)
        return value if isinstance(value, dict) else None
    return _callable_descriptor(getattr(tool, "execute", None))


def runtime_contract_snapshot(
    *,
    model: Any,
    system_prompt: str,
    tools: list[Any] | tuple[Any, ...] | None,
    request: Any,
    structured_output: Any = None,
    toolset: Any = None,
) -> dict[str, Any]:
    """Build the immutable runtime contract used by continuation activation."""
    tool_values: list[dict[str, Any]] = []
    for tool in tools or ():
        implementation = _implementation_descriptor(tool)
        approval = getattr(tool, "_requires_approval", None)
        approval_value = approval if isinstance(approval, bool) or approval is None else _callable_descriptor(approval)
        if implementation is None:
            implementation_value = None
        else:
            implementation_value = implementation
        tool_values.append({
            "name": getattr(tool, "name", None),
            "description": getattr(tool, "description", None),
            "parameters": _json_safe(getattr(tool, "parameters", None)),
            "cache_control": _json_safe(getattr(tool, "cache_control", None)),
            "permission": {
                "mode": getattr(request, "permission_mode", None),
                "rules": _json_safe(getattr(request, "permission_rules", None)),
            },
            "approval": {
                "requires": approval_value,
                "accept_edits_safe": bool(getattr(tool, "_accept_edits_safe", False)),
            },
            "implementation": implementation_value,
        })
    request_semantics = {
        key: _json_safe(getattr(request, key, None))
        for key in (
            "thinking_effort", "service_tier", "tools_override", "response_format",
            "structured_output", "structured_output_mode", "structured_output_attempt",
            "additional_working_dirs", "_execution_revision_id",
        )
    }
    from openprogram.runtime.conversation.workdir import runtime_location_for
    request_semantics["execution_location"] = runtime_location_for(
        getattr(request, "session_id", ""),
    )
    model_value = _json_safe(model)
    if isinstance(model_value, dict) and "endpoint" not in model_value:
        model_value["endpoint"] = model_value.get("base_url")
    return {
        "contract_version": RUNTIME_CONTRACT_VERSION,
        "model": model_value,
        "system_prompt": system_prompt,
        "tools": tool_values,
        "structured_output": _json_safe(structured_output),
        "toolset": _json_safe(toolset),
        "request_semantics": request_semantics,
    }


@dataclass(frozen=True)
class AgentContinuation:
    """A fresh-attempt carrier reconstructed solely from a checkpoint."""

    request: "TurnRequest"
    checkpoint: "CheckpointManifest"
    state: AgentCheckpointV1
    assistant_message: AssistantMessage
    tool_results: tuple[ToolResultMessage, ...]
    resolved_snapshot: Mapping[str, Any]
    display: tuple[dict[str, Any], ...] = ()
    execution_store: Any = field(default=None, repr=False, compare=False)

    @classmethod
    def from_checkpoint(
        cls, *, store: "ExecutionStore", checkpoint: "CheckpointManifest", request: "TurnRequest"
    ) -> "AgentContinuation":
        state = AgentCheckpointV1.load(store, checkpoint)
        payload = state.payload
        turn = payload["turn"]
        if request.user_msg_id and request.user_msg_id != turn["user_message_id"]:
            raise AgentCheckpointError("checkpoint_schema_invalid", "continuation request has a different user anchor")
        request.user_msg_id = turn["user_message_id"]
        assistant_data = state.read_json_ref(
            store, checkpoint.execution_id, payload["assistant_message_delta_ref"]
        )
        try:
            assistant = AssistantMessage.model_validate(assistant_data)
            results = tuple(
                ToolResultMessage.model_validate(
                    state.read_json_ref(store, checkpoint.execution_id, descriptor)
                )
                for descriptor in payload["tool_result_delta_refs"]
            )
        except Exception as exc:
            raise AgentCheckpointError("checkpoint_schema_invalid", "checkpoint message delta is invalid") from exc
        tool_call_ids = [item.id for item in assistant.content if getattr(item, "type", None) == "toolCall"]
        if tool_call_ids != payload["current_decision"]["tool_call_ids"]:
            raise AgentCheckpointError("checkpoint_schema_invalid", "checkpoint decision tool calls differ from assistant delta")
        snapshot = state.read_json_ref(
            store, checkpoint.execution_id, payload["resolved_model_system_tool_snapshot_ref"]
        )
        if (
            not isinstance(snapshot, Mapping)
            or not isinstance(snapshot.get("model"), Mapping)
            or not isinstance(snapshot["model"].get("id"), str)
            or not snapshot["model"]["id"]
            or not isinstance(snapshot.get("system_prompt"), str)
            or not isinstance(snapshot.get("tools"), list)
        ):
            raise AgentCheckpointError("checkpoint_schema_invalid", "resolved snapshot is invalid")
        validate_runtime_contract(snapshot, snapshot)
        display_blocks = decode_turn_display(
            state, store=store, execution_id=checkpoint.execution_id,
        )
        return cls(
            request=request,
            checkpoint=checkpoint,
            state=state,
            assistant_message=assistant,
            tool_results=results,
            resolved_snapshot=dict(snapshot),
            display=tuple(dict(card) for card in display_blocks),
            execution_store=store,
        )

    @property
    def phase(self) -> str:
        return str(self.state.payload["safe_point"]["phase"])

    @property
    def assistant_message_id(self) -> str:
        return str(self.state.payload["turn"]["assistant_message_id"])

    @property
    def provider_action_id(self) -> str:
        return str(self.state.payload["current_decision"]["provider_action_id"])

    @property
    def next_tool_index(self) -> int:
        return int(self.state.payload["next_tool_index"])

    @property
    def repeat_failures(self) -> dict[str, int]:
        return dict(self.state.payload["repeat_failures"])
