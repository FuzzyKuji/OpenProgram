"""Production browser typing and fresh actual values in owned real Chromium."""
from __future__ import annotations

import pytest

from openprogram.programs.applications.browser.web_use import BrowserPageController
from tests.integration.programs.test_browser_observation_privacy import _OwnedBrowserAPI

pytestmark = pytest.mark.browser


@pytest.fixture
def controller():
    result = BrowserPageController(browser_api=_OwnedBrowserAPI(''))
    try:
        result.execute(action='observe')
        yield result
    finally:
        result.close()


def _editor(controller, html):
    controller.evaluate_bound_page('html => document.body.innerHTML = html', html)
    initial = controller.execute(action='observe')
    field = next(element for element in initial['elements'] if element['name'] == 'Report')
    return initial, field


def _type(controller, initial, field, text):
    return controller.execute(action='type', expected_frame_id=initial['frame_id'],
                              ref=field['ref'], text=text)


def _readback(controller):
    fresh = controller.execute(action='observe')
    field = next(element for element in fresh['elements'] if element['name'] == 'Report')
    assert field['value_truncated'] is False
    assert field['value_redacted'] is False
    return fresh, field


@pytest.mark.parametrize('text', [
    '第一行  双空格\n第二行\n\n最后一行',
    '\n开头空行\n\n末尾空行\n',
    '😀  原样\n\n中文',
    '',
])
@pytest.mark.parametrize('kind', ['textarea', 'contenteditable'])
def test_public_type_and_fresh_actual_value_are_exact(controller, kind, text):
    html = ('<textarea aria-label="Report">old</textarea>' if kind == 'textarea' else
            '<div contenteditable="true" aria-label="Report" '
            'style="white-space:pre-wrap">old</div>')
    initial, field = _editor(controller, html)
    result = _type(controller, initial, field, text)
    assert result['ok'] is True
    # A plain field keeps its observation so a form can be filled in one go;
    # a rich editor may re-render, so it asks for a new one.
    assert result['observe_required'] is (kind == 'contenteditable')
    fresh, actual = _readback(controller)
    assert fresh['frame_id'] != initial['frame_id']
    assert actual['value'] == text
    assert actual['value_source'] == ('dom_value' if kind == 'textarea' else 'inner_text')
    # A newer observation retires the previous frame.
    stale = _type(controller, initial, field, 'must not overwrite')
    assert stale['ok'] is False
    _, unchanged = _readback(controller)
    assert unchanged['value'] == text


def test_editor_input_state_and_mutation_rerender_preserve_requested_text(controller):
    initial, field = _editor(controller, '<div contenteditable="true" aria-label="Report" '
                                         'style="white-space:pre-wrap">old</div>')
    controller.evaluate_bound_page("""() => {
        window.savedInput = null;
        window.rerendered = false;
        const field = document.querySelector('[contenteditable]');
        field.addEventListener('input', event => {
            window.savedInput = event.target.innerText;
            if (window.savedInput) Promise.resolve().then(() => {
                const child = document.createElement('span');
                child.textContent = window.savedInput;
                field.replaceChildren(child);
                window.rerendered = true;
            });
        });
    }""")
    text = '第一行  原样\n第二行\n\n末行'
    result = _type(controller, initial, field, text)
    assert result['ok'] is True
    _, actual = _readback(controller)
    assert actual['value'] == text
    state = controller.evaluate_bound_page('() => ({saved:window.savedInput, rerendered:window.rerendered})')
    assert state == {'saved': text, 'rerendered': True}


@pytest.mark.parametrize('rewrite', [False, True])
def test_collapsing_css_or_editor_rewrite_returns_failed_mutated_action(controller, rewrite):
    initial, field = _editor(controller, '<div contenteditable="true" aria-label="Report" '
                                         + ('style="white-space:pre-wrap"' if rewrite else '')
                                         + '>old</div>')
    if rewrite:
        controller.evaluate_bound_page("""() => {
            document.querySelector('[contenteditable]').addEventListener('input', event => {
                if (event.target.innerText) Promise.resolve().then(() => {
                    event.target.textContent = 'editor rewrote the requested text';
                });
            });
        }""")
    text = '第一行  双空格\n第二行\n\n最后一行'
    result = _type(controller, initial, field, text)
    assert result['ok'] is False
    assert result['reason_code'] == 'editable_value_mismatch'
    assert result['observe_required'] is True
    _, actual = _readback(controller)
    assert actual['value'] != text
    assert controller._mutations == 1


def test_cancellation_after_native_clear_invalidates_previous_frame(controller):
    initial, field = _editor(controller, '<div contenteditable="true" aria-label="Report" '
                                         'style="white-space:pre-wrap">old</div>')
    def cancel_after_clear():
        if controller._page().locator('[contenteditable]').text_content() == '':
            raise PermissionError('cancelled after the native clear')
    with pytest.raises(PermissionError, match='cancelled after the native clear'):
        controller.execute(action='type', expected_frame_id=initial['frame_id'],
                           ref=field['ref'], text='must not insert',
                           before_dispatch=cancel_after_clear)
    assert controller._mutations == 1
    assert _type(controller, initial, field, 'must not replay')['ok'] is False
    _, actual = _readback(controller)
    assert actual['value'] == '\n'  # Native clear leaves a Chromium <br>.


def test_form_fields_keep_the_frame_and_other_writes_retire_it(controller):
    controller.evaluate_bound_page('html => document.body.innerHTML = html', (
        '<input aria-label="Name"><input aria-label="Email">'
        '<select aria-label="Track"><option>A</option><option>B</option></select>'
        '<input type="checkbox" aria-label="Agree">'
        '<button onclick="document.body.dataset.sent = 1">Next</button>'))
    initial = controller.execute(action='observe')
    frame = initial['frame_id']
    ref = {element['name']: element['ref'] for element in initial['elements']}
    steps = [dict(action='type', ref=ref['Name'], text='Ada'),
             dict(action='type', ref=ref['Email'], text='ada@example.com'),
             dict(action='select', ref=ref['Track'], value='B'),
             dict(action='click', ref=ref['Agree'])]
    for step in steps:
        result = controller.execute(expected_frame_id=frame, **step)
        assert result['ok'] is True, (step, result)
        assert result['observe_required'] is False
        assert result['frame_id'] == frame
    pressed = controller.execute(action='click', expected_frame_id=frame, ref=ref['Next'])
    assert pressed['ok'] is True and pressed['observe_required'] is True
    stale = controller.execute(action='type', expected_frame_id=frame, ref=ref['Name'], text='x')
    assert stale['ok'] is False
    values = controller.evaluate_bound_page("""() => [...document.querySelectorAll('input, select')]
        .map(node => node.type === 'checkbox' ? node.checked : node.value)""")
    assert values == ['Ada', 'ada@example.com', 'B', True]
