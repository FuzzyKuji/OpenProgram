"""Unknown prior effects require new, exact approval even in bypass mode."""
import asyncio

import pytest

from openprogram.runtime.permissions.authority import local_owner_authority
from openprogram.runtime.agent.turn_request import TurnRequest
from openprogram.runtime.permissions.approval import wrap_with_approval
from openprogram.models.providers.types import AgentTool, AgentToolResult
from openprogram.runtime.execution.attempts import AttemptStore
from openprogram.runtime.execution.control import RuntimeControlService
from openprogram.runtime.execution.driver import DriverRegistry
from openprogram.runtime.execution.effects import EffectClassification, EffectStatus, EffectStore
from openprogram.runtime.execution.store import ExecutionStore


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    store = ExecutionStore(tmp_path / "executions.sqlite3")
    monkeypatch.setattr("openprogram.runtime.execution.default_store", lambda: store)
    monkeypatch.setattr("openprogram.runtime.permissions.rule.load_merged_rules", lambda _: None)
    return store


def orphan(store, *, session="recovery", name="bash", parent=None, kind="tool.before", caller=None):
    revision = store.create_revision(manifest={"entrypoint": "chat"})
    if caller:
        import hashlib
        import json
        from openprogram.runtime.jobs.input import JobAgentInputV1
        from openprogram.runtime.jobs.types import Job

        job = Job(id="called-job", parent_session_id=session, prompt="inspect", agent_id="main",
                  caller_session_id=caller, caller_msg_id="caller-message")
        payload = JobAgentInputV1.from_job(job).to_dict()
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        execution = store.admit_execution(session_id=session, revision_id=revision.revision_id,
            input_ref="job-input-v1:" + serialized,
            input_hash=hashlib.sha256(serialized.encode()).hexdigest(),
            entrypoint="openprogram.runtime.conversation.production_driver:AgentProductionDriver",
            trusted_actor=local_owner_authority(), config_snapshot_ref="config:test",
            job_agent_payload=payload)
    else:
        execution = store.create_execution(
            session_id=session, revision_id=revision.revision_id,
            parent_execution_id=parent,
        )
    attempts = AttemptStore(store)
    leased, reserved = attempts.lease(
        execution.execution_id, expected_version=execution.status_version,
        owner_id="old-worker", ttl_seconds=30,
    )
    active, running = attempts.activate(
        leased.attempt_id, generation=leased.generation,
        expected_execution_version=reserved.status_version,
    )
    effects = EffectStore(store)
    effect = effects.register(
        effect_id=f"effect:{execution.execution_id}", execution_id=execution.execution_id,
        attempt_id=active.attempt_id, action_id="old-call",
        classification=EffectClassification.NONREPEATABLE, idempotency_key=None,
        metadata={"kind": kind, "payload": {"tool_name": name, "tool_call_id": "old-call"}},
    )
    effects.mark_dispatched(effect.effect_id, expected_status=EffectStatus.PLANNED)
    RuntimeControlService(store, attempts, DriverRegistry()).recover_owner_loss(execution.execution_id)
    return execution, effect


def operation(name="bash", *, mode="bypass", source="web", session="recovery"):
    calls = []

    async def execute(*args):
        calls.append(args)
        return AgentToolResult(content=[], details={})

    tool = AgentTool(name=name, label=name, description="test", parameters={}, execute=execute)
    req = TurnRequest(session_id=session, user_text="continue", agent_id="main",
                      source=source, permission_mode=mode, **local_owner_authority())
    return tool, req, calls


@pytest.mark.parametrize("name", ["bash", "read", "memory_update"])
@pytest.mark.parametrize("mode", ["bypass", "auto", "acceptEdits"])
def test_unknown_effect_overrides_automatic_permissions(recovery, name, mode):
    _, effect = orphan(recovery)
    tool, req, calls = operation(name, mode=mode)
    tool._accept_edits_safe = True
    wrapped = wrap_with_approval(tool, req, lambda _: None)
    manifest = wrapped._interaction_manifest("new-call", {})
    assert manifest is not None
    assert manifest["request_metadata"]["approval_reason"] == "RECOVERY_EFFECT_UNCERTAIN"
    assert manifest["policy_snapshot"]["allowed_scopes"] == ["once"]
    assert effect.effect_id in str(manifest["request_metadata"]["recovery_effects"])
    assert "unknown" in manifest["detail"].lower()
    assert calls == []


