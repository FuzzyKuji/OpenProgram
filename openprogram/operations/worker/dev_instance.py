"""Stable and development instances of one source checkout.

The stable instance is the installed App (``/Applications/OpenProgram.app``,
port 18100, ``~/.openprogram``) and only ever runs the ``stable`` branch.
The development instance is a runtime (port 18200,
``~/.openprogram-dev``) that runs whatever ``dev`` commit was deployed to
it last, opened in ``/Applications/OpenProgram Dev.app`` on macOS or in a
browser. Commits reach stable only by promotion: a commit that the
development instance is serving, healthy, is fast-forwarded onto
``stable`` and installed into the App by ``scripts/refresh-local-app.sh``.

Both build from managed detached worktrees of the source repository, so
neither depends on the state of a developer's checkout.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path

DEV_PROFILE = "dev"
DEV_PORT = 18200
# Browser debugging port of the development App (scripts/install-dev-app.sh);
# the stable App uses 9223.
DEV_APP_DEBUG_PORT = 9224
STABLE_PORT = 18100
STABLE_BRANCH = "stable"
DEV_BRANCH = "dev"
APP_PATH = Path("/Applications/OpenProgram.app")
SOURCE_REPO_FILE = "source-repo"


class InstanceError(Exception):
    """A deploy or promotion was refused; the message says why."""


def stable_state_dir() -> Path:
    return Path.home() / ".openprogram"


def dev_state_dir() -> Path:
    return Path.home() / f".openprogram-{DEV_PROFILE}"


def dev_runtime_dir() -> Path:
    return dev_state_dir() / "runtime"


def dev_artifacts_dir() -> Path:
    """The wheel and TUI bundle of the last dev deploy, for promotion."""
    return dev_state_dir() / "artifacts"


def source_repo() -> Path:
    """The source checkout both instances build from.

    ``OPENPROGRAM_SOURCE_REPO`` wins; otherwise the path the last refresh
    recorded in ``~/.openprogram/source-repo``.
    """
    value = os.environ.get("OPENPROGRAM_SOURCE_REPO", "").strip()
    if not value:
        try:
            value = (stable_state_dir() / SOURCE_REPO_FILE).read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            value = ""
    if not value:
        raise InstanceError(
            "no source checkout is known; set OPENPROGRAM_SOURCE_REPO or "
            "run scripts/refresh-dev-instance.sh from the checkout once")
    repo = Path(value).expanduser()
    if not (repo / ".git").exists():
        raise InstanceError(f"the recorded source checkout is not a Git repository: {repo}")
    return repo


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args],
                            capture_output=True, text=True)
    if check and result.returncode != 0:
        raise InstanceError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _ref(repo: Path, ref: str) -> str | None:
    value = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    return value or None


def _read_revision(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return value or None


def dev_revision() -> str | None:
    """The commit the development instance was last deployed from."""
    return _read_revision(dev_runtime_dir() / "source-revision")


def dev_python() -> Path:
    """The development runtime's interpreter, from its manifest."""
    runtime = dev_runtime_dir()
    try:
        manifest = json.loads((runtime / "runtime-manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InstanceError("the development instance is not deployed; run `openprogram dev deploy`") from None
    return runtime / manifest["python"]


def auth_url() -> str:
    """A sign-in link for the development instance's current worker.

    The worker mints a new owner token every time it starts, so a browser
    signed in before a deploy has to sign in again with a fresh link.
    """
    result = subprocess.run(
        [str(dev_python()), "-I", "-B", "-m", "openprogram", "web", "auth-url",
         "--base-url", f"http://127.0.0.1:{DEV_PORT}"],
        capture_output=True, text=True, env={**os.environ, "OPENPROGRAM_PROFILE": DEV_PROFILE})
    url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if result.returncode != 0 or not url.startswith("http"):
        raise InstanceError(result.stderr.strip() or "the development instance gave no sign-in link; is it running?")
    return url


def stable_revision() -> str | None:
    """The commit the installed App was last refreshed from."""
    return _read_revision(APP_PATH / "Contents" / "Resources" / "openprogram-source-revision")


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def _subjects(repo: Path, base: str | None, head: str | None) -> list[dict]:
    if not head:
        return []
    span = f"{base}..{head}" if base else head
    out = _git(repo, "log", "--format=%H%x1f%s", "--max-count=200", span, check=False)
    return [dict(zip(("sha", "subject"), line.split("\x1f", 1)))
            for line in out.splitlines() if "\x1f" in line]


def status() -> dict:
    """Both instances, and what promoting the development one would bring."""
    repo = source_repo()
    stable_ref = _ref(repo, STABLE_BRANCH)
    dev = dev_revision()
    return {
        "source_repo": str(repo),
        "stable": {
            "branch": STABLE_BRANCH,
            "branch_revision": stable_ref,
            "installed_revision": stable_revision(),
            "port": STABLE_PORT,
            "healthy": healthy(STABLE_PORT),
        },
        "dev": {
            "branch": DEV_BRANCH,
            "branch_revision": _ref(repo, DEV_BRANCH),
            "deployed_revision": dev,
            "port": DEV_PORT,
            "url": f"http://127.0.0.1:{DEV_PORT}",
            "healthy": healthy(DEV_PORT),
        },
        # Commits stable would gain by promoting what dev serves now.
        "promotable": _subjects(repo, stable_ref, dev) if dev and not dev.endswith("-dirty") else [],
    }


# Credentials the development instance may share. An API key is static, and a
# CLI-delegated credential reads another tool's login by reference. OAuth
# logins are not copied: their refresh tokens rotate, so two instances
# refreshing one login would sign each other out.
SHAREABLE_KINDS = frozenset({"api_key", "cli_delegated"})
MODEL_CONFIG_KEYS = ("api_keys", "providers", "last_used_model")


def copy_models() -> dict:
    """Give the development instance the stable instance's model setup.

    Copies provider settings and the shareable credentials; returns what
    was copied and which OAuth logins must be signed in again there.
    """
    from openprogram.models.auth.store import AuthStore
    from openprogram.models.auth.types import CredentialPool

    source = AuthStore(root=stable_state_dir())
    target = AuthStore(root=dev_state_dir())
    copied, skipped = [], []
    for pool in source.list_pools():
        name = f"{pool.provider_id}/{pool.account_id}"
        clone = CredentialPool.from_dict(pool.to_dict())
        clone.credentials = [c for c in clone.credentials if c.kind in SHAREABLE_KINDS]
        if len(clone.credentials) < len(pool.credentials):
            skipped.append(name)
        if not clone.credentials:
            continue
        if clone.active_credential_id not in {c.credential_id for c in clone.credentials}:
            clone.active_credential_id = ""
        target.put_pool(clone)
        copied.append(name)

    config_path = dev_state_dir() / "config.json"
    stable_config = json.loads((stable_state_dir() / "config.json").read_text(encoding="utf-8"))
    try:
        dev_config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        dev_config = {}
    for key in MODEL_CONFIG_KEYS:
        if key in stable_config:
            dev_config[key] = stable_config[key]
    staged = config_path.with_suffix(".json.incoming")
    staged.write_text(json.dumps(dev_config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(staged, 0o600)
    os.replace(staged, config_path)
    return {"copied": copied, "oauth_not_copied": skipped}


def _managed_worktree(repo: Path, path: Path, revision: str) -> Path:
    """A clean detached worktree at ``revision``; ignored build caches stay."""
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "add", "--detach", str(path), revision)
        return path
    _git(path, "checkout", "--force", "--detach", revision)
    _git(path, "clean", "-fd")
    return path


def _run(script: Path, cwd: Path, env: dict | None = None) -> None:
    result = subprocess.run(["bash", str(script)], cwd=str(cwd),
                            env={**os.environ, **(env or {})})
    if result.returncode != 0:
        raise InstanceError(f"{script.name} failed (exit {result.returncode})")


def deploy_dev(ref: str = DEV_BRANCH) -> str:
    """Build ``ref`` into the development runtime and restart its worker."""
    repo = source_repo()
    revision = _ref(repo, ref)
    if not revision:
        raise InstanceError(f"unknown ref: {ref}")
    tree = _managed_worktree(repo, dev_state_dir() / "source", revision)
    _run(tree / "scripts" / "refresh-dev-instance.sh", tree)
    return revision


def promote(revision: str | None = None) -> str:
    """Fast-forward ``stable`` to what dev serves and install it into the App.

    Refused unless the commit is exactly the one the development instance
    is serving, that instance is healthy, and the move is a fast-forward.
    The stable profile is backed up first.
    """
    repo = source_repo()
    served = dev_revision()
    if not served or served.endswith("-dirty"):
        raise InstanceError("the development instance serves no clean commit; deploy one first")
    target = _ref(repo, revision) if revision else served
    if not target:
        raise InstanceError(f"unknown revision: {revision}")
    if target != served:
        raise InstanceError(
            f"only the commit the development instance serves can be promoted ({served[:10]}); "
            f"deploy {target[:10]} to it first")
    if not healthy(DEV_PORT):
        raise InstanceError("the development instance is not healthy; promote after it serves the commit")
    current = _ref(repo, STABLE_BRANCH)
    if current and current != target and subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", current, target]).returncode != 0:
        raise InstanceError(f"{target[:10]} does not contain stable ({current[:10]}); promotion only fast-forwards")

    from openprogram.operations.backup import create_backup
    archive = create_backup(label="pre-promote")
    if archive:
        prune_promote_backups(Path(archive).parent)

    # Compare-and-swap so a concurrent promotion cannot be overwritten.
    _git(repo, "update-ref", "-m", "promote from dev", f"refs/heads/{STABLE_BRANCH}",
         target, current or "0" * 40)
    tree = _managed_worktree(repo, stable_state_dir() / "release-source", target)
    # The development instance already built this commit; the refresh reuses
    # that build when its recorded revision matches.
    _run(tree / "scripts" / "refresh-local-app.sh", tree,
         {"OPENPROGRAM_PREBUILT_DIR": str(dev_artifacts_dir())})
    return target


PROMOTE_BACKUPS_KEPT = 5


def prune_promote_backups(directory: Path, keep: int = PROMOTE_BACKUPS_KEPT) -> list[Path]:
    """Delete all but the newest `keep` pre-promote backups (and their locks).

    Every promotion writes a full archive of the stable data; without a
    bound they pile up by the hundred. Other backups are left alone.
    """
    archives = sorted(directory.glob("*-pre-promote-*.tar.gz"), key=lambda path: path.name, reverse=True)
    removed = []
    for archive in archives[keep:]:
        for path in (archive, archive.with_name(archive.name + ".lock")):
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            removed.append(path)
    return removed


def as_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
