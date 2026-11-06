"""driver safe points tests."""

from __future__ import annotations

from openprogram.programs._host import runtime as program_runtime
from pathlib import Path
from openprogram.runtime.execution.model import CommandStatus, ExecutionStatus
from ._support import (
    AttemptStore,
    CapabilitySet,
    ExecutionStore,
    LONG_TURN_DECISIONS,
    _admitted,
    _committed_tool_ids,
    _prepare_long_turn,
    _provider_tool_decision,
    asyncio,
    threading,
)


def test_agent_driver_declares_only_p0_safe_point_capabilities():
    from openprogram.runtime.conversation.production_driver import AgentProductionDriver

    driver = AgentProductionDriver(
        executions=None,
        input_resolver=lambda _record: {},
        turn_runner=lambda **_kwargs: None,
    )

    assert driver.capabilities() == CapabilitySet(
        pause=True,
        step=True,
        steer=True,
        fork=True,
        retry=True,
        safe_point_kinds=(
            "agent.provider.decision.after",
            "agent.tool.action.after",
            "agent.wait.before_tool",
        ),
        state_schema_version=1,
    )


def test_app_control_safe_point_waits_before_tool_effect_and_resumes_once(
    tmp_path, monkeypatch
):

    from openprogram.host import system_access
    from openprogram.runtime.conversation.checkpoint import runtime_contract_snapshot
    from openprogram.runtime.agent.turn_request import TurnRequest
    from openprogram.runtime.conversation.production_driver import AgentProductionDriver
    from openprogram.runtime.execution.control import RuntimeControlService
    from openprogram.runtime.execution.driver import DriverRegistry
    from openprogram.runtime.execution.effects import EffectStore
    from openprogram.runtime.execution.waits import DurableWaitStore, WaitStatus
    from openprogram.models.providers.types import Model

    store, execution = _admitted(tmp_path, execution_id="exec-system-public")
    attempts = AttemptStore(store)
    leased, reserved = attempts.lease(
        execution.execution_id,
        expected_version=execution.status_version,
        owner_id="system-public",
        ttl_seconds=30,
    )
    active, running = attempts.activate(
        leased.attempt_id,
        generation=leased.generation,
        expected_execution_version=reserved.status_version,
    )
    activations = []

    async def activate(next_attempt, activation):
        activations.append(
            (next_attempt.execution_id, activation.checkpoint.checkpoint_id)
        )

    control = RuntimeControlService(
        store,
        attempts,
        DriverRegistry(),
        activator=activate,
    )
    driver = AgentProductionDriver(store, control_service=control)
    frames = []
    monkeypatch.setattr("openprogram.runtime.events.emit_ws_frame", frames.append)
    request = TurnRequest(
        session_id=running.session_id,
        user_text="run GUI",
        agent_id="default",
        source="component",
        user_msg_id="user-system-public",
    )
    request._execution_revision_id = running.revision_id
    hook = driver._safe_point_hook(active, request, threading.Event())
    snapshot = runtime_contract_snapshot(
        model=Model(
            id="fake",
            name="fake",
            api="openai-completions",
            provider="openai",
            base_url="https://example.invalid/v1",
        ),
        system_prompt="system",
        tools=[],
        request=request,
    )
    monkeypatch.setattr(system_access.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        system_access,
        "report",
        lambda: {
            "platform": "Darwin",
            "capabilities": [
                {
                    "id": "screen_recording",
                    "status": "not_granted",
                    "can_request": True,
                },
                {"id": "accessibility", "status": "not_granted", "can_request": True},
            ],
        },
    )
    args = {"target": "app", "action": "click", "args": {"app": "Notes", "element_index": 1}}
    manifest = system_access.access_manifest_for_tool("computer_use_agent", args)
    assert manifest is not None

    assert (
        hook(
            "provider.before",
            {
                "resolved_snapshot": snapshot,
                "context": {"messages": []},
                "supports_idempotency_key": True,
            },
        )
        is False
    )
    assert (
        hook(
            "provider.after",
            {
                "message": {
                    "role": "assistant",
                    "content": [],
                    "api": "fake",
                    "provider": "fake",
                    "model": "fake",
                },
                "provider_request_id": "request-system-public",
                "usage": {},
            },
        )
        is False
    )
    payload = {
        "tool_call_id": "gui-call",
        "tool_name": "computer_use_agent",
        "arguments": args,
        "next_tool_index": 0,
        "pre_wait": manifest,
    }
    assert hook("tool.before", payload) is True
    paused = store.get_execution(execution.execution_id)
    assert paused is not None and paused.status is ExecutionStatus.PAUSED
    assert paused.reason_code == "system_access_required"
    wait = DurableWaitStore(store).list_open(execution_id=execution.execution_id)[0]
    assert wait.kind == "system_access" and wait.expires_at == 0
    waiting = next(
        frame for frame in frames if frame["type"] == "system_access.waiting"
    )
    assert waiting["data"]["live"] is True
    assert not [
        effect
        for effect in EffectStore(store).list_unresolved(execution.execution_id)
        if effect.metadata.get("kind") == "tool.before"
    ]

    monkeypatch.setattr(
        system_access,
        "report",
        lambda: {
            "platform": "Darwin",
            "capabilities": [
                {"id": "screen_recording", "status": "granted"},
                {"id": "accessibility", "status": "granted"},
            ],
        },
    )
    asyncio.run(control.recover_wait_outcomes())
    asyncio.run(control.recover_wait_outcomes())
    resumed = store.get_execution(execution.execution_id)
    assert resumed is not None and resumed.status is ExecutionStatus.RUNNING
    assert activations == [(execution.execution_id, wait.checkpoint_id)]
    assert DurableWaitStore(store).get_wait(wait.wait_id).status is WaitStatus.RESOLVED