def test_real_builtin_inspection_not_name_or_copied_flags(recovery, tmp_path):
    import copy
    from openprogram.programs.tools.files.read import read
    from openprogram.runtime.permissions.policy import permission_decision

    orphan(recovery)
    _, req, _ = operation()
    assert permission_decision(read, req, {})[0] == "allow"
    copied = copy.copy(read)
    assert permission_decision(copied, req, {})[0] == "allow"
    fake, _, _ = operation("read")
    copied.execute = fake.execute
    assert permission_decision(copied, req, {})[:2] == ("ask", "RECOVERY_EFFECT_UNCERTAIN")
    target = tmp_path / "inspect.txt"
    target.write_text("saved result", encoding="utf-8")
    wrapped = wrap_with_approval(read, req, lambda _: None)
    result = asyncio.run(wrapped.execute("inspect", {"file_path": str(target)}, None, None))
    assert not result.is_error
    assert "saved result" in str(result.content)


def test_denies_and_noninteractive_authority_remain_stronger(recovery):
    from openprogram.runtime.permissions.policy import permission_decision
    from openprogram.runtime.permissions.modes import PermissionRules

    orphan(recovery)
    tool, req, _ = operation()
    req.permission_rules = PermissionRules(deny=["bash"])
    assert permission_decision(tool, req, {})[:2] == ("deny", "PERMISSION_RULE_DENY")
    req.permission_rules = PermissionRules(allow=["bash"])
    assert permission_decision(tool, req, {})[:2] == ("ask", "RECOVERY_EFFECT_UNCERTAIN")
    req.source = "agent_spawn"
    assert permission_decision(tool, req, {})[:2] == ("deny", "APPROVAL_UNAVAILABLE_NON_INTERACTIVE")


def test_conversation_descendants_but_not_unrelated_session(recovery):
    from openprogram.runtime.permissions.policy import permission_decision

    revision = recovery.create_revision(manifest={})
    parent = recovery.create_execution(session_id="recovery", revision_id=revision.revision_id)
    orphan(recovery, parent=parent.execution_id)
    tool, req, _ = operation()
    assert permission_decision(tool, req, {})[0] == "ask"
    req.session_id = "unrelated"
    assert permission_decision(tool, req, {})[0] == "allow"
    req.spawned_from_session = "recovery"
    assert permission_decision(tool, req, {})[0] == "ask"


def test_provider_only_and_resolved_effects_do_not_restrict_new_operations(recovery):
    from openprogram.runtime.permissions.policy import permission_decision

    orphan(recovery, kind="provider.before")
    tool, req, _ = operation()
    assert permission_decision(tool, req, {})[0] == "allow"
    _, effect = orphan(recovery)
    effects = EffectStore(recovery)
    effects.resolve(effect.effect_id, expected_status=EffectStatus.DISPATCHED,
                    outcome=EffectStatus.COMMITTED, receipt={"result": "verified"})
    assert permission_decision(tool, req, {})[0] == "allow"


def test_exact_called_job_not_its_entire_target_session(recovery):
    _, called = orphan(recovery, session="target", caller="recovery")
    _, unrelated = orphan(recovery, session="target")
    raw, req, _ = operation()
    manifest = wrap_with_approval(raw, req, lambda _: None)._interaction_manifest("new-call", {})
    ids = {item["effect_id"] for item in manifest["request_metadata"]["recovery_effects"]}
    assert ids == {called.effect_id}
    assert unrelated.effect_id not in str(manifest)


def test_unavailable_recovery_state_fails_closed(recovery, monkeypatch):
    def unavailable():
        raise OSError("unavailable")

    monkeypatch.setattr("openprogram.runtime.execution.default_store", unavailable)
    tool, req, calls = operation()
    result = asyncio.run(wrap_with_approval(tool, req, lambda _: None).execute("new", {}, None, None))
    assert result.details["reason_code"] == "RECOVERY_STATE_UNAVAILABLE"
    assert calls == []


