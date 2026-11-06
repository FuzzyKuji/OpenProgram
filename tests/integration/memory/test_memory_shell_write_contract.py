"""Actual writer shell subprocess shares atomic uncited-prose validation."""
from __future__ import annotations

import subprocess
from contextlib import closing

import pytest


def test_writer_shell_rejects_uncited_prose_without_committed_mutation(tmp_path, monkeypatch):
    from openprogram.state.memory.management import MemoryWorkspace
    from openprogram.state.memory.management.transaction import workspace_revision
    from openprogram.state.memory.markdown import TopicFormatError
    from openprogram.state.memory.store import _ensure_git_history

    root = tmp_path / "memory"
    root.mkdir()
    _ensure_git_history(root)
    # Reuse the existing command-adapter boundary; the shell itself is a real
    # subprocess, while host sandbox availability is controlled for portability.
    monkeypatch.setattr("openprogram.state.memory.management.workspace._sandbox.resolve_policy", lambda *, required: object())
    monkeypatch.setattr("openprogram.host.backend.local._invocation", lambda command, _cwd, **kwargs: (["/bin/sh", "-c", command], False, None, True))
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts}
    revision = workspace_revision(root)
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"])
    with closing(MemoryWorkspace(root)) as workspace:
        stage = workspace.stage_dir
        with pytest.raises(TopicFormatError):
            workspace.shell("printf '# Unsupported\\n\\nUncited substantive prose.\\n' > topics/plain.md")
    assert not stage.exists()
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts} == before
    assert workspace_revision(root) == revision
    assert subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"]) == head