def test_forced_app_control_uses_durable_system_wait_before_subprocess(
    tmp_path, monkeypatch
):

    from openprogram.host import system_access
    from openprogram.runtime.conversation.production_driver import AgentProductionDriver
    from openprogram.runtime.execution.control import RuntimeControlService
    from openprogram.runtime.execution.driver import DriverRegistry
    from openprogram.runtime.execution.waits import DurableWaitStore

    store = ExecutionStore(tmp_path / "forced-system.sqlite3")
    revision = store.create_revision(manifest={"entrypoint": "forced"})
    payload = {
        "version": 1,
        "kind": "forced_tool",
        "tool_name": "computer_use_agent",
        "tool_input": {"target": "app", "args": {"app": "Notes"}},
        "source": "web",
        "agent_id": "main",
    }
    execution = store.admit_execution(
        execution_id="exec-forced-system",
        run_id="run-forced-system",
        session_id="session-forced-system",
        revision_id=revision.revision_id,
        input_ref="input:forced-system",
        input_hash="forced-system-hash",
        entrypoint="openprogram.runtime.conversation.production_driver:AgentProductionDriver",
        trusted_actor={"subject": "owner"},
        config_snapshot_ref="config:forced-system",
        capabilities=AgentProductionDriver.capabilities_for_payload(payload),
        agent_turn_payload=payload,
    )
    attempts = AttemptStore(store)
    leased, reserved = attempts.lease(
        execution.execution_id,
        expected_version=execution.status_version,
        owner_id="forced-system",
        ttl_seconds=30,
    )
    active, running = attempts.activate(
        leased.attempt_id,
        generation=leased.generation,
        expected_execution_version=reserved.status_version,
    )
    calls = []

    def fake_dispatch(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        "openprogram.runtime.conversation.turn_runtime.dispatch_forced_tool_call", fake_dispatch
    )
    frames = []
    monkeypatch.setattr("openprogram.runtime.events.emit_ws_frame", frames.append)
    monkeypatch.setattr(system_access.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        system_access,
        "report",
        lambda: {
            "platform": "Darwin",
            "capabilities": [
                {
                    "id": "screen_recording",
                    "status": "not_granted",
                    "can_request": True,
                },
                {"id": "accessibility", "status": "not_granted", "can_request": True},
            ],
        },
    )
    control = RuntimeControlService(store, attempts, DriverRegistry())
    driver = AgentProductionDriver(store, control_service=control)

    async def resume(attempt, activation):
        binding = await driver.activate(attempt, activation)
        driver.activation_committed(binding)
        await binding.handle.done

    control.activator = resume
    binding = asyncio.run(driver.activate(active, activation=None))
    driver.activation_committed(binding)

    async def wait_done():
        return await binding.handle.done

    asyncio.run(wait_done())
    wait = DurableWaitStore(store).list_open(execution_id=execution.execution_id)[0]
    assert wait.kind == "system_access"
    waiting = next(
        frame for frame in frames if frame["type"] == "system_access.waiting"
    )
    assert waiting["data"]["live"] is True
    assert calls == []

    monkeypatch.setattr(
        system_access,
        "report",
        lambda: {
            "platform": "Darwin",
            "capabilities": [
                {"id": "screen_recording", "status": "granted"},
                {"id": "accessibility", "status": "granted"},
            ],
        },
    )
    asyncio.run(control.recover_wait_outcomes())
    asyncio.run(control.recover_wait_outcomes())
    assert len(calls) == 1
    resumed = store.get_execution(execution.execution_id)
    assert resumed is not None and resumed.status is ExecutionStatus.COMPLETED


def test_production_driver_consumes_running_steer_fifo_at_provider_safe_point(tmp_path):
    from openprogram.runtime.execution.control import RuntimeControlService
    from openprogram.runtime.execution.driver import DriverRegistry
    from openprogram.runtime.conversation.production_driver import AgentProductionDriver
    from openprogram.runtime.conversation.checkpoint import runtime_contract_snapshot
    from openprogram.runtime.agent.turn_request import TurnRequest
    from openprogram.models.providers.types import Model

    store, execution = _admitted(tmp_path, execution_id="exec-running-steer")
    attempts = AttemptStore(store)
    leased, reserved = attempts.lease(
        execution.execution_id,
        expected_version=execution.status_version,
        owner_id="owner-steer",
        ttl_seconds=30,
    )
    active, running = attempts.activate(
        leased.attempt_id,
        generation=leased.generation,
        expected_execution_version=reserved.status_version,
    )
    control = RuntimeControlService(store, attempts, DriverRegistry())
    first = control.request_steer(
        command_id="steer-first",
        execution_id=execution.execution_id,
        expected_version=running.status_version,
        actor={"surface": "test"},
        payload={"message": "first instruction"},
    )
    second = control.request_steer(
        command_id="steer-second",
        execution_id=execution.execution_id,
        expected_version=running.status_version,
        actor={"surface": "test"},
        payload={"message": "second instruction",
                 "images": [{"path": "/s/shot.png", "media_type": "image/png"}]},
    )
    assert first.command.status is CommandStatus.ACCEPTED
    assert second.command.status is CommandStatus.ACCEPTED

    queue: list[dict] = []
    consumed: set[str] = set()
    request = TurnRequest(
        session_id=running.session_id,
        user_text="durable agent turn",
        agent_id="default",
        source="component",
        user_msg_id="user-anchor",
    )
    request._execution_revision_id = running.revision_id
    hook = AgentProductionDriver(store, control_service=control)._safe_point_hook(
        active,
        request,
        threading.Event(),
        steer_queue=queue,
        steer_consumed_ids=consumed,
    )
    snapshot = runtime_contract_snapshot(
        model=Model(
            id="fake",
            name="fake",
            api="openai-completions",
            provider="openai",
            base_url="https://example.invalid/v1",
        ),
        system_prompt="system",
        tools=[],
        request=request,
    )
    assert (
        hook(
            "provider.before",
            {
                "resolved_snapshot": snapshot,
                "context": {"messages": []},
                "supports_idempotency_key": True,
            },
        )
        is False
    )
    assert (
        hook(
            "provider.after",
            {
                "message": {
                    "role": "assistant",
                    "content": [],
                    "api": "fake",
                    "provider": "fake",
                    "model": "fake",
                },
                "provider_request_id": "request-steer",
                "usage": {},
            },
        )
        is False
    )

    # A later safe point must not enqueue the same pending delivery twice.
    assert (
        hook(
            "provider.before",
            {
                "resolved_snapshot": snapshot,
                "context": {"messages": ["next"]},
                "supports_idempotency_key": True,
            },
        )
        is False
    )
    assert (
        hook(
            "provider.after",
            {
                "message": {
                    "role": "assistant",
                    "content": [],
                    "api": "fake",
                    "provider": "fake",
                    "model": "fake",
                },
                "provider_request_id": "request-steer-next",
                "usage": {},
            },
        )
        is False
    )

    assert [item["command_id"] for item in queue] == [
        "steer-first",
        "steer-second",
    ]
    assert [item["payload"]["message"] for item in queue] == [
        "first instruction",
        "second instruction",
    ]
    # Everything the steer carried reaches the loop, not just its text.
    assert queue[1]["payload"]["images"] == [{"path": "/s/shot.png", "media_type": "image/png"}]
    # This fixture exercises safe-point queueing only. Delivery becomes
    # APPLIED after the dispatcher persists the branch-linked user message.
    assert all(
        store.get_command(command_id).status is CommandStatus.APPLYING
        for command_id in ("steer-first", "steer-second")
    )
    current = store.get_execution(execution.execution_id)
    assert current is not None and current.status is ExecutionStatus.RUNNING
    assert current.current_attempt_id == active.attempt_id