def approve(store, manifest, *, scope="once"):
    import time
    from openprogram.runtime.execution.waits import DurableWaitStore

    revision = store.create_revision(manifest={})
    execution = store.create_execution(session_id="recovery", revision_id=revision.revision_id)
    attempts = AttemptStore(store)
    leased, reserved = attempts.lease(execution.execution_id, expected_version=execution.status_version,
                                      owner_id="new-worker", ttl_seconds=30)
    active, _ = attempts.activate(leased.attempt_id, generation=leased.generation,
                                  expected_execution_version=reserved.status_version)
    wait = DurableWaitStore(store).open_wait(execution_id=execution.execution_id,
        attempt_id=active.attempt_id, generation=active.generation, kind="approval",
        request={"prompt": manifest["prompt"], "options": manifest["options"], "multi": False,
                 "allow_custom": False, "detail": manifest["detail"], "schema": {}, "questions": [],
                 **manifest["request_metadata"]}, policy_snapshot=manifest["policy_snapshot"],
        expires_at=time.time() + 60)
    service = RuntimeControlService(store, attempts, DriverRegistry())
    asyncio.run(service.request_wait_answer(command_id="answer", execution_id=execution.execution_id,
        expected_version=store.get_execution(execution.execution_id).status_version,
        actor=local_owner_authority(), wait_id=wait.wait_id, generation=wait.claim_generation,
        answer={"answer": "approve", "scope": scope}))
    return wait


@pytest.mark.parametrize("change", [None, "extra_effect", "arguments", "old_approval"])
def test_durable_approval_binds_exact_uncertainty_and_operation(recovery, change):
    from openprogram.runtime.conversation.run_control import set_preapproved_wait_id, reset_preapproved_wait_id

    _, effect = orphan(recovery)
    raw, req, calls = operation()
    wrapped = wrap_with_approval(raw, req, lambda _: None)
    args = {"command": "perform explicitly approved work"}
    manifest = wrapped._interaction_manifest("new-call", args)
    if change == "old_approval":
        manifest["request_metadata"].pop("recovery_effects")
        manifest["request_metadata"]["approval_reason"] = "MODE_APPROVAL"
    wait = approve(recovery, manifest)
    if change == "extra_effect":
        orphan(recovery)
    if change == "arguments":
        args = {"command": "different work"}
    # A rebuilt wrapper consumes the persisted receipt, as after restart.
    restored = wrap_with_approval(raw, req, lambda _: None)
    token = set_preapproved_wait_id(wait.wait_id)
    try:
        result = asyncio.run(restored.execute("new-call", args, None, None))
    finally:
        reset_preapproved_wait_id(token)
    assert bool(calls) is (change is None), result
    assert result.is_error is (change is not None)
    assert EffectStore(recovery).get(effect.effect_id).status is EffectStatus.DISPATCHED


def test_always_scope_cannot_waive_uncertainty(recovery):
    from openprogram.runtime.execution.waits import DurableWaitStore
    from openprogram.runtime.execution.store import ExecutionConflict

    orphan(recovery)
    raw, req, _ = operation()
    manifest = wrap_with_approval(raw, req, lambda _: None)._interaction_manifest("new-call", {})
    with pytest.raises(ExecutionConflict, match="scope"):
        approve(recovery, manifest, scope="always")
    assert len(DurableWaitStore(recovery).list_open()) == 1


@pytest.mark.parametrize("mode", ["auto", "bypass"])
def test_new_owner_turn_uses_selected_policy_without_replaying_old_effect(recovery, mode):
    from openprogram.runtime.permissions.policy import permission_decision
    from openprogram.runtime.execution.run_control import (
        set_current_execution_id,
        reset_current_execution_id,
    )
    old, effect = orphan(recovery)
    revision = recovery.create_revision(manifest={})
    new = recovery.create_execution(session_id="recovery", revision_id=revision.revision_id)
    tool, req, _ = operation(mode=mode)
    token = set_current_execution_id(new.execution_id)
    try:
        assert permission_decision(tool, req, {})[0] == ("auto" if mode == "auto" else "allow")
        assert EffectStore(recovery).get(effect.effect_id).status is EffectStatus.DISPATCHED
    finally:
        reset_current_execution_id(token)
    token = set_current_execution_id(old.execution_id)
    try:
        assert permission_decision(tool, req, {})[:2] == ("ask", "RECOVERY_EFFECT_UNCERTAIN")
    finally:
        reset_current_execution_id(token)


def admit_owner_turn(store, request):
    """Real immutable admission, also used by the isolated process probe."""
    import hashlib
    import json
    from openprogram.state.authority import normalize_authority

    payload = {"version": 1, "kind": "chat", "request": {
        "user_text": request.user_text, "agent_id": request.agent_id,
        "source": request.source,
    }}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    revision = store.create_revision(manifest={"entrypoint": "chat"})
    return store.admit_execution(
        session_id=request.session_id, revision_id=revision.revision_id,
        input_ref="agent-turn:test", input_hash=hashlib.sha256(encoded.encode()).hexdigest(),
        entrypoint="openprogram.runtime.conversation.production_driver:AgentProductionDriver",
        trusted_actor=normalize_authority(request), config_snapshot_ref="config:test",
        agent_turn_payload=payload,
    )


