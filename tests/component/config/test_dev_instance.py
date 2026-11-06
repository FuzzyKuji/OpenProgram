"""Promotion moves `stable` only to the commit the development instance serves."""
import subprocess

import pytest

from openprogram.operations.worker import dev_instance as instances


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "dev")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    shas = []
    for n in range(3):
        (repo / "f").write_text(str(n))
        _git(repo, "add", "f")
        _git(repo, "commit", "-q", "-m", f"c{n}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    _git(repo, "branch", "stable", shas[0])
    home = tmp_path / "home"
    monkeypatch.setattr(instances.Path, "home", lambda: home)
    monkeypatch.setenv("OPENPROGRAM_SOURCE_REPO", str(repo))
    monkeypatch.setattr(instances, "healthy", lambda port: True)
    runs, backups = [], []
    monkeypatch.setattr(instances, "_managed_worktree", lambda repo, path, rev: path)
    monkeypatch.setattr(instances, "_run", lambda script, cwd, env=None: runs.append(script.name))
    import openprogram.operations.backup as backup
    monkeypatch.setattr(backup, "create_backup", lambda **kw: backups.append(kw))

    def serve(sha):
        target = instances.dev_runtime_dir()
        target.mkdir(parents=True, exist_ok=True)
        (target / "source-revision").write_text(sha + "\n")

    return repo, shas, serve, runs, backups


def test_promotes_the_served_commit(world):
    repo, shas, serve, runs, backups = world
    serve(shas[2])
    assert [c["subject"] for c in instances.status()["promotable"]] == ["c2", "c1"]
    assert instances.promote() == shas[2]
    assert _git(repo, "rev-parse", "stable") == shas[2]
    assert backups == [{"label": "pre-promote"}]
    assert runs == ["refresh-local-app.sh"]


def test_promotion_reuses_the_dev_build(world, monkeypatch):
    _, shas, serve, _, _ = world
    serve(shas[2])
    envs = []
    monkeypatch.setattr(instances, "_run", lambda script, cwd, env=None: envs.append(env))
    instances.promote()
    assert envs == [{"OPENPROGRAM_PREBUILT_DIR": str(instances.dev_artifacts_dir())}]


def test_refuses_a_commit_dev_does_not_serve(world):
    repo, shas, serve, runs, _ = world
    serve(shas[1])
    with pytest.raises(instances.InstanceError, match="only the commit the development instance serves"):
        instances.promote(shas[2])
    assert _git(repo, "rev-parse", "stable") == shas[0] and runs == []


def test_refuses_dirty_unhealthy_or_backwards(world, monkeypatch):
    repo, shas, serve, runs, _ = world
    serve(shas[2] + "-dirty")
    with pytest.raises(instances.InstanceError, match="no clean commit"):
        instances.promote()
    serve(shas[2])
    monkeypatch.setattr(instances, "healthy", lambda port: False)
    with pytest.raises(instances.InstanceError, match="not healthy"):
        instances.promote()
    monkeypatch.setattr(instances, "healthy", lambda port: True)
    _git(repo, "branch", "-f", "stable", shas[2])
    serve(shas[1])
    with pytest.raises(instances.InstanceError, match="only fast-forwards"):
        instances.promote()
    assert runs == []


def _cred(kind, cid):
    from openprogram.models.auth.types import CREDENTIAL_SCHEMA_VERSION
    return {"v": CREDENTIAL_SCHEMA_VERSION, "provider_id": "acme", "account_id": "default", "credential_id": cid, "kind": kind,
            "source": "test", "payload": {"kind": kind, "auth_value": f"value-{cid}"},
            "metadata": {}, "read_only": False}


def test_credentials_belong_to_the_active_profile(tmp_path, monkeypatch):
    from openprogram.state import paths
    from openprogram.models.auth.store import AuthStore

    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
    previous = paths.get_active_profile()
    paths.set_active_profile("dev")
    try:
        assert AuthStore().base_dir() == tmp_path / ".openprogram-dev" / "auth"
    finally:
        paths.set_active_profile(previous)


def test_copy_models_shares_keys_but_not_oauth(tmp_path, monkeypatch):
    import json
    from openprogram.models.auth.store import AuthStore
    from openprogram.models.auth.types import CredentialPool

    monkeypatch.setattr(instances.Path, "home", lambda: tmp_path)
    stable = instances.stable_state_dir()
    AuthStore(root=stable).put_pool(CredentialPool.from_dict({
        "provider_id": "acme", "account_id": "default", "active_credential_id": "o",
        "credentials": [_cred("oauth", "o"), _cred("api_key", "k")]}))
    (stable / "config.json").write_text(json.dumps(
        {"providers": {"acme": {"enabled": True}}, "last_used_model": {"provider": "acme"}, "ui": {"x": 1}}))
    (instances.dev_state_dir()).mkdir(parents=True)
    (instances.dev_state_dir() / "config.json").write_text(json.dumps({"ui": {"y": 2}}))

    result = instances.copy_models()

    assert result == {"copied": ["acme/default"], "oauth_not_copied": ["acme/default"]}
    pool = AuthStore(root=instances.dev_state_dir()).get_pool("acme", "default")
    assert [c.kind for c in pool.credentials] == ["api_key"] and pool.active_credential_id == ""
    config = json.loads((instances.dev_state_dir() / "config.json").read_text())
    assert config == {"ui": {"y": 2}, "providers": {"acme": {"enabled": True}},
                      "last_used_model": {"provider": "acme"}}


def test_only_the_newest_promote_backups_are_kept(tmp_path):
    names = [f"default-pre-promote-2026110{day}-120000.tar.gz" for day in range(1, 9)]
    for name in names:
        (tmp_path / name).write_text("x")
        (tmp_path / (name + ".lock")).write_text("")
    other = tmp_path / "default-20261101-120000.tar.gz"
    other.write_text("x")
    instances.prune_promote_backups(tmp_path, keep=5)
    left = sorted(path.name for path in tmp_path.glob("*.tar.gz"))
    assert left == sorted([other.name, *names[-5:]])
    assert sorted(path.name for path in tmp_path.glob("*.lock")) == sorted(name + ".lock" for name in names[-5:])