def test_production_pause_precedes_steer_and_paused_steer_is_next_activation_input(
    tmp_path,
):
    from openprogram.runtime.execution.control import RuntimeControlService
    from openprogram.runtime.execution.driver import DriverRegistry
    from openprogram.runtime.conversation.production_driver import AgentProductionDriver
    from openprogram.runtime.conversation.checkpoint import runtime_contract_snapshot
    from openprogram.runtime.agent.turn_request import TurnRequest
    from openprogram.models.providers.types import Model

    store, execution = _admitted(tmp_path, execution_id="exec-pause-steer")
    attempts = AttemptStore(store)
    leased, reserved = attempts.lease(
        execution.execution_id,
        expected_version=execution.status_version,
        owner_id="owner-pause-steer",
        ttl_seconds=30,
    )
    active, running = attempts.activate(
        leased.attempt_id,
        generation=leased.generation,
        expected_execution_version=reserved.status_version,
    )
    control = RuntimeControlService(store, attempts, DriverRegistry())
    request = TurnRequest(
        session_id=running.session_id,
        user_text="durable agent turn",
        agent_id="default",
        source="component",
        user_msg_id="user-anchor",
    )
    request._execution_revision_id = running.revision_id
    snapshot = runtime_contract_snapshot(
        model=Model(
            id="fake",
            name="fake",
            api="openai-completions",
            provider="openai",
            base_url="https://example.invalid/v1",
        ),
        system_prompt="system",
        tools=[],
        request=request,
    )
    queue: list[dict] = []
    hook = AgentProductionDriver(store, control_service=control)._safe_point_hook(
        active,
        request,
        threading.Event(),
        steer_queue=queue,
        steer_consumed_ids=set(),
    )
    hook(
        "provider.before",
        {
            "resolved_snapshot": snapshot,
            "context": {"messages": []},
            "supports_idempotency_key": True,
        },
    )
    steer = control.request_steer(
        command_id="steer-after-pause",
        execution_id=execution.execution_id,
        expected_version=running.status_version,
        actor={"surface": "test"},
        payload={"message": "continue with source B"},
    )
    asyncio.run(
        control.request_pause(
            command_id="pause-before-steer",
            execution_id=execution.execution_id,
            expected_version=running.status_version,
            actor={"surface": "test"},
        )
    )
    assert (
        hook(
            "provider.after",
            {
                "message": {
                    "role": "assistant",
                    "content": [],
                    "api": "fake",
                    "provider": "fake",
                    "model": "fake",
                },
                "provider_request_id": "request-pause-steer",
                "usage": {},
            },
        )
        is True
    )
    paused = store.get_execution(execution.execution_id)
    assert paused is not None and paused.status is ExecutionStatus.PAUSED
    assert store.get_command("pause-before-steer").status is CommandStatus.APPLIED
    assert store.get_command(steer.command.command_id).status is CommandStatus.ACCEPTED
    assert queue == []

    activation_inputs = []

    async def activate(_attempt, activation):
        activation_inputs.append(activation)

    continued = asyncio.run(
        control.request_continue(
            command_id="continue-after-pause-steer",
            execution_id=execution.execution_id,
            expected_version=paused.status_version,
            actor={"surface": "test"},
            activator=activate,
        )
    )
    assert continued.command.status is CommandStatus.APPLIED
    assert len(activation_inputs) == 1
    assert (
        activation_inputs[0].steer_inputs[0]["command_id"] == steer.command.command_id
    )


def test_long_turn_pause_continue_uses_current_decision_cursor(tmp_path):
    from openprogram.runtime.conversation.checkpoint import AgentContinuation
    from openprogram.runtime.execution.checkpoints import ExecutionCheckpointStore
    from openprogram.runtime.execution.public import execution_snapshot

    store, attempts, control, driver, request, snapshot, execution, active, hook = (
        _prepare_long_turn(tmp_path, "exec-long-pause")
    )
    for index in range(LONG_TURN_DECISIONS):
        _provider_tool_decision(hook, snapshot, index)
    first_tools = _committed_tool_ids(store, execution.execution_id)
    assert len(first_tools) == LONG_TURN_DECISIONS
    assert len(set(first_tools)) == LONG_TURN_DECISIONS

    assert (
        hook(
            "provider.before",
            {
                "resolved_snapshot": snapshot,
                "context": {"messages": ["pause-1"]},
                "supports_idempotency_key": True,
            },
        )
        is False
    )
    asyncio.run(
        control.request_pause(
            command_id="pause-long-1",
            execution_id=execution.execution_id,
            expected_version=store.get_execution(execution.execution_id).status_version,
            actor={"surface": "browser-resource"},
        )
    )
    assert (
        hook(
            "provider.after",
            {
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "paused-1"}],
                    "api": "fake",
                    "provider": "fake",
                    "model": "fake",
                    "timestamp": 1,
                },
                "provider_request_id": "request-pause-1",
                "usage": {},
                "tool_call_ids": [],
                "next_tool_index": 0,
            },
        )
        is True
    )
    paused = store.get_execution(execution.execution_id)
    assert paused is not None and paused.status is ExecutionStatus.PAUSED
    assert paused.checkpoint_head_id is not None
    assert store.get_command("pause-long-1").status is CommandStatus.APPLIED
    assert _committed_tool_ids(store, execution.execution_id) == first_tools
    snapshot_one = execution_snapshot(paused, store=store)
    assert snapshot_one.can_continue is True
    unresolved = control.effects.list_unresolved(execution.execution_id)
    assert unresolved == []
    from openprogram.runtime.execution.agent_checkpoint import AgentCheckpointV1
    from openprogram.runtime.execution.projections import ExecutionProjectionReadModel

    state = AgentCheckpointV1.load(
        store, ExecutionCheckpointStore(store).get(paused.checkpoint_head_id)
    )
    assert "turn_display_ref" in state.payload
    display = state.read_json_ref(
        store,
        execution.execution_id,
        state.payload["turn_display_ref"],
    )
    assert display[0]["tool_call_id"] == "call-0"
    assert display[0]["result"] == "clicked-0"
    assert (
        display[LONG_TURN_DECISIONS - 1]["tool_call_id"]
        == f"call-{LONG_TURN_DECISIONS - 1}"
    )
    assert (
        display[LONG_TURN_DECISIONS - 1]["result"]
        == f"clicked-{LONG_TURN_DECISIONS - 1}"
    )
    assert len(state.payload["terminal_effect_receipts"]) <= 2
    projected = ExecutionProjectionReadModel(store)._checkpoint_blocks(
        paused,
        state.payload["turn"]["assistant_message_id"],
    )
    assert any(
        block.get("tool_call_id") == "call-0" and block.get("result") == "clicked-0"
        for block in projected
    )
    assert any(
        block.get("tool_call_id") == f"call-{LONG_TURN_DECISIONS - 1}"
        and block.get("result") == f"clicked-{LONG_TURN_DECISIONS - 1}"
        for block in projected
    )

    captured = {}

    async def activate(attempt, activation):
        captured["attempt"] = attempt
        captured["activation"] = activation

    continued = asyncio.run(
        control.request_continue(
            command_id="continue-long-1",
            execution_id=execution.execution_id,
            expected_version=paused.status_version,
            actor={"surface": "test"},
            activator=activate,
        )
    )
    assert continued.command.status is CommandStatus.APPLIED
    assert continued.execution.status is ExecutionStatus.RUNNING
    checkpoint = ExecutionCheckpointStore(store).get(paused.checkpoint_head_id)
    continuation = AgentContinuation.from_checkpoint(
        store=store,
        checkpoint=checkpoint,
        request=request,
    )
    assert len(continuation.state.payload["terminal_effect_receipts"]) <= 2
    hook2 = driver._safe_point_hook(
        captured["attempt"],
        request,
        threading.Event(),
        continuation=continuation,
    )
    for index in range(LONG_TURN_DECISIONS, LONG_TURN_DECISIONS * 2):
        _provider_tool_decision(hook2, snapshot, index)
    second_tools = _committed_tool_ids(store, execution.execution_id)
    assert second_tools[:LONG_TURN_DECISIONS] == first_tools
    assert len(second_tools) == LONG_TURN_DECISIONS * 2
    assert len(set(second_tools)) == LONG_TURN_DECISIONS * 2

    assert (
        hook2(
            "provider.before",
            {
                "resolved_snapshot": snapshot,
                "context": {"messages": ["pause-2"]},
                "supports_idempotency_key": True,
            },
        )
        is False
    )
    asyncio.run(
        control.request_pause(
            command_id="pause-long-2",
            execution_id=execution.execution_id,
            expected_version=store.get_execution(execution.execution_id).status_version,
            actor={"surface": "browser-resource"},
        )
    )
    assert (
        hook2(
            "provider.after",
            {
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "paused-2"}],
                    "api": "fake",
                    "provider": "fake",
                    "model": "fake",
                    "timestamp": 1,
                },
                "provider_request_id": "request-pause-2",
                "usage": {},
                "tool_call_ids": [],
                "next_tool_index": 0,
            },
        )
        is True
    )
    paused_again = store.get_execution(execution.execution_id)
    assert paused_again is not None and paused_again.status is ExecutionStatus.PAUSED
    assert paused_again.checkpoint_head_id is not None
    assert paused_again.checkpoint_head_id != paused.checkpoint_head_id
    assert store.get_command("pause-long-2").status is CommandStatus.APPLIED
    assert _committed_tool_ids(store, execution.execution_id) == second_tools
    second_state = AgentCheckpointV1.load(
        store,
        ExecutionCheckpointStore(store).get(paused_again.checkpoint_head_id),
    )
    second_display = second_state.read_json_ref(
        store,
        execution.execution_id,
        second_state.payload["turn_display_ref"],
    )
    assert any(
        block.get("tool_call_id") == "call-0" and block.get("result") == "clicked-0"
        for block in second_display
    )
    assert any(
        block.get("tool_call_id") == f"call-{LONG_TURN_DECISIONS}"
        and block.get("result") == f"clicked-{LONG_TURN_DECISIONS}"
        for block in second_display
    )
    snapshot_two = execution_snapshot(paused_again, store=store)
    assert snapshot_two.can_continue is True

    async def activate_again(attempt, activation):
        captured["second_activation"] = activation

    resumed = asyncio.run(
        control.request_continue(
            command_id="continue-long-2",
            execution_id=execution.execution_id,
            expected_version=paused_again.status_version,
            actor={"surface": "test"},
            activator=activate_again,
        )
    )
    assert resumed.command.status is CommandStatus.APPLIED
    assert resumed.execution.status is ExecutionStatus.RUNNING
    assert _committed_tool_ids(store, execution.execution_id) == second_tools


