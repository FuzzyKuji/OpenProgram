"""Promotion moves `stable` only to the commit the development instance serves."""
import os
import subprocess
import time

import pytest

from openprogram.operations.self_update.control import supervisor
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
    monkeypatch.setattr(supervisor, "active_work", lambda: [])
    monkeypatch.setattr(instances, "_stable_worker_pid", lambda: 4242)

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


def test_a_failed_refresh_runs_once_more(world, monkeypatch):
    _, shas, serve, _, _ = world
    serve(shas[2])
    attempts = []

    def flaky(script, cwd, env=None):
        attempts.append(script.name)
        if len(attempts) == 1:
            raise instances.InstanceError("refresh-local-app.sh failed (exit 1)")

    monkeypatch.setattr(instances, "_run", flaky)
    assert instances.promote(shas[2]) == shas[2]
    assert attempts == ["refresh-local-app.sh", "refresh-local-app.sh"]


def test_a_refresh_that_fails_twice_is_reported_apart_from_a_refusal(world, monkeypatch):
    repo, shas, serve, _, _ = world
    serve(shas[2])

    def broken(script, cwd, env=None):
        raise instances.InstanceError("refresh-local-app.sh failed (exit 1)")

    monkeypatch.setattr(instances, "_run", broken)
    with pytest.raises(instances.RefreshFailedError, match="failed twice"):
        instances.promote(shas[2])
    # stable has moved; the controller repairs it forward, never backward.
    assert _git(repo, "rev-parse", "stable") == shas[2]


def test_refuses_a_commit_dev_does_not_serve(world):
    repo, shas, serve, runs, _ = world
    serve(shas[1])
    with pytest.raises(instances.NotServedError, match="only the commit the development instance serves"):
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


def _busy(monkeypatch, snapshots, quiet=False):
    """``active_work`` answers from ``snapshots``; records the wait it was given."""
    waits = []
    answers = iter(snapshots)
    monkeypatch.setattr(supervisor, "active_work", lambda: next(answers))
    monkeypatch.setattr(supervisor, "_wait_for_quiescence",
                        lambda deadline: waits.append(deadline - time.time()) or quiet)
    monkeypatch.setattr(instances, "_inside_worker", lambda pid: False)
    return waits


def test_promotion_waits_for_stable_to_go_quiet(world, monkeypatch):
    repo, shas, serve, runs, backups = world
    serve(shas[2])
    waits = _busy(monkeypatch, [["a turn in conversation c1"]], quiet=True)
    said = []
    assert instances.promote(on_wait=said.append) == shas[2]
    assert len(waits) == 1 and waits[0] <= instances.STABLE_QUIET_WAIT_SECONDS
    assert "c1" in said[0] and runs and backups


def test_a_stable_instance_that_stays_busy_refuses_and_changes_nothing(world, monkeypatch):
    repo, shas, serve, runs, backups = world
    serve(shas[2])
    work = ["execution e1 (running) in conversation c1", "job j1 in conversation c2"]
    _busy(monkeypatch, [work, work])
    with pytest.raises(instances.StableBusyError) as refused:
        instances.promote()
    assert "e1" in str(refused.value) and "j1" in str(refused.value)
    assert _git(repo, "rev-parse", "stable") == shas[0] and not runs and not backups


def test_work_ending_just_as_the_wait_expires_is_not_a_refusal(world, monkeypatch):
    repo, shas, serve, runs, _ = world
    serve(shas[2])
    _busy(monkeypatch, [["a turn in conversation c1"], []])
    assert instances.promote() == shas[2] and runs


def test_a_refusal_for_another_reason_comes_before_the_wait(world, monkeypatch):
    repo, shas, serve, runs, _ = world
    serve(shas[1])
    waits = _busy(monkeypatch, [["a turn in conversation c1"]])
    with pytest.raises(instances.NotServedError):
        instances.promote(shas[2])
    assert not waits


