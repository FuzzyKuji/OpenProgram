"""File selection and independent verification in owned headless Chromium."""

import pytest
from openprogram.programs.applications.browser.web_use import BrowserPageController
from tests.integration.programs.test_browser_observation_privacy import _OwnedBrowserAPI

pytestmark = pytest.mark.browser

@pytest.fixture
def controller():
    controller = BrowserPageController(browser_api=_OwnedBrowserAPI(''))
    try:
        controller.execute(action='observe')
        controller.evaluate_bound_page('() => { document.body.innerHTML = `<input type="file" aria-label="Attachment"><p id="status">Not submitted</p>`; }')
        yield controller
    finally:
        controller.close()


def observe(controller):
    frame = controller.execute(action='observe')
    return frame, next(e for e in frame['elements'] if e['name'] == 'Attachment')


def test_upload_selects_exact_file_then_requires_separate_verification(controller, tmp_path):
    path = tmp_path/'sample.txt'; path.write_text('test only')
    frame, field = observe(controller)
    result = controller.execute(action='upload', expected_frame_id=frame['frame_id'], ref=field['ref'], path=str(path))
    assert result['ok'] is True
    assert result['server_acceptance_verified'] is False
    assert controller.final_result(summary='')['status'] == 'failed'
    fresh, field = observe(controller)
    assert field['input_type'] == 'file'
    assert field['files'] == ['sample.txt']
    assert str(path) not in str(fresh)
    result = controller.execute(action='verify', expected_frame_id=fresh['frame_id'], ref=field['ref'],
                                assertion='file_selected', value='sample.txt')
    assert result['passed'] is True
    assert controller.final_result(summary='File selected')['status'] == 'succeeded'
    controller.evaluate_bound_page("() => document.querySelector('input').value = ''")
    assert controller.final_result(summary='')['status'] == 'failed'


@pytest.mark.parametrize('blocked', ['sandbox', 'missing', 'nonfile', 'stale', 'disabled', 'cancel'])
def test_upload_rejects_without_selecting_any_file(controller, tmp_path, monkeypatch, blocked):
    from openprogram.host import sandbox
    path = tmp_path/'test.txt'; path.write_text('must not transmit')
    frame, field = observe(controller)
    if blocked == 'sandbox':
        original = sandbox.policy_snapshot()
        sandbox.install_policy_snapshot({'enabled': True, 'policy': sandbox.policy_to_dict(
            sandbox.SandboxPolicy(deny_read=(str(path),), writable_roots=(str(tmp_path),), deny_write=()))})
    if blocked == 'missing':
        path = tmp_path/'absent.txt'
    if blocked in {'nonfile', 'disabled'}:
        controller.evaluate_bound_page("kind => {const el=document.querySelector('input'); if(kind==='nonfile') el.type='text'; else el.disabled=true;}", blocked)
        frame, field = observe(controller)
    kwargs = dict(action='upload', expected_frame_id='old' if blocked == 'stale' else frame['frame_id'],
                  ref=field['ref'], path=str(path))
    try:
        if blocked == 'cancel':
            from openprogram.programs.applications.browser.web_use import file_inputs
            original_read = file_inputs.file_payload
            read_done = []
            def read(path):
                result = original_read(path); read_done.append(True); return result
            monkeypatch.setattr(file_inputs, 'file_payload', read)
            def guard():
                if read_done:
                    raise PermissionError('cancelled after file read')
            with pytest.raises(PermissionError, match='cancelled'):
                controller.execute(**kwargs, before_dispatch=guard)
        else:
            result = controller.execute(**kwargs)
            assert result['ok'] is False
        assert controller._mutations == 0
        assert controller.evaluate_bound_page("() => document.querySelector('input').files?.length || 0") == 0
    finally:
        if blocked == 'sandbox':
            sandbox.install_policy_snapshot(original)


def test_uncertain_upload_is_not_replayed(controller, tmp_path, monkeypatch):
    path = tmp_path/'test.txt'; path.write_text('once')
    frame, field = observe(controller)
    handle = controller._refs[field['ref']]
    actual = handle.set_input_files
    calls = []
    def uncertain(*args):
        calls.append(1)
        actual(*args)
        raise RuntimeError('receipt unavailable after mutation')
    monkeypatch.setattr(handle, 'set_input_files', uncertain)
    result = controller.execute(action='upload', expected_frame_id=frame['frame_id'], ref=field['ref'], path=str(path))
    assert result['reason_code'] == 'file_selection_unconfirmed'
    frame, field = observe(controller)
    again = controller.execute(action='upload', expected_frame_id=frame['frame_id'], ref=field['ref'], path=str(path))
    assert again['reason_code'] == 'file_selection_unconfirmed'
    assert calls == [1]
    assert controller._mutations == 1


@pytest.mark.parametrize('backend_name', ['playwright_mcp', 'chrome_devtools_mcp'])
def test_mcp_file_capability_uses_real_owned_input_and_verifies_selection(controller, tmp_path, monkeypatch, backend_name):
    from types import SimpleNamespace
    from openprogram.programs.applications.browser.web_use.mcp_backends import OfficialMCPPageBackend
    class SnapshotClient:
        def call(self, name, params):
            assert name in {'browser_snapshot', 'take_snapshot'}
            return SimpleNamespace(isError=False, content=[SimpleNamespace(
                text='button unrelated [ref=e1]')])
    backend = OfficialMCPPageBackend(backend_name, lambda: controller)
    monkeypatch.setattr(backend, '_ensure_bound', lambda session: SnapshotClient())
    session = SimpleNamespace(controller=controller, state={'upstream_page': 7})
    path = tmp_path / 'fixture.txt'
    path.write_text('non-sensitive fixture')
    frame = backend.observe(session, {})
    field = frame['elements'][0]
    assert field['ref'].startswith('file_')
    result = backend.act(session, dict(action='upload', ref=field['ref'],
                                      expected_frame_id=frame['frame_id'], path=str(path)))
    assert result['ok'] is True
    assert result['server_acceptance_verified'] is False
    fresh = backend.observe(session, {})
    field = fresh['elements'][0]
    assert field['files'] == ['fixture.txt']
    result = backend.verify(session, dict(assertion='file_selected', ref=field['ref'],
                                          expected_frame_id=fresh['frame_id'], value='fixture.txt'))
    assert result['passed'] is True
    assert str(path) not in str(fresh)