def test_pause_during_dispatched_nonrepeatable_tool_stays_reconciliation(tmp_path):
    from openprogram.runtime.execution.effects import EffectStatus

    store, attempts, control, driver, request, snapshot, execution, active, hook = (
        _prepare_long_turn(tmp_path, "exec-uncertain-tool")
    )
    _provider_tool_decision(hook, snapshot, 0)
    assert (
        hook(
            "provider.before",
            {
                "resolved_snapshot": snapshot,
                "context": {"messages": ["in-flight-tool"]},
                "supports_idempotency_key": True,
            },
        )
        is False
    )
    assert (
        hook(
            "provider.after",
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "call-inflight",
                            "name": "web_use",
                            "arguments": {"n": "inflight"},
                        }
                    ],
                    "api": "fake",
                    "provider": "fake",
                    "model": "fake",
                },
                "provider_request_id": "request-inflight",
                "usage": {},
                "tool_call_ids": ["call-inflight"],
                "next_tool_index": 0,
            },
        )
        is False
    )
    assert (
        hook(
            "tool.before",
            {
                "tool_call_id": "call-inflight",
                "arguments": {"n": "inflight"},
            },
        )
        is False
    )
    assert hook("tool.started", {"tool_call_id": "call-inflight"}) is False
    unresolved = control.effects.list_unresolved(execution.execution_id)
    assert len(unresolved) == 1
    assert unresolved[0].metadata.get("kind") == "tool.before"
    assert unresolved[0].status is EffectStatus.DISPATCHED
    pausing = asyncio.run(
        control.request_pause(
            command_id="pause-uncertain-tool",
            execution_id=execution.execution_id,
            expected_version=store.get_execution(execution.execution_id).status_version,
            actor={"surface": "test"},
        )
    )
    finished = control.finish_attempt(
        attempt_id=active.attempt_id,
        generation=active.generation,
        expected_execution_version=pausing.execution.status_version,
        target=ExecutionStatus.COMPLETED,
        outcome="completed",
        command_id="pause-uncertain-tool",
    )
    assert finished.execution.status is ExecutionStatus.RECONCILIATION_REQUIRED
    assert finished.command is not None
    assert finished.command.status is CommandStatus.APPLYING
    still = control.effects.get(unresolved[0].effect_id)
    assert still is not None and still.status is EffectStatus.DISPATCHED