@pytest.mark.parametrize("mode", ["auto", "bypass"])
def test_new_owner_runtime_excludes_only_old_uncertainty(recovery, mode):
    from openprogram.runtime.permissions.policy import permission_decision
    from openprogram.runtime.execution.run_control import (
        set_current_execution_id,
        reset_current_execution_id,
    )
    from openprogram.runtime.agent.turn_request import (
        set_turn_request,
        reset_turn_request,
        inner_turn_request,
    )
    from openprogram.runtime.agent.runtime import Runtime

    old, effect = orphan(recovery)
    tool, req, calls = operation("browser_page", mode=mode)
    new = admit_owner_turn(recovery, req)
    current = set_current_execution_id(new.execution_id)
    bound = set_turn_request(req)
    try:
        inner = inner_turn_request("program")
        assert (inner.speaker_kind, inner.interaction) == ("runtime", "non-interactive")
        assert permission_decision(tool, inner, {})[0] == ("auto" if mode == "auto" else "allow")
        if mode == "bypass":
            runtime = Runtime.__new__(Runtime)
            gated = runtime._gate_inner_tools([tool])[0]
            assert not asyncio.run(gated.execute("new", {}, None, None)).is_error
            assert len(calls) == 1
        from openprogram.runtime.permissions.modes import PermissionRules
        for rule in ("ask", "deny"):
            inner.permission_rules = PermissionRules(**{rule: ["browser_page"]})
            assert permission_decision(tool, inner, {})[:2] == (rule, "PERMISSION_RULE_" + rule.upper())
        inner.permission_rules = None
        # A current descendant's unknown outcome must still block this runtime.
        _, descendant = orphan(recovery, parent=new.execution_id)
        assert permission_decision(tool, inner, {})[:2] == ("ask", "RECOVERY_EFFECT_UNCERTAIN")
        result = asyncio.run(wrap_with_approval(tool, inner, lambda _: None).execute("blocked", {}, None, None))
        assert result.details["reason_code"] == "APPROVAL_LOCAL_OWNER_REQUIRED"
        assert EffectStore(recovery).get(effect.effect_id).status is EffectStatus.DISPATCHED
        assert EffectStore(recovery).get(descendant.effect_id).status is EffectStatus.DISPATCHED
    finally:
        reset_turn_request(bound)
        reset_current_execution_id(current)


@pytest.mark.parametrize("mismatch", ["missing", "principal", "session", "source", "actor", "hash"])
def test_runtime_recovery_requires_exact_owner_admission(recovery, mismatch):
    from openprogram.runtime.permissions.authority import runtime_authority
    from openprogram.runtime.permissions.policy import permission_decision
    from openprogram.runtime.execution.run_control import (
        set_current_execution_id,
        reset_current_execution_id,
    )

    orphan(recovery)
    tool, outer, _ = operation("browser_page", mode="auto")
    if mismatch == "actor":
        outer.interaction = "non-interactive"
        outer.speaker_kind = "runtime"
    if mismatch == "source":
        outer.source = "cron"
    new = admit_owner_turn(recovery, outer)
    inner = TurnRequest(session_id=outer.session_id, user_text="", agent_id="main", source="web",
                        permission_mode="auto", **runtime_authority(outer, "program"))
    if mismatch == "principal":
        inner.principal_id = "another-owner"
    if mismatch == "session":
        # Keep the hazard visible, while the claimed current execution belongs elsewhere.
        _, outer2, _ = operation(session="another-session")
        new = admit_owner_turn(recovery, outer2)
    if mismatch == "missing":
        new = recovery.create_execution(session_id="recovery", revision_id=new.revision_id)
    if mismatch == "hash":
        with recovery._connect() as connection:
            connection.execute("UPDATE execution_agent_turn_inputs SET content_hash='bad' WHERE execution_id=?", (new.execution_id,))
    token = set_current_execution_id(new.execution_id)
    try:
        expected = ("deny", "RECOVERY_STATE_UNAVAILABLE") if mismatch == "hash" else ("ask", "RECOVERY_EFFECT_UNCERTAIN")
        assert permission_decision(tool, inner, {})[:2] == expected
    finally:
        reset_current_execution_id(token)