def test_a_turn_inside_stable_is_told_at_once_instead_of_waiting_on_itself(world, monkeypatch):
    repo, shas, serve, runs, _ = world
    serve(shas[2])
    work = ["a turn in conversation c1"]
    waits = _busy(monkeypatch, [work, work])
    monkeypatch.setattr(instances, "_inside_worker", lambda pid: True)
    with pytest.raises(instances.StableBusyError, match="self_update"):
        instances.promote()
    assert waits[0] <= instances.STABLE_QUIET_WAIT_FROM_WORKER_SECONDS and not runs


def test_the_controller_skips_the_wait(world, monkeypatch):
    repo, shas, serve, runs, _ = world
    serve(shas[2])
    monkeypatch.setattr(supervisor, "active_work", lambda: pytest.fail("the controller already waited"))
    assert instances.promote(shas[2], wait_for_stable=False) == shas[2] and runs


def test_an_unreadable_stable_store_refuses_without_a_traceback(world, monkeypatch):
    repo, shas, serve, runs, _ = world
    serve(shas[2])

    def broken():
        raise OSError("disk gone")

    monkeypatch.setattr(supervisor, "active_work", broken)
    with pytest.raises(instances.InstanceError, match="disk gone"):
        instances.promote()
    assert not runs


def test_stable_is_read_even_from_the_dev_profile(world, monkeypatch):
    from openprogram.state.paths import get_active_profile

    repo, shas, serve, *_ = world
    serve(shas[2])
    monkeypatch.setenv("OPENPROGRAM_PROFILE", "dev")
    seen = []
    monkeypatch.setattr(supervisor, "active_work", lambda: seen.append(get_active_profile()) or [])
    instances.promote()
    assert seen == [None] and get_active_profile() == "dev"


def test_rows_a_dead_worker_left_running_do_not_block_the_repair(world, monkeypatch):
    repo, shas, serve, runs, backups = world
    serve(shas[2])
    monkeypatch.setattr(instances, "_stable_worker_pid", lambda: None)
    monkeypatch.setattr(supervisor, "active_work", lambda: pytest.fail("no worker, nothing to interrupt"))
    assert instances.promote() == shas[2] and runs and backups


def test_a_lock_file_left_by_a_crash_is_not_a_live_worker(monkeypatch):
    from openprogram.operations.worker import lock

    monkeypatch.setattr(lock, "read_holder_pid", lambda: 4242)
    monkeypatch.setattr(lock, "is_held_by", lambda pid: False)
    assert instances._stable_worker_pid() is None
    monkeypatch.setattr(lock, "is_held_by", lambda pid: True)
    assert instances._stable_worker_pid() == 4242


def test_a_dev_deploy_during_the_wait_stops_the_promotion(world, monkeypatch):
    repo, shas, serve, runs, backups = world
    serve(shas[2])
    work = ["a turn in conversation c1"]
    _busy(monkeypatch, [work])
    monkeypatch.setattr(supervisor, "_wait_for_quiescence", lambda deadline: serve(shas[1]) or True)
    with pytest.raises(instances.NotServedError):
        instances.promote()
    assert _git(repo, "rev-parse", "stable") == shas[0] and not runs and not backups


def test_the_backup_is_of_stable_even_from_the_dev_profile(world, monkeypatch):
    import openprogram.operations.backup as backup
    from openprogram.state.paths import get_active_profile

    repo, shas, serve, *_ = world
    serve(shas[2])
    monkeypatch.setenv("OPENPROGRAM_PROFILE", "dev")
    seen = []
    monkeypatch.setattr(backup, "create_backup", lambda **kw: seen.append(get_active_profile()))
    instances.promote()
    assert seen == [None] and get_active_profile() == "dev"


def test_this_process_descends_from_its_ancestors_only():
    assert instances._inside_worker(os.getppid())
    assert not instances._inside_worker(None)
    assert not instances._inside_worker(2 ** 22 - 1)


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