def test_legacy_checkpoint_continue_keeps_completed_tool_history(tmp_path):
    from openprogram.runtime.execution.agent_checkpoint import (
        AgentCheckpointV1,
        canonical_json_bytes,
        decode_turn_display,
    )
    from openprogram.runtime.conversation.checkpoint import AgentContinuation
    from openprogram.runtime.execution.checkpoints import ExecutionCheckpointStore
    from openprogram.runtime.execution.effects import (
        EffectClassification,
        EffectStatus,
        EffectStore,
    )
    from openprogram.runtime.execution.projections import ExecutionProjectionReadModel
    from openprogram.models.providers.types import (
        AssistantMessage,
        TextContent,
        ToolCall,
        ToolResultMessage,
    )

    store, _attempts, control, driver, request, snapshot, execution, active, _hook = (
        _prepare_long_turn(tmp_path, "exec-legacy-display")
    )
    decision = AssistantMessage(
        content=[
            ToolCall(id="call-finished", name="web_use", arguments={"n": "old"}),
            ToolCall(id="call-pending", name="web_use", arguments={"n": "suffix"}),
        ],
        api="fake",
        provider="fake",
        model="fake",
        timestamp=1,
        stop_reason="toolUse",
    )
    finished_result = ToolResultMessage(
        tool_call_id="call-finished",
        tool_name="web_use",
        content=[TextContent(text="second:ok")],
        timestamp=1,
    )
    effects = EffectStore(store)
    provider = effects.register(
        effect_id="effect_legacy_provider",
        execution_id=execution.execution_id,
        attempt_id=active.attempt_id,
        action_id="provider-legacy",
        classification=EffectClassification.IDEMPOTENT,
        idempotency_key="provider-legacy",
        metadata={"kind": "provider.before"},
    )
    effects.mark_dispatched(provider.effect_id, expected_status=EffectStatus.PLANNED)
    effects.resolve(
        provider.effect_id,
        expected_status=EffectStatus.DISPATCHED,
        outcome=EffectStatus.COMMITTED,
        receipt={"provider_request_id": "legacy-provider"},
        attempt_id=active.attempt_id,
        generation=active.generation,
    )
    tool_effect = effects.register(
        effect_id="effect_legacy_tool",
        execution_id=execution.execution_id,
        attempt_id=active.attempt_id,
        action_id="tool-finished-legacy",
        classification=EffectClassification.NONREPEATABLE,
        idempotency_key=None,
        metadata={"kind": "tool.before"},
    )
    effects.mark_dispatched(tool_effect.effect_id, expected_status=EffectStatus.PLANNED)
    pausing = asyncio.run(
        control.request_pause(
            command_id="pause-legacy-display",
            execution_id=execution.execution_id,
            expected_version=store.get_execution(execution.execution_id).status_version,
            actor={"surface": "test"},
        )
    )
    terminal_receipt = {
        "tool_call_id": "call-finished",
        "is_error": False,
        "result_hash": "legacy",
    }
    legacy = AgentCheckpointV1.build(
        safe_point={
            "kind": "agent.tool.action.after",
            "step_id": "after_tool:tool-finished-legacy",
            "phase": "after_tool",
            "sentinel": "resume-from-checkpoint",
        },
        frontier=[
            {
                "step_id": "after_tool:tool-finished-legacy",
                "phase": "after_tool",
                "branch_id": "main",
            }
        ],
        turn={
            "user_message_id": "user-anchor",
            "assistant_message_id": "user-anchor_reply",
            "base_history_head_id": "user-anchor",
        },
        assistant_message=decision.model_dump(mode="json"),
        tool_results=[finished_result.model_dump(mode="json")],
        resolved_snapshot=snapshot,
        provider_action_id="provider-legacy",
        tool_call_ids=["call-finished", "call-pending"],
        next_tool_index=1,
        repeat_failures={},
        completed_actions=[
            {
                "action_id": "provider-legacy",
                "input_hash": "legacy-context",
                "result": decision.model_dump(mode="json"),
            },
            {
                "action_id": "tool-finished-legacy",
                "input_hash": "legacy-tool",
                "result": finished_result.model_dump(mode="json"),
            },
        ],
        terminal_effect_receipts=[
            {
                "effect_id": "effect_legacy_provider",
                "frontier_step_id": "after_provider:provider-legacy",
                "action_id": "provider-legacy",
                "outcome": "committed",
                "receipt": {"provider_request_id": "legacy-provider"},
            },
            {
                "effect_id": "effect_legacy_tool",
                "frontier_step_id": "after_tool:tool-finished-legacy",
                "action_id": "tool-finished-legacy",
                "outcome": "committed",
                "receipt": dict(terminal_receipt),
            },
        ],
    )
    assert "turn_display_ref" not in legacy.payload
    control.commit_agent_safe_point(
        execution_id=execution.execution_id,
        attempt_id=active.attempt_id,
        generation=active.generation,
        expected_version=pausing.execution.status_version,
        safe_point_kind="agent.tool.action.after",
        frontier=tuple(legacy.payload["frontier"]),
        state_refs={},
        effect_id=tool_effect.effect_id,
        terminal_receipt=terminal_receipt,
        receipt_blob=canonical_json_bytes(terminal_receipt),
        agent_checkpoint=legacy,
        command_id="pause-legacy-display",
        managed_action_id="tool-finished-legacy",
    )
    paused = store.get_execution(execution.execution_id)
    assert paused is not None and paused.status is ExecutionStatus.PAUSED
    seeded = decode_turn_display(
        AgentCheckpointV1.load(
            store, ExecutionCheckpointStore(store).get(paused.checkpoint_head_id)
        ),
        store=store,
        execution_id=execution.execution_id,
    )
    finished_card = next(
        block for block in seeded if block.get("tool_call_id") == "call-finished"
    )
    pending_card = next(
        block for block in seeded if block.get("tool_call_id") == "call-pending"
    )
    assert finished_card.get("result") == "second:ok"
    assert "result" not in pending_card
    assert "declined" not in str(pending_card)
    assert "expired" not in str(pending_card)

    captured = {}

    async def activate(attempt, activation):
        captured["attempt"] = attempt
        captured["activation"] = activation

    continued = asyncio.run(
        control.request_continue(
            command_id="continue-legacy-display",
            execution_id=execution.execution_id,
            expected_version=paused.status_version,
            actor={"surface": "test"},
            activator=activate,
        )
    )
    assert continued.command.status is CommandStatus.APPLIED
    continuation = AgentContinuation.from_checkpoint(
        store=store,
        checkpoint=captured["activation"].checkpoint,
        request=request,
    )
    assert "turn_display_ref" not in continuation.state.payload
    hook = driver._safe_point_hook(
        captured["attempt"],
        request,
        threading.Event(),
        continuation=continuation,
    )
    assert (
        hook(
            "tool.before",
            {
                "tool_call_id": "call-pending",
                "arguments": {"n": "suffix"},
            },
        )
        is False
    )
    assert (
        hook(
            "tool.after",
            {
                "tool_call_id": "call-pending",
                "is_error": False,
                "result": {
                    "role": "toolResult",
                    "tool_call_id": "call-pending",
                    "content": [{"type": "text", "text": "suffix-ok"}],
                },
                "tool_call_ids": ["call-finished", "call-pending"],
                "next_tool_index": 2,
            },
        )
        is False
    )
    _provider_tool_decision(hook, snapshot, "new")
    assert (
        hook(
            "provider.before",
            {
                "resolved_snapshot": snapshot,
                "context": {"messages": ["legacy-pause"]},
                "supports_idempotency_key": True,
            },
        )
        is False
    )
    asyncio.run(
        control.request_pause(
            command_id="pause-after-legacy-continue",
            execution_id=execution.execution_id,
            expected_version=store.get_execution(execution.execution_id).status_version,
            actor={"surface": "test"},
        )
    )
    assert (
        hook(
            "provider.after",
            {
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "done"}],
                    "api": "fake",
                    "provider": "fake",
                    "model": "fake",
                    "timestamp": 1,
                },
                "provider_request_id": "after-legacy",
                "usage": {},
                "tool_call_ids": [],
                "next_tool_index": 0,
            },
        )
        is True
    )
    paused_again = store.get_execution(execution.execution_id)
    assert paused_again is not None and paused_again.status is ExecutionStatus.PAUSED
    new_state = AgentCheckpointV1.load(
        store,
        ExecutionCheckpointStore(store).get(paused_again.checkpoint_head_id),
    )
    assert "turn_display_ref" in new_state.payload
    display = new_state.read_json_ref(
        store,
        execution.execution_id,
        new_state.payload["turn_display_ref"],
    )
    assert any(
        block.get("tool_call_id") == "call-finished"
        and block.get("result") == "second:ok"
        for block in display
    )
    assert any(
        block.get("tool_call_id") == "call-pending"
        and block.get("result") == "suffix-ok"
        for block in display
    )
    assert any(
        block.get("tool_call_id") == "call-new" and block.get("result") == "clicked-new"
        for block in display
    )
    projected = ExecutionProjectionReadModel(store)._checkpoint_blocks(
        paused_again,
        new_state.payload["turn"]["assistant_message_id"],
    )
    assert any(
        block.get("tool_call_id") == "call-finished"
        and block.get("result") == "second:ok"
        for block in projected
    )
    assert any(
        block.get("tool_call_id") == "call-new" and block.get("result") == "clicked-new"
        for block in projected
    )
    tool_ids = _committed_tool_ids(store, execution.execution_id)
    assert tool_ids.count("tool-finished-legacy") == 1
    assert len(tool_ids) == len(set(tool_ids))


