"""File references must never alias the upstream MCP snapshot namespace."""
from types import SimpleNamespace

import pytest

from openprogram.programs.applications.browser.web_use.mcp_backends import OfficialMCPPageBackend


class Controller:
    def __init__(self):
        self.calls = []
        self.frame = 'frame-1'
        self.denied = False

    def execute(self, **params):
        guard = params.get('before_dispatch')
        if guard:
            guard()
        if params['action'] == 'observe':
            return {'frame_id': self.frame, 'target': {'target_id': 'exact-page'},
                    'elements': [
                        {'ref': 'e107', 'input_type': 'file', 'name': 'Student ID',
                         'files': [], 'disabled': False},
                        {'ref': 'e108', 'input_type': 'file', 'name': 'Student ID',
                         'disabled': True},
                        {'ref': 'e109', 'role': 'button', 'name': 'Pay'}]}
        if params['expected_frame_id'] != self.frame:
            return {'ok': False, 'reason_code': 'stale_observation'}
        self.calls.append(params)
        if self.denied:
            return {'ok': False, 'reason_code': 'write_not_allowed'}
        if params['action'] == 'upload':
            return {'ok': True, 'server_acceptance_verified': False}
        return {'ok': True, 'passed': True}

    def capture_observation(self, capture):
        return capture()


class Client:
    def call(self, name, params):
        # Deliberately collide with a native file ref: the MCP e107 is NOT it.
        return SimpleNamespace(content=[SimpleNamespace(text='button Pay [ref=e107]')],
                               isError=False)


@pytest.fixture(params=['playwright_mcp', 'chrome_devtools_mcp'])
def setup(request, monkeypatch):
    controller = Controller()
    backend = OfficialMCPPageBackend(request.param, lambda: controller)
    monkeypatch.setattr(backend, '_ensure_bound', lambda session: Client())
    session = SimpleNamespace(state={'upstream_page': 7}, controller=controller)
    return backend, session, controller


def test_file_capabilities_do_not_alias_mcp_refs(setup):
    backend, session, controller = setup
    observed = backend.observe(session, {})
    assert len(observed['elements']) == 2
    first, second = observed['elements']
    assert first['ref'] != second['ref']
    assert first['ref'].startswith('file_')
    assert second['disabled'] is True
    assert 'ref=e107' in observed['aria_snapshot']
    assert first['files'] == []
    result = backend.act(session, {'action': 'upload', 'ref': first['ref'],
                                  'path': '/approved/student.jpg',
                                  'expected_frame_id': 'frame-1'})
    assert result['ok']
    assert result['server_acceptance_verified'] is False
    assert controller.calls[-1]['ref'] == 'e107'
    assert controller.calls[-1]['path'] == '/approved/student.jpg'
    verified = backend.verify(session, {'assertion': 'file_selected',
                                        'ref': first['ref'], 'value': 'student.jpg',
                                        'expected_frame_id': 'frame-1'})
    assert verified['passed']
    assert controller.calls[-1]['ref'] == 'e107'


@pytest.mark.parametrize('ref', ['e107', 'missing', 'file_forged', ''])
def test_upstream_or_forged_refs_cannot_transmit(setup, ref):
    backend, session, controller = setup
    backend.observe(session, {})
    result = backend.act(session, {'action': 'upload', 'ref': ref,
                                  'expected_frame_id': 'frame-1'})
    assert result['reason_code'] == 'file_input_required'
    assert not controller.calls


def test_reobservation_revokes_old_capabilities(setup):
    backend, session, controller = setup
    old = backend.observe(session, {})['elements'][0]['ref']
    backend.observe(session, {})
    assert backend.act(session, {'action': 'upload', 'ref': old,
                                'expected_frame_id': 'frame-1'})['ok'] is False
    assert not controller.calls


def test_stale_and_cross_session_file_refs(setup):
    backend, session, controller = setup
    ref = backend.observe(session, {})['elements'][0]['ref']
    assert backend.act(session, {'action': 'upload', 'ref': ref,
                                'expected_frame_id': 'old'})['reason_code'] == 'stale_observation'
    other = SimpleNamespace(state={'file_refs_frame': 'frame-1'}, controller=controller)
    assert backend.act(other, {'action': 'upload', 'ref': ref,
                              'expected_frame_id': 'frame-1'})['ok'] is False
    # The adapter mapping is necessary, but the controller still checks live freshness.
    controller.frame = 'frame-2'
    assert backend.act(session, {'action': 'upload', 'ref': ref,
                                'expected_frame_id': 'frame-1'})['reason_code'] == 'stale_observation'
    assert not controller.calls


def test_guard_and_native_permission_checks_are_preserved(setup):
    backend, session, controller = setup
    ref = backend.observe(session, {})['elements'][0]['ref']
    params = {'action': 'upload', 'ref': ref, 'expected_frame_id': 'frame-1'}
    def denied():
        raise PermissionError('revoked')
    with pytest.raises(PermissionError):
        backend.act(session, params, before_dispatch=denied)
    assert not controller.calls
    controller.denied = True
    assert backend.act(session, params)['reason_code'] == 'write_not_allowed'


def test_file_refs_are_not_clickable(setup):
    backend, session, controller = setup
    ref = backend.observe(session, {})['elements'][0]['ref']
    assert backend.act(session, {'action': 'click', 'ref': ref,
                                'expected_frame_id': 'frame-1'})['reason_code'] == 'file_ref_action_required'
    assert not controller.calls
