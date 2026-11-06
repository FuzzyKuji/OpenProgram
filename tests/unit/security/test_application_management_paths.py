"""New management locations retain the non-configurable write boundary."""
import json
from pathlib import Path


def test_package_code_and_software_registration_are_protected(tmp_path, monkeypatch):
    import openprogram
    from openprogram.state import paths
    from openprogram.host import sandbox
    from openprogram.host.sandbox.protected_paths import application_catalog_path
    monkeypatch.setattr(openprogram, '__file__', str(tmp_path / 'openprogram/__init__.py'))
    monkeypatch.setattr(paths, 'get_state_dir', lambda: tmp_path / 'state')
    monkeypatch.setattr(sandbox, 'resolve_policy', lambda: None)
    harness = tmp_path / 'state' / 'programs' / 'demo_harness'
    harness.mkdir(parents=True)
    (tmp_path / 'state' / 'program-sources.json').write_text(json.dumps({
        'version': 2, 'programs': [{'path': str(harness), 'source': 'fixture', 'kind': 'git'}],
    }))
    for target in [harness / 'demo/agentics/__init__.py', Path(application_catalog_path()),
                   tmp_path / 'openprogram/programs/applications/legacy/agent.py']:
        assert sandbox.validate_write_path(target) is not None
    assert sandbox.validate_write_path(tmp_path / 'ordinary.txt') is None
    # A Program the user writes is not a recorded harness: it stays writable.
    assert sandbox.validate_write_path(tmp_path / 'state' / 'programs' / 'weekly_report' / 'run.py') is None