def test_function_suspension_retains_pending_agent_tool_slot(tmp_path, monkeypatch):
    import importlib

    importlib.import_module(
        "openprogram.runtime.agent.call_state"
    )
    monkeypatch.setattr(program_runtime, "_registry", dict(program_runtime._registry))
    from openprogram.runtime.conversation.checkpoint import AgentContinuation
    from openprogram.runtime.execution.checkpoints import ExecutionCheckpointStore

    store, attempts, control, driver, request, snapshot, execution, active, hook = (
        _prepare_long_turn(tmp_path, "function-slot")
    )
    hook(
        "provider.before", {"resolved_snapshot": snapshot, "context": {"messages": []}}
    )
    hook(
        "provider.after",
        {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "toolCall",
                        "id": "function-call",
                        "name": "web_use",
                        "arguments": {},
                    }
                ],
                "api": "fake",
                "provider": "fake",
                "model": "fake",
                "timestamp": 1,
            },
            "tool_call_ids": ["function-call"],
            "next_tool_index": 0,
        },
    )
    hook(
        "tool.before",
        {"tool_call_id": "function-call", "tool_name": "web_use", "arguments": {}},
    )
    hook("tool.started", {"tool_call_id": "function-call"})
    from openprogram import Agent
    from openprogram.runtime.agent.durable_steps import function_execution

    def completed_function():
        return "saved result"

    class RegisteredProgram1Agent(Agent):
        method_options = {
            "run": {
                "name": "web_use",
                "as_tool": False,
                "resumable": True,
                "tool": True,
            }
        }
        run = staticmethod(completed_function)

    durable = RegisteredProgram1Agent().run
    with function_execution(
        store,
        attempt_id=active.attempt_id,
        generation=active.generation,
        call_key="function-call",
        checkpoint_root=False,
    ):
        durable()
    asyncio.run(
        control.request_pause(
            command_id="pause-function",
            execution_id=execution.execution_id,
            expected_version=store.get_execution(execution.execution_id).status_version,
            actor={"surface": "test"},
        )
    )
    assert (
        hook(
            "tool.suspended",
            {
                "tool_call_id": "function-call",
                "tool_name": "web_use",
                "next_tool_index": 0,
                "tool_call_ids": ["function-call"],
            },
        )
        is True
    )
    paused = store.get_execution(execution.execution_id)
    assert paused.status is ExecutionStatus.PAUSED
    checkpoint = ExecutionCheckpointStore(store).get(paused.checkpoint_head_id)
    continuation = AgentContinuation.from_checkpoint(
        store=store, checkpoint=checkpoint, request=request
    )
    assert continuation.tool_results == ()
    assert continuation.next_tool_index == 0
    captured = {}

    async def activate(attempt, activation):
        captured["attempt"] = attempt

    asyncio.run(
        control.request_continue(
            command_id="resume-function",
            execution_id=execution.execution_id,
            expected_version=paused.status_version,
            actor={"surface": "test"},
            activator=activate,
        )
    )
    resumed_hook = driver._safe_point_hook(
        captured["attempt"], request, threading.Event(), continuation=continuation
    )
    assert (
        resumed_hook(
            "tool.before",
            {"tool_call_id": "function-call", "tool_name": "web_use", "arguments": {}},
        )
        is False
    )


# Owned synchronous steps exercise the same admission boundary as GUI operations.
def _pause_admission_write(folder, value):
    with (Path(folder) / "dispatches").open("a") as stream:
        stream.write(value + "\n")
    return value


def _pause_admission_program(folder):
    from openprogram.runtime.agent.durable_steps import step

    first = step("first", _pause_admission_write, folder, "first")
    second = step("second", _pause_admission_write, folder, "second")
    return first + second


def _pause_admission_owner(tmp_path, monkeypatch, program_fn=_pause_admission_program):
    import importlib

    from openprogram.runtime.execution import RuntimeControlService
    from openprogram.runtime.execution.driver import DriverRegistry
    from openprogram import Agent

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENPROGRAM_CONFIG_DIR", str(tmp_path / ".openprogram"))
    module = importlib.import_module("openprogram.programs._host.runtime")
    monkeypatch.setattr(module, "_registry", dict(module._registry))
    store = ExecutionStore(tmp_path / "function.db")
    revision = store.create_revision(manifest={"entrypoint": "pause-admission"})
    execution = store.create_execution(
        session_id="owned-session",
        revision_id=revision.revision_id,
        capabilities=CapabilitySet(
            pause=True,
            safe_point_kinds=("function.step.after",),
            state_schema_version=1,
        ),
    )
    attempts = AttemptStore(store)
    leased, execution = attempts.lease(
        execution.execution_id,
        expected_version=execution.status_version,
        owner_id="owned-function",
        ttl_seconds=30,
    )
    active, execution = attempts.activate(
        leased.attempt_id,
        generation=leased.generation,
        expected_execution_version=execution.status_version,
    )

    class RegisteredProgram2Agent(Agent):
        method_options = {
            "run": {
                "name": "pause-admission",
                "resumable": True,
                "as_tool": False,
                "tool": True,
            }
        }
        run = staticmethod(program_fn)

    program = RegisteredProgram2Agent().run
    return (
        store,
        active,
        RuntimeControlService(store, attempts, DriverRegistry()),
        program,
    )


def _pause_admission_effects(store, execution_id):
    from openprogram.runtime.execution.effects import EffectStore

    with store._connect() as connection:
        rows = connection.execute(
            "SELECT * FROM effects WHERE execution_id = ? ORDER BY created_at",
            (execution_id,),
        ).fetchall()
    return [EffectStore(store)._record(row) for row in rows]


