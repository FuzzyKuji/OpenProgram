"""A load that reports a running turn names it, and closes it if it ends mid-load."""
import asyncio
import json

from openprogram.state.store import SessionStore
from openprogram.interfaces.server.ws_actions import session as ws_session


def test_turn_ending_during_load_is_cleared_by_name(tmp_path, monkeypatch):
    from openprogram.interfaces.server import server
    sid = 'run-identity-chat'
    store = SessionStore(tmp_path / 'sessions')
    store.create_session(sid, 'main')
    store.append_message(sid, {'id': 'm1', 'role': 'user', 'content': 'hi', 'predecessor': None})
    store.update_session(sid, head_id='m1')
    monkeypatch.setattr('openprogram.runtime.context.session_db.default_db', lambda: store)
    monkeypatch.setattr(server, '_get_provider_info', lambda _sid=None: {})
    monkeypatch.setattr(server, '_is_run_active', lambda _sid: True)
    monkeypatch.setattr(server, '_canonical_foreground_task', lambda _sid: None)

    def turn_ends(_sid):
        # The turn finishes while the load is still in flight.
        with server._running_tasks_lock:
            server._running_tasks.pop(sid, None)
    monkeypatch.setattr(server, 'refresh_context_stats', turn_ends)

    class WS:
        def __init__(self):
            self.frames = []

        async def send_text(self, text):
            self.frames.append(json.loads(text))

    ws = WS()
    with server._sessions_lock:
        server._sessions[sid] = {'id': sid}
    with server._running_tasks_lock:
        server._running_tasks[sid] = {'msg_id': 'm1', 'execution_id': 'exec-1',
                                      'func_name': '_chat', 'started_at': 0}
    try:
        asyncio.run(ws_session.handle_load_session(ws, {'session_id': sid}))
        loaded = next(f['data'] for f in ws.frames if f['type'] == 'session_loaded')
        assert loaded['run_active'] is True
        assert loaded['run_task'] == {'msg_id': 'm1', 'execution_id': 'exec-1'}
        clears = [f['data'] for f in ws.frames if f['type'] == 'running_task_clear']
        # The clear read the run state after the load did, so its run_seq
        # orders it after the load's "running" on the client.
        assert [c.pop('run_seq') > loaded['run_seq'] for c in clears] == [True]
        assert clears == [{'session_id': sid, 'msg_id': 'm1', 'execution_id': 'exec-1'}]
        assert not any(f['type'] == 'running_task' for f in ws.frames)
    finally:
        with server._sessions_lock:
            server._sessions.pop(sid, None)
        with server._running_tasks_lock:
            server._running_tasks.pop(sid, None)


def test_running_task_frames_carry_increasing_run_seq(monkeypatch):
    from openprogram.interfaces.server import server
    sid = 'run-seq-chat'
    sent = []
    monkeypatch.setattr(server, '_broadcast', lambda text: sent.append(json.loads(text)))
    monkeypatch.setattr(server, '_canonical_foreground_task', lambda _sid: None)
    with server._running_tasks_lock:
        server._running_tasks[sid] = {'msg_id': 'm1', 'execution_id': 'exec-1',
                                      'func_name': '_chat', 'started_at': 0}
    try:
        server._emit_running_task_event(sid)
        with server._running_tasks_lock:
            server._running_tasks.pop(sid, None)
        server._emit_running_task_event(sid, cleared_msg_id='m1', cleared_execution_id='exec-1')
    finally:
        with server._running_tasks_lock:
            server._running_tasks.pop(sid, None)
    assert [f['type'] for f in sent] == ['running_task', 'running_task_clear']
    assert sent[0]['data']['run_seq'] < sent[1]['data']['run_seq'] < 2 ** 53


def test_run_identity_carries_the_turn_version_for_an_exact_stop(monkeypatch):
    """A client that reconnects mid-turn learns the version a cancel needs."""
    from openprogram.interfaces.server import server
    sid = 'run-identity-version'
    monkeypatch.setattr(server, '_canonical_foreground_task', lambda _sid: None)
    with server._running_tasks_lock:
        server._running_tasks[sid] = {'msg_id': 'm1', 'execution_id': 'exec-1',
                                      'status_version': 3, 'func_name': '_chat', 'started_at': 0}
    try:
        assert server._run_identity(sid) == {'msg_id': 'm1', 'execution_id': 'exec-1', 'status_version': 3}
        with server._running_tasks_lock:
            server._running_tasks[sid] = {'msg_id': 'm1', 'func_name': '_chat', 'started_at': 0}
        # A reservation without an execution yet names only the message.
        assert server._run_identity(sid) == {'msg_id': 'm1', 'execution_id': ''}
    finally:
        with server._running_tasks_lock:
            server._running_tasks.pop(sid, None)
    monkeypatch.setattr(server, '_canonical_foreground_task', lambda _sid: {
        'session_id': sid, 'msg_id': 'm2', 'execution_id': 'exec-2', 'status_version': 11,
        'status': 'running', 'func_name': 'agent', 'started_at': 0})
    assert server._run_identity(sid) == {'msg_id': 'm2', 'execution_id': 'exec-2', 'status_version': 11}
