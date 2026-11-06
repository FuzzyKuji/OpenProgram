"""The Activity endpoint exposes a dispatched tool until it returns."""

def test_activity_shows_waiting_shell_and_removes_it_on_completion(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from openprogram.runtime.execution import ExecutionStore, CapabilitySet, AttemptStore
    from openprogram.runtime.execution.effects import EffectStore, EffectStatus, EffectClassification
    from openprogram.interfaces.server.routes.execution import processes

    monkeypatch.setattr('openprogram.state.paths.get_state_dir', lambda: tmp_path)
    store = ExecutionStore(tmp_path / 'executions.db')
    revision = store.create_revision(manifest={'entrypoint': 'workflow'})
    store.admit_execution(
        execution_id='run', run_id='run', session_id='session', revision_id=revision.revision_id,
        input_ref='input', input_hash='hash', entrypoint='workflow', trusted_actor={'subject': 'owner'},
        config_snapshot_ref='config', user_message_id='user', assistant_message_id='assistant', capabilities=CapabilitySet())
    attempts = AttemptStore(store)
    lease, reserved = attempts.lease('run', expected_version=1, owner_id='owner', ttl_seconds=60)
    attempt, running = attempts.activate(lease.attempt_id, generation=1, expected_execution_version=reserved.status_version)
    effects = EffectStore(store)
    effects.register(effect_id='shell', execution_id='run', attempt_id=attempt.attempt_id,
        action_id='shell', classification=EffectClassification.UNKNOWN, idempotency_key=None,
        metadata={'kind':'tool.before', 'payload':{'tool_call_id':'tool-one','tool_name':'bash','arguments':{'command':'sleep 30'}}})
    monkeypatch.setattr(processes, '_authorize', lambda *args, **kwargs: None)
    monkeypatch.setattr('openprogram.runtime.execution.default_store', lambda: store)
    monkeypatch.setattr('openprogram.runtime.execution.conversation_scope.conversation_executions', lambda *_: [running])
    app = FastAPI(); processes.register(app)
    with TestClient(app) as client:
        assert client.get('/api/session/session/processes').json()['calls'] == []
        effects.mark_dispatched('shell', expected_status=EffectStatus.PLANNED)
        result = client.get('/api/session/session/processes')
        assert result.status_code == 200
        call, = result.json()['calls']
        assert (call['name'],call['command'],call['status']) == ('bash','sleep 30','running')
        effects.resolve('shell', expected_status=EffectStatus.DISPATCHED, outcome=EffectStatus.COMMITTED,
            receipt={'result':'done'}, attempt_id=attempt.attempt_id,generation=1)
        assert client.get('/api/session/session/processes').json()['calls'] == []