def test_function_pause_racing_admission_resumes_same_cursor_once(
    tmp_path, monkeypatch
):
    import pytest

    from openprogram.runtime.agent.durable_steps import (
        FunctionSuspended,
        function_execution,
    )
    from openprogram.runtime.execution.effects import EffectStore, EffectStatus

    # Repeat both deterministic scheduling windows with isolated owners.
    for window in ("register", "mark_dispatched"):
        with monkeypatch.context() as scoped:
            folder = tmp_path / window
            folder.mkdir()
            store, active, control, program = _pause_admission_owner(folder, scoped)
            original = getattr(EffectStore, window)
            pauses = []

            def before_admission(self, *args, **kwargs):
                step = (
                    kwargs["metadata"]["function_step"]["step"]
                    if window == "register"
                    else self.get(args[0]).metadata["function_step"]["step"]
                )
                if step == "second" and not pauses:
                    pauses.append(step)
                    current = store.get_execution(active.execution_id)
                    asyncio.run(
                        control.request_pause(
                            command_id="owned-pause",
                            execution_id=current.execution_id,
                            expected_version=current.status_version,
                            actor={"surface": "test"},
                        )
                    )
                return original(self, *args, **kwargs)

            scoped.setattr(EffectStore, window, before_admission)
            with pytest.raises(FunctionSuspended) as suspended:
                with function_execution(
                    store,
                    attempt_id=active.attempt_id,
                    generation=active.generation,
                    call_key="same-call",
                ):
                    program(str(folder))
            assert type(suspended.value) is FunctionSuspended
            paused = store.get_execution(active.execution_id)
            assert paused.status is ExecutionStatus.PAUSED
            assert (folder / "dispatches").read_text().splitlines() == ["first"]
            effects = _pause_admission_effects(store, active.execution_id)
            assert effects[0].status is EffectStatus.COMMITTED
            assert not EffectStore(store).list_unresolved(active.execution_id)
            if window == "mark_dispatched":
                intent = effects[1]
                assert intent.status is EffectStatus.NOT_COMMITTED
                assert intent.attempt_id == active.attempt_id
                assert intent.receipt == {
                    "outcome": "not_started",
                    "execution_started": False,
                    "pause_before_dispatch": True,
                }
            else:
                assert len(effects) == 1
            asyncio.run(
                control.request_continue(
                    command_id="owned-continue",
                    execution_id=paused.execution_id,
                    expected_version=paused.status_version,
                    actor={"surface": "test"},
                )
            )
            resumed = store.get_execution(active.execution_id)
            for _ in range(2):
                with function_execution(
                    store,
                    attempt_id=resumed.current_attempt_id,
                    generation=resumed.owner_lease["generation"],
                    call_key="same-call",
                ):
                    assert program(str(folder)) == "firstsecond"
            assert (folder / "dispatches").read_text().splitlines() == [
                "first",
                "second",
            ]
            assert [
                e.status for e in _pause_admission_effects(store, active.execution_id)
            ].count(EffectStatus.COMMITTED) == 2


def test_function_cancel_wins_admission_pause_race(tmp_path, monkeypatch):
    import pytest

    from openprogram.runtime.agent.durable_steps import function_execution
    from openprogram.host.cancellation import CancelledError
    from openprogram.runtime.execution.effects import EffectStore, EffectStatus

    for window in ("register", "mark_dispatched"):
        with monkeypatch.context() as scoped:
            folder = tmp_path / window
            folder.mkdir()
            store, active, control, program = _pause_admission_owner(folder, scoped)
            original = getattr(EffectStore, window)

            def cancel_before_admission(self, *args, **kwargs):
                current = store.get_execution(active.execution_id)
                asyncio.run(
                    control.request_pause(
                        command_id="pause",
                        execution_id=current.execution_id,
                        expected_version=current.status_version,
                        actor={"surface": "test"},
                    )
                )
                current = store.get_execution(active.execution_id)
                asyncio.run(
                    control.request_cancel(
                        command_id="cancel",
                        execution_id=current.execution_id,
                        expected_version=current.status_version,
                        actor={"surface": "test"},
                        reason_code="user_cancel",
                    )
                )
                return original(self, *args, **kwargs)

            scoped.setattr(EffectStore, window, cancel_before_admission)
            with pytest.raises(CancelledError):
                with function_execution(
                    store,
                    attempt_id=active.attempt_id,
                    generation=active.generation,
                    call_key="cancelled-call",
                ):
                    program(str(folder))
            assert (
                store.get_execution(active.execution_id).status
                is ExecutionStatus.CANCELLING
            )
            assert not (folder / "dispatches").exists()
            effects = _pause_admission_effects(store, active.execution_id)
            assert all(e.status is EffectStatus.NOT_COMMITTED for e in effects)
            assert all(e.receipt["pause_before_dispatch"] is False for e in effects)


def test_function_unrelated_admission_conflicts_are_not_suspensions(
    tmp_path, monkeypatch
):
    import pytest

    from openprogram.runtime.agent.durable_steps import function_execution
    from openprogram.runtime.execution.effects import EffectStore, EffectConflict

    for code in ("admission_closed", "idempotency_collision", "stale_attempt"):
        with monkeypatch.context() as scoped:
            folder = tmp_path / code
            folder.mkdir()
            store, active, _control, program = _pause_admission_owner(folder, scoped)
            conflict = EffectConflict(code, "owned non-pause failure")

            def fail_registration(self, **kwargs):
                raise conflict

            scoped.setattr(EffectStore, "register", fail_registration)
            with pytest.raises(EffectConflict) as caught:
                with function_execution(
                    store,
                    attempt_id=active.attempt_id,
                    generation=active.generation,
                    call_key="failed-call",
                ):
                    program(str(folder))
            assert caught.value is conflict
            assert (
                store.get_execution(active.execution_id).status
                is ExecutionStatus.RUNNING
            )
            assert not (folder / "dispatches").exists()