def admit_owner_spawn(store, owner, parent_execution_id, *, session=None, principal=None):
    """A job admitted the way the agent tool's spawn is: the runtime speaker
    carrying the owner's tier, parented to the spawning execution."""
    import hashlib
    import json
    from openprogram.runtime.jobs.input import JobAgentInputV1
    from openprogram.runtime.jobs.types import Job
    from openprogram.runtime.permissions.authority import runtime_authority

    authority = runtime_authority(owner, "agent_spawn")
    if principal:
        authority["principal_id"] = principal
    job = Job(id=f"spawn-{parent_execution_id}", parent_session_id=session or owner.session_id,
              prompt="look", agent_id="main", caller_msg_id="caller-message", **authority)
    payload = JobAgentInputV1.from_job(job, parent_execution_id=parent_execution_id).to_dict()
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    revision = store.create_revision(manifest={"kind": "job"})
    return store.admit_execution(
        execution_id=job.id, parent_execution_id=parent_execution_id,
        session_id=job.parent_session_id, revision_id=revision.revision_id,
        input_ref="job-input-v1:" + serialized,
        input_hash=hashlib.sha256(serialized.encode()).hexdigest(),
        entrypoint="openprogram.runtime.conversation.production_driver:AgentProductionDriver",
        trusted_actor=authority, config_snapshot_ref="job-config:test",
        job_agent_payload=payload,
    )


def spawn_request(owner):
    from openprogram.runtime.permissions.authority import runtime_authority

    return TurnRequest(session_id=owner.session_id, user_text="look", agent_id="main",
                       source="agent_spawn", permission_mode="bypass",
                       **runtime_authority(owner, "agent_spawn"))


def test_owner_spawn_excludes_only_old_uncertainty(recovery):
    """An agent the owner's turn spawns cannot ask, so an abandoned earlier
    turn of the session must not deny it what its parent may do; a hazard
    under its own execution still does."""
    from openprogram.runtime.permissions.policy import permission_decision
    from openprogram.runtime.execution.run_control import (
        set_current_execution_id,
        reset_current_execution_id,
    )

    old, effect = orphan(recovery)
    tool, owner, _ = operation("browser_page")
    turn = admit_owner_turn(recovery, owner)
    spawn = admit_owner_spawn(recovery, owner, turn.execution_id)
    nested = admit_owner_spawn(recovery, owner, spawn.execution_id)
    req = spawn_request(owner)
    for current in (spawn, nested):
        token = set_current_execution_id(current.execution_id)
        try:
            assert permission_decision(tool, req, {})[:2] == ("allow", "BYPASS")
        finally:
            reset_current_execution_id(token)
    assert EffectStore(recovery).get(effect.effect_id).status is EffectStatus.DISPATCHED
    _, descendant = orphan(recovery, parent=spawn.execution_id)
    token = set_current_execution_id(spawn.execution_id)
    try:
        assert permission_decision(tool, req, {})[:2] == ("deny", "APPROVAL_UNAVAILABLE_NON_INTERACTIVE")
    finally:
        reset_current_execution_id(token)
    assert EffectStore(recovery).get(descendant.effect_id).status is EffectStatus.DISPATCHED


@pytest.mark.parametrize("mismatch", ["no_root", "cron_root", "runtime_root", "principal"])
def test_spawn_recovery_requires_an_owner_chat_at_the_chain_root(recovery, mismatch):
    from openprogram.runtime.permissions.policy import permission_decision
    from openprogram.runtime.execution.run_control import (
        set_current_execution_id,
        reset_current_execution_id,
    )

    orphan(recovery)
    tool, owner, _ = operation("browser_page")
    if mismatch == "cron_root":
        owner.source = "cron"
    if mismatch == "runtime_root":
        owner.interaction = "non-interactive"
        owner.speaker_kind = "runtime"
    if mismatch == "no_root":
        revision = recovery.create_revision(manifest={})
        root = recovery.create_execution(session_id="recovery", revision_id=revision.revision_id)
    else:
        root = admit_owner_turn(recovery, owner)
    spawn = admit_owner_spawn(recovery, owner, root.execution_id,
                              principal="another-owner" if mismatch == "principal" else None)
    req = spawn_request(owner)
    token = set_current_execution_id(spawn.execution_id)
    try:
        assert permission_decision(tool, req, {})[:2] == ("deny", "APPROVAL_UNAVAILABLE_NON_INTERACTIVE")
    finally:
        reset_current_execution_id(token)
