"""AgentProductionDriver safe points operations."""
from __future__ import annotations
from openprogram.runtime.conversation.checkpoint import AgentContinuation
import time
from openprogram.runtime.conversation.production_driver import shared
from openprogram.runtime.execution.attempts import AttemptRecord
from openprogram.runtime.execution.agent_checkpoint import (
    AgentCheckpointError,
    AgentCheckpointV1,
    canonical_json_bytes,
    decode_turn_display,
)
from openprogram.runtime.execution.model import CommandStatus
from openprogram.runtime.execution.model import ExecutionStatus


def _digest(*parts: str) -> str:
    """Hash identity parts into a stable action identifier."""
    value = "\x1f".join(parts).encode("utf-8")
    return shared.hashlib.sha256(value).hexdigest()


def _json_digest(value: shared.Any) -> str:
    """Hash a JSON value by its canonical bytes."""
    return shared.hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _interrupt_cancelled() -> None:
    """Interrupt the Agent loop because the execution is cancelling."""
    from openprogram.models.providers.utils.errors import ExecInterrupt
    raise ExecInterrupt("cancelled")


class _AgentSafePointHook:
    """One attempt's resume cursor plus the callable the Agent loop invokes."""

    def __init__(
        self,
        driver: shared.Any,
        attempt: AttemptRecord,
        request: shared.Any,
        cancel_event: shared.threading.Event,
        continuation: AgentContinuation | None,
        steer_queue: list[dict[str, shared.Any]] | None,
        steer_consumed_ids: set[str] | None,
    ) -> None:
        self.driver = driver
        self.attempt = attempt
        self.request = request
        self.cancel_event = cancel_event
        self.continuation = continuation
        self.steer_queue = steer_queue
        self.steer_consumed_ids = steer_consumed_ids
        self.pending: dict[
            str, tuple[str, str, str, str | None, tuple[dict[str, shared.Any], ...]]
        ] = {}
        self.prior_actions: list[dict[str, shared.Any]] = []
        self.prior_receipts: list[dict[str, shared.Any]] = []
        self.completed_tool_results: list[dict[str, shared.Any]] = []
        self.decision_action_ids: set[str] = set()
        self.display_blocks: list[dict[str, shared.Any]] = []
        self.provider_action_id = ""
        self.provider_effect_id = ""
        self.provider_input_hash = ""
        self.provider_terminal_receipt: dict[str, shared.Any] | None = None
        self.latest_assistant: dict[str, shared.Any] | None = None
        self.latest_snapshot: dict[str, shared.Any] = {}
        self.last_checkpoint_inputs = None
        if continuation is not None:
            self._restore_cursor(continuation)

    # -- resume cursor -------------------------------------------------

    def _restore_cursor(self, continuation: AgentContinuation) -> None:
        """Reload the committed decision, receipts and display from a checkpoint."""
        for item in continuation.state.payload["completed_actions"]:
            action = dict(item)
            action["result"] = continuation.state.read_json_ref(
                self.driver.executions, continuation.checkpoint.execution_id, action["result_ref"],
            )
            self.prior_actions.append(action)
        for item in continuation.state.payload["terminal_effect_receipts"]:
            receipt = dict(item)
            receipt_ref = receipt.pop("receipt_ref", None)
            if not isinstance(receipt_ref, shared.Mapping):
                raise shared.AgentDriverError("checkpoint_schema_invalid", "terminal receipt ref is missing")
            try:
                receipt["receipt"] = continuation.state.read_json_ref(
                    self.driver.executions, continuation.checkpoint.execution_id, receipt_ref,
                )
            except AgentCheckpointError as exc:
                raise shared.AgentDriverError(exc.code, str(exc)) from exc
            self.prior_receipts.append(receipt)
        self.completed_tool_results = [item.model_dump(mode="json") for item in continuation.tool_results]
        self.provider_action_id = continuation.provider_action_id
        self.latest_assistant = continuation.assistant_message.model_dump(mode="json")
        self.latest_snapshot = dict(continuation.resolved_snapshot)
        self.decision_action_ids.update(
            str(item.get("action_id"))
            for item in (*self.prior_actions, *self.prior_receipts)
            if isinstance(item.get("action_id"), str) and item["action_id"]
        )
        self.display_blocks.extend(
            decode_turn_display(
                continuation.state,
                store=self.driver.executions,
                execution_id=continuation.checkpoint.execution_id,
            )
        )
        for action in self.prior_actions:
            if action.get("action_id") == self.provider_action_id:
                candidate_hash = action.get("input_hash")
                if isinstance(candidate_hash, str):
                    self.provider_input_hash = candidate_hash
                break
        for receipt in self.prior_receipts:
            if receipt.get("action_id") == self.provider_action_id:
                candidate_effect = receipt.get("effect_id")
                candidate_receipt = receipt.get("receipt")
                if isinstance(candidate_effect, str):
                    self.provider_effect_id = candidate_effect
                if isinstance(candidate_receipt, shared.Mapping):
                    self.provider_terminal_receipt = dict(candidate_receipt)
                break

    @staticmethod
    def _current_command(service, execution_id: str):
        """Return the open control command that wins at this safe point."""
        from openprogram.runtime.execution.model import CommandKind

        commands = service.executions.list_commands(execution_id)
        priority = (CommandKind.PAUSE, CommandKind.STEP, CommandKind.STEER)
        for kind in priority:
            for command in commands:
                if (
                    command.kind is kind
                    and command.status in {
                        CommandStatus.ACCEPTED,
                        CommandStatus.APPLYING,
                    }
                ):
                    return command
        return None

    # -- checkpoint construction ---------------------------------------

    def _checkpoint_turn(self, payload: shared.Mapping[str, shared.Any]):
        """Resolve the turn's message identities for the checkpoint."""
        execution = self.driver._control_service().executions.get_execution(
            self.attempt.execution_id
        )
        if execution is None:
            raise shared.AgentDriverError("execution_not_found", "execution disappeared at safe point")
        raw_turn = payload.get("turn") if isinstance(payload.get("turn"), shared.Mapping) else {}
        user_message_id = str(
            raw_turn.get("user_message_id")
            or getattr(execution, "user_message_id", None)
            or getattr(self.request, "user_msg_id", "")
            or "durable-user"
        )
        assistant_message_id = str(
            raw_turn.get("assistant_message_id")
            or getattr(execution, "assistant_message_id", None)
            or (self.continuation.assistant_message_id if self.continuation is not None else "")
            or f"{user_message_id}_reply"
        )
        base_history_head_id = str(raw_turn.get("base_history_head_id") or user_message_id)
        return raw_turn, user_message_id, assistant_message_id, base_history_head_id

    def _resume_actions(self, kind: str, action_id: str | None):
        """Select the committed actions and receipts the resume cursor keeps."""
        # The Agent checkpoint is a resume cursor for the current provider
        # decision. Committed historical effects stay in the effect ledger;
        # copying them here overflows the bounded receipt/state-ref caps
        # and prevents pause after a long turn.
        if kind in {"provider.after", "provider.finished"}:
            keep_ids = {item for item in (action_id, self.provider_action_id) if item}
        else:
            keep_ids = set(self.decision_action_ids)
            if self.provider_action_id:
                keep_ids.add(self.provider_action_id)
            if action_id:
                keep_ids.add(action_id)
        action_values: list[dict[str, shared.Any]] = []
        seen_action_ids: set[str] = set()
        for item in self.prior_actions:
            item_id = item.get("action_id")
            if item_id in keep_ids and item_id not in seen_action_ids:
                action_values.append(item)
                seen_action_ids.add(item_id)
        receipt_values: list[dict[str, shared.Any]] = []
        seen_receipt_ids: set[str] = set()
        for item in self.prior_receipts:
            item_id = item.get("action_id")
            if item_id in keep_ids and item_id not in seen_receipt_ids:
                receipt_values.append(item)
                seen_receipt_ids.add(item_id)
        return action_values, seen_action_ids, receipt_values, seen_receipt_ids

    def _checkpoint_inputs(
        self,
        kind: str,
        payload: shared.Mapping[str, shared.Any],
        effect_id: str | None = None,
        action_id: str | None = None,
        input_hash: str | None = None,
        terminal_receipt: shared.Mapping[str, shared.Any] | None = None,
    ) -> dict:
        """Build the AgentCheckpointV1 fields for the safe point being reached."""
        phase = "after_provider" if kind in {"provider.after", "provider.finished", "wait.before_tool", "tool.suspended"} else "after_tool"
        point_kind = (
            "agent.wait.before_tool" if kind == "wait.before_tool" else
            "agent.provider.decision.after" if phase == "after_provider"
            else "agent.tool.action.after"
        )
        raw_turn, user_message_id, assistant_message_id, base_history_head_id = (
            self._checkpoint_turn(payload)
        )
        snapshot = payload.get("resolved_snapshot")
        if not isinstance(snapshot, shared.Mapping):
            snapshot = self.latest_snapshot
        if not isinstance(snapshot, shared.Mapping) or not snapshot:
            raise shared.AgentDriverError("checkpoint_schema_invalid", "Agent safe point has no resolved snapshot")
        latest_assistant = self.latest_assistant
        if latest_assistant is None:
            raise shared.AgentDriverError("checkpoint_schema_invalid", "Agent safe point has no completed assistant message")
        tool_call_ids = [
            str(value) for value in payload.get("tool_call_ids", ())
        ]
        if not tool_call_ids:
            tool_call_ids = [
                str(item.get("id"))
                for item in latest_assistant.get("content", [])
                if isinstance(item, shared.Mapping) and item.get("type") == "toolCall"
            ]
        next_tool_index = payload.get("next_tool_index")
        if not isinstance(next_tool_index, int):
            next_tool_index = 0 if phase == "after_provider" else len(self.completed_tool_results)
        action_values, seen_action_ids, receipt_values, seen_receipt_ids = (
            self._resume_actions(kind, action_id)
        )
        provider_action_id = self.provider_action_id
        if kind == "wait.before_tool":
            if not self.provider_effect_id or not self.provider_input_hash or self.provider_terminal_receipt is None:
                raise shared.AgentDriverError("checkpoint_schema_invalid", "wait has no committed provider decision")
            if not any(item.get("action_id") == provider_action_id for item in action_values):
                action_values.append({"action_id": provider_action_id, "input_hash": self.provider_input_hash, "result": latest_assistant})
                seen_action_ids.add(provider_action_id)
            if not any(item.get("effect_id") == self.provider_effect_id for item in receipt_values):
                receipt_values.append({
                    "effect_id": self.provider_effect_id,
                    "frontier_step_id": f"after_provider:{provider_action_id}",
                    "action_id": provider_action_id,
                    "outcome": "committed",
                    "receipt": dict(self.provider_terminal_receipt),
                })
                seen_receipt_ids.add(provider_action_id)
        if effect_id is not None:
            if action_id is None or input_hash is None or terminal_receipt is None:
                raise shared.AgentDriverError("checkpoint_schema_invalid", "effect safe point is missing a receipt")
            if action_id not in seen_action_ids:
                action_values.append({"action_id": action_id, "input_hash": input_hash, "result": latest_assistant if phase == "after_provider" else self.completed_tool_results[-1]})
            if action_id not in seen_receipt_ids:
                receipt_values.append({
                    "effect_id": effect_id,
                    "frontier_step_id": f"{phase}:{action_id}",
                    "action_id": action_id,
                    "outcome": "committed",
                    "receipt": dict(terminal_receipt),
                })
        pending_commands = [
            command.command_id
            for command in self.driver._control_service().executions.list_commands(self.attempt.execution_id)
            if command.status not in {CommandStatus.APPLIED, CommandStatus.REJECTED}
            and command.command_id not in (self.steer_consumed_ids or ())
        ]
        return dict(
            safe_point={
                "kind": point_kind,
                "step_id": (
                    f"wait:{payload.get('tool_call_id')}"
                    if kind == "wait.before_tool" else f"{phase}:{action_id}"
                ),
                "phase": phase,
                "sentinel": "resume-from-checkpoint",
            },
            frontier=[{
                "step_id": (
                    f"wait:{payload.get('tool_call_id')}"
                    if kind == "wait.before_tool" else f"{phase}:{action_id}"
                ),
                "phase": phase,
                "branch_id": str(raw_turn.get("branch_id") or "main"),
            }],
            turn={
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "base_history_head_id": base_history_head_id,
            },
            assistant_message=latest_assistant,
            tool_results=self.completed_tool_results,
            resolved_snapshot=dict(snapshot),
            provider_action_id=provider_action_id,
            tool_call_ids=tool_call_ids,
            next_tool_index=next_tool_index,
            repeat_failures=dict(payload.get("repeat_failures") or {}),
            completed_actions=action_values,
            terminal_effect_receipts=receipt_values,
            pending_command_ids=pending_commands,
            loaded_deferred_tools=payload.get("loaded_deferred_tools", []),
            turn_display=list(self.display_blocks),
        )

    def _checkpoint_payload(self, *args, **kwargs):
        """Build the checkpoint, reporting schema errors as driver errors."""
        try:
            return AgentCheckpointV1.build(**self._checkpoint_inputs(*args, **kwargs))
        except AgentCheckpointError as exc:
            raise shared.AgentDriverError(exc.code, str(exc)) from exc

    # -- Pausing: stop before new work starts ---------------------------

    def _pause_before_dispatch(self, service):
        """Consume pause at the last completed decision, without starting work."""
        from openprogram.runtime.execution.checkpoints import CheckpointFragment
        from openprogram.runtime.execution.effects import EffectStatus
        from openprogram.runtime.execution.model import CommandKind
        from openprogram.runtime.execution.restart import window_seconds

        attempt = self.attempt
        execution = service.executions.get_execution(attempt.execution_id)
        if execution.status is ExecutionStatus.CANCELLING or self.cancel_event.is_set():
            _interrupt_cancelled()
        if execution.status is not ExecutionStatus.PAUSING:
            return False
        command = self._current_command(service, attempt.execution_id)
        if command is None or command.kind is not CommandKind.PAUSE:
            return False
        # A registered effect can still be undispatched. Settle that intent;
        # its action remains pending in the Agent cursor for the next owner.
        for value in self.pending.values():
            effect = service.effects.get(value[0])
            if effect is not None and effect.status is EffectStatus.PLANNED:
                service.effects.resolve_not_started(
                    effect.effect_id,
                    receipt={"outcome": "not_started", "execution_started": False,
                             "pause_before_dispatch": True},
                    attempt_id=attempt.attempt_id, generation=attempt.generation,
                )
        if self.last_checkpoint_inputs is not None:
            state = AgentCheckpointV1.build(**self.last_checkpoint_inputs)
            for blob in state.blob_payloads.values():
                service.executions.put_state_blob(attempt.execution_id, blob)
            refs = {
                "agent_checkpoint": service.executions.put_state_blob(
                    attempt.execution_id, state.to_bytes()),
                "restart_window_seconds": window_seconds(),
                "agent_checkpoint_v1": {
                    key: state.payload[key]
                    for key in ("safe_point", "frontier", "turn", "current_decision", "next_tool_index")
                },
            }
            fragment = CheckpointFragment(
                safe_point_kind=state.payload["safe_point"]["kind"],
                frontier=tuple(state.payload["frontier"]), state_refs=refs,
            )
        else:
            checkpoint = service.checkpoints.get(execution.checkpoint_head_id)
            if checkpoint is None:
                service.pause_before_first_effect(
                    attempt_id=attempt.attempt_id, generation=attempt.generation,
                    command_id=command.command_id,
                )
                return True
            state = AgentCheckpointV1.load(service.executions, checkpoint)
            fragment = CheckpointFragment(
                safe_point_kind=state.payload["safe_point"]["kind"],
                frontier=checkpoint.frontier, state_refs=checkpoint.state_refs,
                completed_frontier=checkpoint.completed_frontier,
                completed_actions=checkpoint.completed_actions,
                effect_receipts=checkpoint.effect_receipts,
                child_frontier=checkpoint.child_frontier,
            )
        if command.status is CommandStatus.ACCEPTED:
            service.executions.transition_command(
                command.command_id, expected_status=CommandStatus.ACCEPTED,
                target=CommandStatus.APPLYING,
            )
        service.arrive_safe_point(
            attempt_id=attempt.attempt_id, generation=attempt.generation,
            command_id=command.command_id,
            expected_execution_version=execution.status_version, fragment=fragment,
        )
        return True

    # -- Running: observation and dispatch bookkeeping -------------------

    def _observe_provider_poll(self, service, payload) -> bool:
        """Raise on cancel and flag a pending steer while the provider streams."""
        from openprogram.runtime.execution.model import CommandKind

        attempt = self.attempt
        # Observation only: application still occurs at provider.after,
        # after the producer closes and its partial response is saved.
        current = service.executions.get_execution(attempt.execution_id)
        if self.cancel_event.is_set() or (current and current.status is ExecutionStatus.CANCELLING):
            _interrupt_cancelled()
        command = self._current_command(service, attempt.execution_id)
        payload["steer_pending"] = bool(
            current and current.current_attempt_id == attempt.attempt_id
            and current.status is ExecutionStatus.RUNNING
            and command is not None and command.kind is CommandKind.STEER
        )
        return False

    def _mark_tool_started(self, service) -> bool:
        """Mark the tool's planned effect dispatched once it actually starts."""
        from openprogram.runtime.execution.effects import EffectStatus

        pending_tool = self.pending.get("tool")
        if pending_tool is None:
            raise shared.AgentDriverError("effect_state_invalid", "tool start has no durable dispatch intent")
        started = service.effects.get(pending_tool[0])
        if started is None:
            raise shared.AgentDriverError("effect_state_invalid", "tool start has no matching effect")
        if started.status is EffectStatus.PLANNED:
            service.effects.mark_dispatched(
                started.effect_id, expected_status=EffectStatus.PLANNED,
            )
        return False

    @staticmethod
    def _recheck_system_access(payload) -> None:
        """Re-probe system access so a granted permission opens no wait."""
        from openprogram.host.system_access import access_manifest_for_tool
        # The manifest was captured while building the tool list;
        # re-probe at the canonical boundary before opening or
        # reusing a wait so a grant race does not suspend a task
        # after access is already available. When access has
        # arrived there is no wait, and the tool goes on to the
        # ordinary dispatch bookkeeping below (tool.started looks
        # its intent up there).
        payload["pre_wait"] = access_manifest_for_tool(
            str(payload.get("tool_name") or ""),
            dict(payload.get("arguments") or {}),
        )

    # -- Waiting: durable question or approval before a tool --------------

    def _wait_identity(self, payload, pre_wait):
        """Derive the wait's kind and stable id, and look up an existing record."""
        from openprogram.runtime.execution.waits import DurableWaitStore, WaitStatus

        attempt = self.attempt
        tool_call_id = str(payload.get("tool_call_id") or "")
        if not self.provider_action_id or not tool_call_id:
            raise shared.AgentDriverError("checkpoint_schema_invalid", "wait has no stable provider or tool identity")
        wait_kind = str(pre_wait.get("kind") or "")
        if wait_kind not in {"approval", "ask", "ask_many", "confirm", "form", "system_access"}:
            raise shared.AgentDriverError("invalid_wait", "wait kind is not supported at an Agent tool boundary")
        wait_id_parts = [
            attempt.execution_id, self.provider_action_id, tool_call_id, wait_kind,
        ]
        if wait_kind == "system_access":
            wait_id_parts.append(str(attempt.generation))
        wait_id = "wait_" + _digest(*wait_id_parts)[:32]
        existing = DurableWaitStore(self.driver.executions).get_wait(wait_id)
        if wait_kind == "system_access" and existing is not None and existing.status is WaitStatus.RESOLVED:
            # A resolved receipt is tied to an earlier executor
            # report. Never reuse it after a revocation race.
            wait_id = "wait_" + _digest(
                attempt.execution_id, self.provider_action_id, tool_call_id,
                wait_kind, str(attempt.generation), "recheck",
            )[:32]
            existing = DurableWaitStore(self.driver.executions).get_wait(wait_id)
        return wait_kind, wait_id, existing

    def _wait_before_tool(self, service, payload) -> bool:
        """Open or reuse the tool's durable wait; True suspends the turn."""
        from openprogram.runtime.execution.waits import WaitStatus

        pre_wait = dict(payload["pre_wait"])
        wait_kind, wait_id, existing = self._wait_identity(payload, pre_wait)
        if existing is not None:
            if existing.status is WaitStatus.RESOLVED or (
                existing.status is WaitStatus.DECLINED
                and existing.policy_snapshot.get("on_decline") == "continue"
            ):
                # The tool reads the outcome; a declined approval
                # reports the refusal instead of running.
                payload["preapproved_wait_id"] = wait_id
                return False
            # Other outcomes settle the execution before a
            # replacement attempt can reach this boundary. Do not
            # dispatch the protected tool from an unresolved record.
            return True
        self._open_wait(service, payload, pre_wait, wait_kind, wait_id)
        return True

    def _open_wait(self, service, payload, pre_wait, wait_kind: str, wait_id: str) -> None:
        """Checkpoint at the wait, open it durably and announce it."""
        from openprogram.runtime.execution.checkpoints import CheckpointFragment

        attempt = self.attempt
        checkpoint = self._checkpoint_payload("wait.before_tool", payload)
        current = service.executions.get_execution(attempt.execution_id)
        if current is None:
            raise shared.AgentDriverError("execution_not_found", "execution disappeared before wait")
        request_metadata = pre_wait.get("request_metadata", {})
        if not isinstance(request_metadata, shared.Mapping):
            raise shared.AgentDriverError("invalid_wait", "wait request metadata is invalid")
        wait_request = {
            "prompt": str(pre_wait.get("prompt") or ""),
            "options": list(pre_wait.get("options") or ()),
            "multi": bool(pre_wait.get("multi", False)),
            "allow_custom": bool(pre_wait.get("allow_custom", True)),
            "detail": str(pre_wait.get("detail") or ""),
            "schema": dict(pre_wait.get("schema") or {}),
            "questions": list(pre_wait.get("questions") or []),
        }
        reserved = set(wait_request).intersection(request_metadata)
        if reserved:
            raise shared.AgentDriverError("invalid_wait", "wait metadata cannot replace presentation fields")
        wait_request.update(dict(request_metadata))
        timeout = pre_wait.get("timeout", 300.0)
        if timeout is not None and (type(timeout) not in {int, float} or timeout <= 0):
            raise shared.AgentDriverError("invalid_wait", "approval wait timeout is invalid")
        policy = pre_wait.get("policy_snapshot")
        if not isinstance(policy, shared.Mapping):
            raise shared.AgentDriverError("invalid_wait_policy", "approval wait policy is invalid")
        suspension = service.open_wait_at_safe_point(
            execution_id=attempt.execution_id,
            attempt_id=attempt.attempt_id,
            generation=attempt.generation,
            expected_version=current.status_version,
            fragment=CheckpointFragment(
                safe_point_kind="agent.wait.before_tool",
                frontier=tuple(checkpoint.payload["frontier"]),
                state_refs={},
                completed_actions=tuple(), effect_receipts=tuple(),
                pending_command_ids=tuple(checkpoint.payload["pending_command_ids"]),
            ),
            kind=wait_kind, request=wait_request,
            policy_snapshot=dict(policy), expires_at=0 if timeout is None else time.time() + float(timeout),
            wait_id=wait_id, agent_checkpoint=checkpoint,
        )
        self._publish_wait(suspension, wait_kind, wait_request)

    def _publish_wait(self, suspension, wait_kind: str, wait_request) -> None:
        """Send the live question or system-access frame for an opened wait."""
        try:
            sink = self.driver.event_sink
            if sink is None:
                # Durable continuations can outlive the original
                # chat transport. Their next wait still needs a
                # live notification on the shared event stream.
                from openprogram.runtime.events import emit_ws_frame
                sink = emit_ws_frame
            frame_type = "system_access.waiting" if wait_kind == "system_access" else "question.asked"
            from openprogram.runtime.execution.waits import question_frame_data
            data = question_frame_data(
                suspension.wait, session_id=self.request.session_id,
                expected_version=suspension.execution.status_version,
            )
            if wait_kind == "system_access":
                data.update({
                    "wait_id": suspension.wait.wait_id,
                    "execution_id": self.attempt.execution_id,
                    "required_capabilities": list(wait_request.get("required_capabilities", [])),
                    "capabilities": list(wait_request.get("capabilities", [])),
                    "reason_code": "system_access_required",
                    "live": True,
                })
            sink({"type": frame_type, "data": data})
        except Exception:
            shared._log.exception("failed to publish durable approval wait")

    # -- Running: register the effect intent before dispatch --------------

    def _register_effect_intent(self, service, kind: str, payload) -> bool:
        """Register the provider or tool effect before it is dispatched."""
        from openprogram.runtime.execution.effects import EffectClassification, EffectStatus

        attempt = self.attempt
        execution = service.executions.get_execution(attempt.execution_id)
        if execution is None:
            raise shared.AgentDriverError("execution_not_found", "execution disappeared before effect")
        if execution.status is ExecutionStatus.CANCELLING or self.cancel_event.is_set():
            _interrupt_cancelled()
        if kind == "provider.before":
            snapshot = payload.get("resolved_snapshot")
            if not isinstance(snapshot, shared.Mapping):
                raise shared.AgentDriverError("checkpoint_schema_invalid", "provider action has no resolved snapshot")
            self.latest_snapshot = dict(snapshot)
            context_hash = str(payload.get("normalized_context_hash") or _json_digest(payload.get("context") or {}))
            action_id = _digest(
                str(execution.revision_id),
                str(attempt.generation),
                str(execution.checkpoint_head_id or "root"),
                context_hash,
                _json_digest(self.latest_snapshot),
            )
            input_hash = context_hash
        elif kind == "tool.before":
            tool_call_id = str(payload.get("tool_call_id") or "")
            if not self.provider_action_id or not tool_call_id:
                raise shared.AgentDriverError("checkpoint_schema_invalid", "tool action has no provider decision")
            action_id = _digest(
                str(execution.revision_id),
                self.provider_action_id,
                tool_call_id,
                _json_digest(payload.get("arguments") or {}),
            )
            input_hash = _json_digest(payload.get("arguments") or {})
        else:
            raise shared.AgentDriverError("invalid_safe_point", "unsupported Agent effect boundary")
        effect_id = f"effect_{action_id[:32]}"
        previous = service.effects.get(effect_id)
        if kind == "tool.before" and previous is not None and (
            previous.receipt.get("function_suspended") is True
            or previous.receipt.get("pause_before_dispatch") is True
        ):
            action_id = _digest(action_id, str(attempt.generation))
            effect_id = f"effect_{action_id[:32]}"
        supports_idempotency_key = (
            kind == "provider.before"
            and payload.get("supports_idempotency_key") is True
        )
        idempotency_key = action_id if supports_idempotency_key else None
        if kind == "provider.before":
            # The callback mutates the request payload so the exact
            # key used for the durable effect reaches SimpleStreamOptions.
            payload["supports_idempotency_key"] = supports_idempotency_key
            payload["idempotency_key"] = idempotency_key
        dispatch_candidates = tuple(
            dict(candidate)
            for candidate in (payload.get("dispatch_candidates") or ())
            if isinstance(candidate, shared.Mapping)
        )
        classification = (
            EffectClassification.IDEMPOTENT
            if supports_idempotency_key
            else EffectClassification.NONREPEATABLE
        )
        effect = service.effects.register(
            effect_id=effect_id, execution_id=attempt.execution_id,
            attempt_id=attempt.attempt_id, action_id=action_id,
            classification=classification,
            idempotency_key=idempotency_key,
            metadata={"kind": kind, "payload": dict(payload)},
        )
        self.pending[kind.rsplit(".", 1)[0]] = (
            effect_id, action_id, input_hash, idempotency_key,
            dispatch_candidates,
        )
        if effect.status is EffectStatus.PLANNED and kind != "tool.before":
            service.effects.mark_dispatched(
                effect.effect_id, expected_status=EffectStatus.PLANNED,
            )
        return False

    # -- Running: settle the effect that just finished -------------------

    def _take_dispatched_effect(self, service, kind: str):
        """Pop the pending intent for this boundary and check it can settle."""
        from openprogram.runtime.execution.effects import EffectStatus

        key = kind.rsplit(".", 1)[0]
        try:
            intent = self.pending.pop(key)
        except KeyError as exc:
            raise shared.AgentDriverError("effect_state_invalid", "Agent effect has no durable dispatch intent") from exc
        effect = service.effects.get(intent[0])
        if effect is None or effect.status not in {EffectStatus.DISPATCHED, EffectStatus.PLANNED}:
            raise shared.AgentDriverError("effect_state_invalid", "Agent effect is not dispatchable")
        if effect.status is EffectStatus.PLANNED and kind not in {"tool.after", "tool.suspended"}:
            raise shared.AgentDriverError("effect_state_invalid", "Agent effect is not dispatchable")
        return effect, intent

    def _record_provider_decision(
        self, payload, effect_id: str, action_id: str, input_hash: str,
        idempotency_key: str | None, dispatch_candidates,
    ) -> dict[str, shared.Any]:
        """Adopt the provider's AssistantMessage as the new decision; return its receipt."""
        message = payload.get("message")
        if not isinstance(message, shared.Mapping):
            raise shared.AgentDriverError("checkpoint_schema_invalid", "provider receipt lacks AssistantMessage")
        self.latest_assistant = dict(message)
        self.provider_action_id = action_id
        self.completed_tool_results = []
        actual_identity = {
            "api": message.get("api"),
            "provider": message.get("provider"),
            "model": message.get("model"),
        }
        actual_candidate = next(
            (
                candidate for candidate in dispatch_candidates
                if all(
                    actual_identity[field] == candidate.get(field)
                    for field in ("api", "provider", "model")
                )
            ),
            None,
        )
        actual_supports_idempotency_key = bool(
            actual_candidate is not None
            and actual_candidate.get("supports_idempotency_key") is True
        )
        if not dispatch_candidates:
            # Direct callers predating candidate metadata have only
            # the effect's dispatch-time capability declaration.
            actual_supports_idempotency_key = idempotency_key is not None
        terminal_receipt = {
            **actual_identity,
            "provider_request_id": payload.get("provider_request_id"),
            "usage": payload.get("usage"),
            "message_hash": _json_digest(self.latest_assistant),
            "stop_reason": message.get("stop_reason"),
            "interrupted_by_steer": bool(payload.get("interrupted_by_steer")),
            "supports_idempotency_key": actual_supports_idempotency_key,
        }
        terminal_receipt["idempotency_key"] = (
            idempotency_key if actual_supports_idempotency_key else None
        )
        self.provider_effect_id = effect_id
        self.provider_input_hash = input_hash
        self.provider_terminal_receipt = dict(terminal_receipt)
        for item in self.latest_assistant.get("content", []):
            if not isinstance(item, shared.Mapping):
                continue
            item_type = item.get("type")
            if item_type == "text" and isinstance(item.get("text"), str) and item["text"]:
                self.display_blocks.append({"type": "text", "text": item["text"]})
            elif item_type == "thinking" and isinstance(item.get("thinking"), str) and item["thinking"]:
                self.display_blocks.append({"type": "thinking", "text": item["thinking"]})
            elif item_type == "toolCall":
                self.display_blocks.append({
                    "type": "tool",
                    "tool": item.get("name"),
                    "tool_call_id": item.get("id"),
                    "input": shared.json.dumps(item.get("arguments") or {}, default=str),
                })
        return terminal_receipt

    @staticmethod
    def _record_tool_suspension(service, effect, effect_id: str, payload) -> dict[str, shared.Any]:
        """Receipt a tool whose function suspended mid-call."""
        from openprogram.runtime.execution.effects import EffectStatus

        terminal_receipt = {"function_suspended": True, "tool_call_id": payload.get("tool_call_id")}
        if effect.status is EffectStatus.PLANNED:
            service.effects.mark_dispatched(
                effect.effect_id, expected_status=EffectStatus.PLANNED,
            )
            effect = service.effects.get(effect_id)
        return terminal_receipt

    def _record_tool_result(self, service, effect, effect_id: str, payload):
        """Keep the ToolResultMessage, update its display block; return receipt and result."""
        from openprogram.runtime.execution.effects import EffectStatus

        result = payload.get("result")
        if not isinstance(result, shared.Mapping):
            raise shared.AgentDriverError("checkpoint_schema_invalid", "tool receipt lacks ToolResultMessage")
        self.completed_tool_results.append(dict(result))
        not_started = effect.status is EffectStatus.PLANNED
        outcome = "not_started" if not_started else ("failed" if payload.get("is_error") else "completed")
        terminal_receipt = {
            "tool_call_id": payload.get("tool_call_id"),
            "is_error": bool(payload.get("is_error")),
            "result_hash": _json_digest(result),
            "outcome": outcome, "execution_started": not not_started,
        }
        tool_call_id = payload.get("tool_call_id")
        result_text = "\n".join(
            str(item.get("text") or "")
            for item in (result.get("content") or ())
            if isinstance(item, shared.Mapping) and item.get("type") == "text"
        )
        for block in reversed(self.display_blocks):
            if block.get("type") == "tool" and block.get("tool_call_id") == tool_call_id:
                block["result"] = result_text
                block["is_error"] = bool(payload.get("is_error"))
                block["outcome"] = outcome
                break
        if effect.status is EffectStatus.PLANNED and terminal_receipt.get("outcome") != "not_started":
            service.effects.mark_dispatched(
                effect.effect_id, expected_status=EffectStatus.PLANNED,
            )
            effect = service.effects.get(effect_id)
        return terminal_receipt, result

    def _remember_completed_action(
        self, kind: str, effect_id: str, action_id: str, input_hash: str,
        terminal_receipt, result,
    ) -> None:
        """Add the settled action to the resume cursor."""
        is_provider = kind in {"provider.after", "provider.finished"}
        # Keep the current provider decision as the resume cursor.
        # Earlier committed writes are already in the effect ledger.
        self.prior_actions.append({
            "action_id": action_id, "input_hash": input_hash,
            "result": dict(self.latest_assistant) if is_provider else dict(result),
        })
        self.prior_receipts.append({
            "effect_id": effect_id,
            "frontier_step_id": f"{'after_provider' if is_provider else 'after_tool'}:{action_id}",
            "action_id": action_id, "outcome": "committed",
            "receipt": dict(terminal_receipt),
        })
        if is_provider:
            self.decision_action_ids.clear()
            self.decision_action_ids.add(action_id)
            self.prior_actions[:] = [
                item for item in self.prior_actions if item.get("action_id") == action_id
            ]
            self.prior_receipts[:] = [
                item for item in self.prior_receipts if item.get("action_id") == action_id
            ]
        else:
            self.decision_action_ids.add(action_id)

    def _resolve_without_checkpoint(self, service, effect_id: str, terminal_receipt) -> None:
        """Settle the effect directly when no command or restart window needs a checkpoint."""
        from openprogram.runtime.execution.effects import EffectStatus

        attempt = self.attempt
        if terminal_receipt.get("outcome") == "not_started":
            service.effects.resolve_not_started(
                effect_id, receipt=terminal_receipt,
                attempt_id=attempt.attempt_id, generation=attempt.generation,
            )
        else:
            service.effects.resolve(
                effect_id, expected_status=EffectStatus.DISPATCHED,
                outcome=EffectStatus.COMMITTED, receipt=terminal_receipt,
                attempt_id=attempt.attempt_id, generation=attempt.generation,
            )

    def _commit_safe_point(
        self, service, kind: str, payload, effect_id: str, action_id: str,
        input_hash: str, terminal_receipt, command, restart_window,
    ):
        """Record the result and commit the checkpoint, retrying stale versions."""
        attempt = self.attempt
        current = service.executions.get_execution(attempt.execution_id)
        if current is None:
            raise shared.AgentDriverError("execution_not_found", "execution disappeared at safe point")
        inputs = self._checkpoint_inputs(kind, payload, effect_id, action_id, input_hash, terminal_receipt)
        if kind != "tool.suspended":
            from openprogram.runtime.execution.agent_receipts import record_result
            record_result(service, attempt=attempt, effect_id=effect_id,
                          terminal_receipt=terminal_receipt, checkpoint_inputs=inputs,
                          restart_window=restart_window,
                          command_id=command.command_id if command is not None else None,
                          consumed_steer_command_ids=tuple(sorted(self.steer_consumed_ids or ())))
        try:
            checkpoint = AgentCheckpointV1.build(**inputs)
        except AgentCheckpointError as exc:
            raise shared.AgentDriverError(exc.code, str(exc)) from exc
        from openprogram.runtime.execution.safe_points import AgentSafePointConflict
        while True:
            try:
                return service.commit_agent_safe_point(
                    execution_id=attempt.execution_id, attempt_id=attempt.attempt_id,
                    generation=attempt.generation, expected_version=current.status_version,
                    safe_point_kind=str(checkpoint.payload["safe_point"]["kind"]),
                    frontier=tuple(checkpoint.payload["frontier"]),
                    state_refs={"restart_window_seconds": restart_window},
                    effect_id=effect_id, terminal_receipt=terminal_receipt,
                    receipt_blob=canonical_json_bytes(terminal_receipt),
                    agent_checkpoint=checkpoint,
                    command_id=command.command_id if command is not None else None, managed_action_id=action_id,
                    consumed_steer_command_ids=tuple(sorted(self.steer_consumed_ids or ())),
                )
            except AgentSafePointConflict as exc:
                if exc.code != "stale_version":
                    raise
                # Control commands may advance the execution version while
                # we serialize the result. The exact effect and attempt
                # still fence this retry; no provider/tool is re-executed.
                current = service.executions.get_execution(attempt.execution_id)
                if current is None or current.current_attempt_id != attempt.attempt_id:
                    raise

    # -- Steering: queue applied steer messages for the next provider call --

    def _queue_applied_steers(self, completion) -> None:
        """Append steer messages the commit applied to the in-memory steer queue."""
        from openprogram.runtime.execution.model import CommandKind

        steer_queue = self.steer_queue
        consumed = self.steer_consumed_ids or set()
        for applied in completion.applied_commands:
            if applied.kind is not CommandKind.STEER:
                continue
            if applied.command_id in consumed or any(
                item.get("command_id") == applied.command_id for item in steer_queue
            ):
                continue
            message = applied.payload.get("message")
            if isinstance(message, str) and message.strip():
                steer_queue.append({
                    "command_id": applied.command_id,
                    "payload": shared._json_safe(applied.payload),
                })

    def _settle_effect(self, service, kind: str, payload) -> bool:
        """Settle a finished effect and checkpoint; True pauses after this step."""
        from openprogram.runtime.execution.model import CommandKind
        from openprogram.runtime.execution.restart import window_seconds

        effect, intent = self._take_dispatched_effect(service, kind)
        effect_id, action_id, input_hash, idempotency_key, dispatch_candidates = intent
        result = None
        if kind in {"provider.after", "provider.finished"}:
            terminal_receipt = self._record_provider_decision(
                payload, effect_id, action_id, input_hash, idempotency_key, dispatch_candidates,
            )
        elif kind == "tool.suspended":
            terminal_receipt = self._record_tool_suspension(service, effect, effect_id, payload)
        elif kind == "tool.after":
            terminal_receipt, result = self._record_tool_result(service, effect, effect_id, payload)
        else:
            raise shared.AgentDriverError("invalid_safe_point", "unsupported Agent safe point")

        self.last_checkpoint_inputs = self._checkpoint_inputs(
            kind, payload, effect_id, action_id, input_hash, terminal_receipt,
        )
        command = None if kind == "provider.finished" else self._current_command(service, self.attempt.execution_id)
        # Direct non-durable hook callers do not carry a revision contract.
        restart_window = window_seconds() if getattr(self.request, "_execution_revision_id", None) or self.continuation is not None else 0
        if command is None and restart_window == 0:
            self._resolve_without_checkpoint(service, effect_id, terminal_receipt)
            # A suspended tool has no result to resume from, on this path as
            # on the checkpointed one below.
            if kind != "tool.suspended":
                self._remember_completed_action(kind, effect_id, action_id, input_hash, terminal_receipt, result)
            return False
        completion = self._commit_safe_point(
            service, kind, payload, effect_id, action_id, input_hash,
            terminal_receipt, command, restart_window,
        )
        if kind != "tool.suspended":
            self._remember_completed_action(kind, effect_id, action_id, input_hash, terminal_receipt, result)
        if command is not None and command.kind is CommandKind.STEER and self.steer_queue is not None:
            self._queue_applied_steers(completion)
        return command is not None and command.kind in {CommandKind.PAUSE, CommandKind.STEP}

    # -- entry points ----------------------------------------------------

    def hook(self, kind: str, payload: shared.Mapping[str, shared.Any]) -> bool:
        """Route one Agent-loop boundary to the step that handles it."""
        service = self.driver._control_service()
        if kind == "provider.poll":
            return self._observe_provider_poll(service, payload)
        if kind == "tool.started":
            return self._mark_tool_started(service)
        if kind == "tool.before" and isinstance(payload.get("pre_wait"), shared.Mapping) and (
            str(payload["pre_wait"].get("kind") or "") == "system_access"
        ):
            self._recheck_system_access(payload)
        if kind == "tool.before" and isinstance(payload.get("pre_wait"), shared.Mapping):
            if self._wait_before_tool(service, payload):
                return True
        if kind.endswith(".before"):
            return self._register_effect_intent(service, kind, payload)
        return self._settle_effect(service, kind, payload)

    def __call__(self, kind, payload):
        """Check for pause before any new dispatch, then run the boundary."""
        from openprogram.runtime.execution.effects import EffectConflict

        if kind.endswith(".before") or kind == "tool.started":
            service = self.driver._control_service()
            if self._pause_before_dispatch(service):
                return True
            try:
                return self.hook(kind, payload)
            except EffectConflict as exc:
                # Pause can win after the precheck, including between
                # registering an intent and admitting its dispatch.
                if exc.code == "admission_closed" and self._pause_before_dispatch(service):
                    return True
                raise
        return self.hook(kind, payload)


class SafePointsOperations:
    def _safe_point_hook(
        self,
        attempt: AttemptRecord,
        request: shared.Any,
        cancel_event: shared.threading.Event,
        *,
        continuation: AgentContinuation | None = None,
        steer_queue: list[dict[str, shared.Any]] | None = None,
        steer_consumed_ids: set[str] | None = None,
    ) -> shared.Callable[[str, shared.Mapping[str, shared.Any]], bool]:
        """Bind Agent-loop boundaries to the canonical execution owner.

        The closure carries only durable identifiers and JSON payloads.  It
        deliberately retains no provider stream, coroutine, tool object, or
        dispatcher-local state for a future attempt.
        """
        return _AgentSafePointHook(
            self, attempt, request, cancel_event,
            continuation, steer_queue, steer_consumed_ids,
        )