def test_function_pause_after_dispatch_keeps_committed_effect(tmp_path, monkeypatch):
    import pytest

    from openprogram.runtime.agent.durable_steps import (
        FunctionSuspended,
        function_execution,
    )
    from openprogram.runtime.execution.effects import EffectStore, EffectStatus

    store, active, control, program = _pause_admission_owner(tmp_path, monkeypatch)
    original = EffectStore.mark_dispatched
    pauses = []

    def pause_after_admission(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if not pauses:
            pauses.append(result.effect_id)
            current = store.get_execution(active.execution_id)
            asyncio.run(
                control.request_pause(
                    command_id="after-dispatch",
                    execution_id=current.execution_id,
                    expected_version=current.status_version,
                    actor={"surface": "test"},
                )
            )
        return result

    monkeypatch.setattr(EffectStore, "mark_dispatched", pause_after_admission)
    with pytest.raises(FunctionSuspended):
        with function_execution(
            store,
            attempt_id=active.attempt_id,
            generation=active.generation,
            call_key="after-call",
        ):
            program(str(tmp_path))
    effects = _pause_admission_effects(store, active.execution_id)
    assert len(effects) == 1 and effects[0].status is EffectStatus.COMMITTED
    assert "pause_before_dispatch" not in effects[0].receipt
    assert (tmp_path / "dispatches").read_text().splitlines() == ["first"]


def test_function_stale_owner_at_registration_still_fails(tmp_path, monkeypatch):
    import pytest

    from openprogram.runtime.agent.durable_steps import function_execution
    from openprogram.runtime.execution.effects import EffectConflict, EffectStore

    store, active, _control, program = _pause_admission_owner(tmp_path, monkeypatch)
    original = EffectStore.register

    def finish_owner_before_registration(self, **kwargs):
        current = store.get_execution(active.execution_id)
        AttemptStore(store).finish(
            active.attempt_id,
            generation=active.generation,
            expected_execution_version=current.status_version,
            target=ExecutionStatus.FAILED,
            outcome="owned test owner ended",
        )
        return original(self, **kwargs)

    monkeypatch.setattr(EffectStore, "register", finish_owner_before_registration)
    with pytest.raises(EffectConflict) as caught:
        with function_execution(
            store,
            attempt_id=active.attempt_id,
            generation=active.generation,
            call_key="stale-call",
        ):
            program(str(tmp_path))
    assert caught.value.code == "stale_attempt"
    assert store.get_execution(active.execution_id).status is ExecutionStatus.FAILED
    assert not (tmp_path / "dispatches").exists()


def _pause_admission_unknown_write(folder):
    _pause_admission_write(folder, "unconfirmed")
    raise RuntimeError("owned connection lost before receipt")


def _pause_admission_unknown_program(folder):
    from openprogram.runtime.agent.durable_steps import step

    return step("unknown", _pause_admission_unknown_write, folder)


def test_function_pause_after_dispatch_keeps_unknown_effect_for_reconciliation(
    tmp_path, monkeypatch
):
    import pytest

    from openprogram.runtime.agent.durable_steps import function_execution
    from openprogram.runtime.execution.effects import EffectStore, EffectStatus
    from openprogram.runtime.execution.state_machine import InvalidCommand

    store, active, control, program = _pause_admission_owner(
        tmp_path,
        monkeypatch,
        _pause_admission_unknown_program,
    )
    original = EffectStore.mark_dispatched

    def pause_after_admission(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        current = store.get_execution(active.execution_id)
        asyncio.run(
            control.request_pause(
                command_id="pause-unknown",
                execution_id=current.execution_id,
                expected_version=current.status_version,
                actor={"surface": "test"},
            )
        )
        return result

    monkeypatch.setattr(EffectStore, "mark_dispatched", pause_after_admission)
    with pytest.raises(RuntimeError, match="owned connection lost"):
        with function_execution(
            store,
            attempt_id=active.attempt_id,
            generation=active.generation,
            call_key="unknown-call",
        ):
            program(str(tmp_path))
    effects = _pause_admission_effects(store, active.execution_id)
    assert len(effects) == 1 and effects[0].status is EffectStatus.DISPATCHED
    assert not effects[0].receipt
    recovered = control.recover_owner_loss(
        active.execution_id,
        attempt_id=active.attempt_id,
        generation=active.generation,
    )
    assert recovered.execution.status is ExecutionStatus.RECONCILIATION_REQUIRED
    with pytest.raises(InvalidCommand):
        asyncio.run(
            control.request_continue(
                command_id="cannot-replay",
                execution_id=active.execution_id,
                expected_version=recovered.execution.status_version,
                actor={"surface": "test"},
            )
        )
    assert (tmp_path / "dispatches").read_text().splitlines() == ["unconfirmed"]
    assert (
        _pause_admission_effects(store, active.execution_id)[0].status
        is EffectStatus.DISPATCHED
    )


def test_app_control_granted_before_the_boundary_still_records_the_tool_intent(
    tmp_path, monkeypatch
):
    """The manifest captured with the tool list said "waiting"; access was
    granted by the time the tool reached its boundary. No wait opens, and
    tool.started finds the dispatch intent like for any other tool."""

    from openprogram.host import system_access
    from openprogram.runtime.conversation.checkpoint import runtime_contract_snapshot
    from openprogram.runtime.agent.turn_request import TurnRequest
    from openprogram.runtime.conversation.production_driver import AgentProductionDriver
    from openprogram.runtime.execution.control import RuntimeControlService
    from openprogram.runtime.execution.driver import DriverRegistry
    from openprogram.runtime.execution.effects import EffectStore
    from openprogram.runtime.execution.waits import DurableWaitStore
    from openprogram.models.providers.types import Model

    store, execution = _admitted(tmp_path, execution_id="exec-system-granted")
    attempts = AttemptStore(store)
    leased, reserved = attempts.lease(
        execution.execution_id,
        expected_version=execution.status_version,
        owner_id="system-granted",
        ttl_seconds=30,
    )
    active, running = attempts.activate(
        leased.attempt_id,
        generation=leased.generation,
        expected_execution_version=reserved.status_version,
    )
    control = RuntimeControlService(store, attempts, DriverRegistry())
    driver = AgentProductionDriver(store, control_service=control)
    request = TurnRequest(
        session_id=running.session_id,
        user_text="run GUI",
        agent_id="default",
        source="component",
        user_msg_id="user-system-granted",
    )
    request._execution_revision_id = running.revision_id
    hook = driver._safe_point_hook(active, request, threading.Event())
    snapshot = runtime_contract_snapshot(
        model=Model(
            id="fake", name="fake", api="openai-completions", provider="openai",
            base_url="https://example.invalid/v1",
        ),
        system_prompt="system", tools=[], request=request,
    )
    monkeypatch.setattr(system_access.platform, "system", lambda: "Darwin")
    not_granted = {
        "platform": "Darwin",
        "capabilities": [
            {"id": "screen_recording", "status": "not_granted", "can_request": True},
            {"id": "accessibility", "status": "not_granted", "can_request": True},
        ],
    }
    monkeypatch.setattr(system_access, "report", lambda: not_granted)
    args = {"target": "app", "action": "click", "args": {"app": "Notes", "element_index": 1}}
    manifest = system_access.access_manifest_for_tool("computer_use_agent", args)
    assert manifest is not None

    assert hook("provider.before", {
        "resolved_snapshot": snapshot, "context": {"messages": []},
        "supports_idempotency_key": True,
    }) is False
    assert hook("provider.after", {
        "message": {"role": "assistant", "content": [], "api": "fake", "provider": "fake", "model": "fake"},
        "provider_request_id": "request-system-granted", "usage": {},
    }) is False

    granted = {
        "platform": "Darwin",
        "capabilities": [
            {"id": "screen_recording", "status": "granted"},
            {"id": "accessibility", "status": "granted"},
        ],
    }
    monkeypatch.setattr(system_access, "report", lambda: granted)
    payload = {
        "tool_call_id": "gui-call", "tool_name": "computer_use_agent",
        "arguments": args, "next_tool_index": 0, "pre_wait": manifest,
    }
    assert hook("tool.before", payload) is False
    assert payload["pre_wait"] is None
    assert DurableWaitStore(store).list_open(execution_id=execution.execution_id) == []
    assert hook("tool.started", {"tool_call_id": "gui-call"}) is False
    assert [
        effect.metadata.get("kind")
        for effect in EffectStore(store).list_unresolved(execution.execution_id)
    ] == ["tool.before"]
