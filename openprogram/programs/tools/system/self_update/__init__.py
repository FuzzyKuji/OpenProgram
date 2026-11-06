"""Owner-only conversational self-update request tools.

These tools only validate and persist an immutable candidate request. App
building, activation, restart, verification, and rollback are owned by the
external supervisor rather than this worker process.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import time
import tomllib
from typing import Any, Mapping

from openprogram.state.authority import normalize_authority
from openprogram.runtime.permissions.authority import owner_principal_id
from openprogram.runtime.agent.turn_request import get_turn_request
from openprogram.programs._host.runtime import function
from openprogram.operations.self_update import (
    ActiveUpdateError,
    IterationMode,
    IterationPolicy,
    SelfUpdateError,
    SelfUpdateStore,
    UpdatePhase,
    UpdateRequest,
    mint_update_id,
)
from openprogram.state.worktree.manager import get_manager
from openprogram.state.worktree.types import WorktreeStatus


_NON_INTERACTIVE_SOURCES = frozenset({"agent_spawn", "cron", "scheduler", "mcp"})
_GIT_TIMEOUT_SECONDS = 10
_GIT_CONFIG_OVERRIDES = (
    "core.fsmonitor=false",
    "core.hooksPath=/dev/null",
    "core.pager=cat",
)


class SelfUpdateToolError(RuntimeError):
    """A stable validation error safe to return through the tool runtime."""


def _require_update_backend() -> None:
    from openprogram.host._platform.environment import conversational_update_backend

    if conversational_update_backend() is None:
        raise SelfUpdateToolError(
            "Conversational source self-update is not available on this host; "
            "its packaging, activation and recovery controller currently requires macOS. "
            "No update request was created. For a published version, use "
            "`openprogram upgrade` for the CLI or the Desktop release updater. "
            "Existing self-update status and cancellation remain available."
        )


def _launch_supervisor(update_id: str) -> None:
    from openprogram.operations.self_update.delivery.launcher import launch_supervisor

    launch_supervisor(update_id)


def _require_local_owner(req: Any) -> dict[str, str]:
    authority = normalize_authority(req)
    try:
        installed_owner = owner_principal_id()
    except Exception as exc:
        raise SelfUpdateToolError("interactive local owner identity is unavailable") from exc
    if (
        not authority
        or authority.get("principal_id") != installed_owner
        or authority.get("authority_tier") != "owner"
        or authority.get("speaker_kind") != "owner"
        or authority.get("interaction") != "interactive"
        or getattr(req, "source", None) in _NON_INTERACTIVE_SOURCES
    ):
        raise SelfUpdateToolError("self-update requires an interactive local owner")
    return authority


def _git(cwd: Path, *args: str) -> str:
    from openprogram.host._platform.process_ownership import no_window_creation_flags
    environment = {
        "PATH": os.environ.get(
            "PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
        ),
        "HOME": os.environ.get("HOME", "/var/empty"),
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    command = ["git", "--no-optional-locks"]
    for value in _GIT_CONFIG_OVERRIDES:
        command.extend(("-c", value))
    command.extend(args)
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            creationflags=no_window_creation_flags(),
            timeout=_GIT_TIMEOUT_SECONDS,
            env=environment,
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise SelfUpdateToolError(f"git validation failed: {type(exc).__name__}") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()[:500]
        raise SelfUpdateToolError(f"git validation failed: {message or result.returncode}")
    return result.stdout.rstrip("\n")


def _iteration_policy(value: Mapping[str, Any] | None) -> IterationPolicy:
    if value is None:
        return IterationPolicy()
    if not isinstance(value, Mapping):
        raise SelfUpdateToolError("iteration_policy must be an object")
    allowed = {"mode", "max_attempts", "deadline", "allowed_paths", "required_tests"}
    unknown = set(value) - allowed
    if unknown:
        raise SelfUpdateToolError(
            "iteration_policy contains unsupported fields: " + ", ".join(sorted(unknown))
        )
    for field in ("allowed_paths", "required_tests"):
        raw = value.get(field)
        if raw is not None and not isinstance(raw, list):
            raise SelfUpdateToolError(f"iteration_policy {field} must be an array")
    try:
        policy = IterationPolicy(
            mode=IterationMode(
                value.get("mode", IterationMode.APPROVE_EACH_ACTIVATION.value)
            ),
            max_attempts=value.get("max_attempts", 3),
            deadline=value.get("deadline"),
            allowed_paths=tuple(value.get("allowed_paths") or ()),
            required_tests=tuple(value.get("required_tests") or ()),
        )
    except (TypeError, ValueError) as exc:
        raise SelfUpdateToolError(f"invalid iteration_policy: {exc}") from exc
    if policy.deadline is not None and policy.deadline <= time.time():
        raise SelfUpdateToolError("iteration_policy deadline must be in the future")
    return policy


def _validate_openprogram_repo(source: Path, worktree: Path) -> None:
    if source == worktree:
        raise SelfUpdateToolError("candidate must be an isolated linked worktree")
    try:
        metadata = tomllib.loads((worktree / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SelfUpdateToolError("candidate does not contain readable project metadata") from exc
    project = metadata.get("project")
    if not isinstance(project, dict) or project.get("name") != "openprogram":
        raise SelfUpdateToolError("candidate is not an OpenProgram source checkout")


def _git_directory(cwd: Path) -> Path:
    value = Path(_git(cwd, "rev-parse", "--absolute-git-dir"))
    return value.resolve()


def _recorded_path(value: str, name: str) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise SelfUpdateToolError(f"{name} must be an absolute path")
    lexical = Path(os.path.normpath(str(raw)))
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise SelfUpdateToolError(f"{name} is unavailable") from exc
    if resolved != lexical:
        raise SelfUpdateToolError(f"{name} must not contain symlinks")
    return resolved


def _validate_registered_worktree(
    source: Path, candidate: Path, candidate_sha: str, branch_name: str
) -> None:
    entries = _git(source, "worktree", "list", "--porcelain", "-z").split("\0\0")
    expected = {
        "HEAD": candidate_sha,
        "branch": f"refs/heads/{branch_name}",
    }
    for entry in entries:
        fields = {}
        for line in entry.split("\0"):
            key, separator, value = line.partition(" ")
            if separator:
                fields[key] = value
        # Git emits forward slashes on Windows; compare host paths rather than
        # their serialized spelling while keeping HEAD and branch exact.
        if fields.get("worktree") and Path(fields["worktree"]) == candidate:
            if all(fields.get(key) == value for key, value in expected.items()):
                return
            break
    raise SelfUpdateToolError("candidate does not match its registered Git worktree")


def _validate_candidate_snapshot(candidate: Path, candidate_sha: str) -> None:
    if _git(candidate, "status", "--porcelain=v1", "--untracked-files=all"):
        raise SelfUpdateToolError("candidate worktree is dirty")
    if _git(candidate, "rev-parse", "HEAD") != candidate_sha:
        raise SelfUpdateToolError("candidate_sha is not the worktree HEAD")


def _check_prepare_arguments(candidate_sha, goal, assertions, iteration_policy, verification_plan) -> None:
    """The checks of a prepare call that need nothing but its arguments."""
    if (
        not isinstance(candidate_sha, str)
        or len(candidate_sha) != 40
        or candidate_sha.lower() != candidate_sha
        or any(ch not in "0123456789abcdef" for ch in candidate_sha)
    ):
        raise SelfUpdateToolError("candidate_sha must be a full lowercase Git SHA")
    if not isinstance(goal, str) or not goal.strip():
        raise SelfUpdateToolError("goal is required")
    if (
        not isinstance(assertions, list)
        or not assertions
        or any(not isinstance(value, str) or not value.strip() for value in assertions)
    ):
        raise SelfUpdateToolError("assertions must be a non-empty list of strings")
    _iteration_policy(iteration_policy)
    if verification_plan is not None:
        from types import SimpleNamespace
        from openprogram.operations.self_update.verification.verification_plan import validate_plan
        try:
            validate_plan(verification_plan, SimpleNamespace(assertions=tuple(assertions)))
        except ValueError as exc:
            raise SelfUpdateToolError(f"verification_plan: {exc}") from exc


def _precheck(args: dict) -> str | None:
    """Refuse a prepare call with invalid arguments before it asks for approval."""
    if action_of(args) != "prepare":
        return None
    try:
        _check_prepare_arguments(args.get("candidate_sha"), args.get("goal"), args.get("assertions"),
                                 args.get("iteration_policy"), args.get("verification_plan"))
    except SelfUpdateToolError as exc:
        return str(exc)
    return None


def _has_stable_branch(source: Path) -> bool:
    """With a `stable` branch the App installs only promoted commits
    (openprogram/operations/worker/dev_instance.py), so a candidate goes to the development
    instance instead of the App."""
    result = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "--verify", "--quiet", "refs/heads/stable^{commit}"],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS)
    return result.returncode == 0


def _spawn_detached(command: list[str], *, env: dict[str, str], log: Path) -> None:
    with log.open("ab") as stream:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                         start_new_session=True, close_fds=True, env=env)


def _deploy_candidate_to_dev(source: Path, candidate_sha: str) -> dict[str, Any]:
    """Build the candidate into the development instance, detached from this
    worker; the stable App and its worker are not touched."""
    import sys

    from openprogram.operations.worker import dev_instance

    log = dev_instance.dev_state_dir() / "deploy.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if key != "OPENPROGRAM_PROFILE"}
    env["OPENPROGRAM_SOURCE_REPO"] = str(source)
    _spawn_detached([sys.executable, "-I", "-B", "-m", "openprogram", "dev", "deploy", candidate_sha],
                    env=env, log=log)
    return {
        "phase": "deploying_to_development_instance",
        "candidate_sha": candidate_sha,
        "development_url": f"http://127.0.0.1:{dev_instance.DEV_PORT}",
        "log": str(log),
        "next": (
            "The candidate is being built into the development instance; the stable App is "
            "unchanged. When `openprogram dev status` shows this commit deployed and healthy, "
            "check the change there (sign a browser in with `openprogram dev auth-url`). The stable "
            "App only takes it when the owner promotes: merge the candidate into dev, run "
            "`openprogram dev deploy`, then `openprogram dev promote`."
        ),
    }


def _prepare_update(
    *,
    worktree_id: str,
    candidate_sha: str,
    goal: str,
    assertions: list[str],
    iteration_policy: Mapping[str, Any] | None,
    req: Any,
    assistant_id: str,
    manager: Any,
    store: SelfUpdateStore,
    verification_plan: dict | None = None,
) -> dict[str, Any]:
    _require_local_owner(req)
    if not isinstance(assistant_id, str) or not assistant_id.strip():
        raise SelfUpdateToolError("self-update must run inside a persisted chat turn")
    if not isinstance(worktree_id, str) or not worktree_id.strip():
        raise SelfUpdateToolError("worktree_id is required")
    _check_prepare_arguments(candidate_sha, goal, assertions, iteration_policy, verification_plan)

    worktree = manager.get_worktree(worktree_id)
    if worktree is None:
        raise SelfUpdateToolError(f"worktree does not exist: {worktree_id}")
    if worktree.status is not WorktreeStatus.ACTIVE:
        raise SelfUpdateToolError("candidate worktree must be active")
    if worktree.parent_session != req.session_id:
        raise SelfUpdateToolError("candidate worktree is not owned by this session")

    source = _recorded_path(worktree.source_repo, "source repo")
    candidate = _recorded_path(worktree.worktree_path, "candidate worktree")
    _validate_openprogram_repo(source, candidate)
    candidate_common = Path(_git(candidate, "rev-parse", "--git-common-dir"))
    if not candidate_common.is_absolute():
        candidate_common = candidate / candidate_common
    if candidate_common.resolve() != _git_directory(source):
        raise SelfUpdateToolError("candidate worktree is not linked to its source repo")
    if Path(_git(candidate, "rev-parse", "--show-toplevel")).resolve() != candidate:
        raise SelfUpdateToolError("candidate path is not the worktree root")
    _validate_registered_worktree(
        source, candidate, candidate_sha, worktree.branch_name
    )
    _validate_candidate_snapshot(candidate, candidate_sha)

    base_sha = _git(source, "rev-parse", "HEAD")
    if base_sha == candidate_sha:
        raise SelfUpdateToolError("candidate must differ from the source checkout HEAD")
    if _git(candidate, "merge-base", base_sha, candidate_sha) != base_sha:
        raise SelfUpdateToolError("candidate is not based on the source checkout HEAD")
    changed = tuple(
        path
        for path in _git(
            candidate,
            "diff",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            "-z",
            f"{base_sha}..{candidate_sha}",
        ).split("\0")
        if path
    )
    if not changed:
        raise SelfUpdateToolError("candidate commit contains no changes")
    if any(any(ord(char) < 32 for char in path) for path in changed):
        raise SelfUpdateToolError("candidate contains unsupported control characters in paths")

    policy = _iteration_policy(iteration_policy)
    if policy.mode is IterationMode.BOUNDED_AUTO:
        outside = [
            path
            for path in changed
            if not any(fnmatch.fnmatchcase(path, pattern) for pattern in policy.allowed_paths)
        ]
        if outside:
            raise SelfUpdateToolError(
                "candidate changes paths outside iteration_policy: " + ", ".join(outside)
            )

    if _has_stable_branch(source):
        return _deploy_candidate_to_dev(source, candidate_sha)
    origin_turn_id = getattr(req, "user_msg_id", None)
    if not origin_turn_id and assistant_id.endswith("_reply"):
        origin_turn_id = assistant_id[: -len("_reply")]
    request = UpdateRequest(
        update_id=mint_update_id(),
        session_id=req.session_id,
        origin_turn_id=origin_turn_id or assistant_id,
        origin_assistant_id=assistant_id,
        agent_id=req.agent_id,
        repo=os.path.normpath(str(source)),
        worktree_id=worktree.id,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        changed_paths=changed,
        pre_update_evidence=(
            "git-status:clean",
            f"source-head:{base_sha}",
            f"candidate-head:{candidate_sha}",
        ),
        goal=goal.strip(),
        assertions=tuple(value.strip() for value in assertions),
        iteration_policy=policy,
    )
    try:
        from openprogram.operations.self_update.verification.verifier_config import freeze_verifier_config
        from openprogram.operations.self_update.verification.verifier_config import config_evidence
        from openprogram.operations.self_update.repair.diagnosis import freeze_config
        from openprogram.operations.self_update.repair.diagnosis import config_evidence as diagnosis_evidence
        from openprogram.operations.self_update.control.continuation import freeze_config as freeze_continuation
        from openprogram.operations.self_update.control.continuation import config_evidence as continuation_evidence
        continuation_config = freeze_continuation(request, req)
        verifier_config = freeze_verifier_config(request, req, verification_plan=verification_plan)
        diagnosis_config = freeze_config(request, verifier_config)
        from openprogram.operations.self_update.repair.source_repair import freeze_config as freeze_repair
        from openprogram.operations.self_update.repair.source_repair import config_evidence as repair_evidence
        repair_config = freeze_repair(request, verifier_config, candidate_path=str(candidate), branch_name=worktree.branch_name)
        from openprogram.operations.self_update.repair.next_candidate import root_config
        from openprogram.operations.self_update.repair.next_candidate import config_evidence as iteration_evidence
        iteration_config = root_config(request)
        if policy.mode is IterationMode.BOUNDED_AUTO and (policy.deadline is None or policy.deadline <= time.time()
                                                        or not policy.required_tests):
            raise ValueError("bounded_auto requires a future total deadline and non-empty required_tests")
        if policy.deadline is not None:
            request = replace(request, timeout_seconds=min(request.timeout_seconds, int(policy.deadline - request.created_at)))
        request = replace(request, pre_update_evidence=(*request.pre_update_evidence, config_evidence(verifier_config),
                                                       diagnosis_evidence(diagnosis_config), repair_evidence(repair_config),
                                                       iteration_evidence(iteration_config), continuation_evidence(continuation_config)))
        state = store.create(request, verifier_config=verifier_config, diagnosis_config=diagnosis_config,
                             source_repair_config=repair_config, iteration_config=iteration_config, continuation_config=continuation_config)
    except ActiveUpdateError as exc:
        raise SelfUpdateToolError(str(exc)) from exc
    except (SelfUpdateError, ValueError) as exc:
        raise SelfUpdateToolError(str(exc)) from exc
    try:
        _validate_registered_worktree(
            source, candidate, candidate_sha, worktree.branch_name
        )
        _validate_candidate_snapshot(candidate, candidate_sha)
    except SelfUpdateToolError as exc:
        try:
            store.transition(
                request.update_id,
                UpdatePhase.ABORTED,
                expected_phase=UpdatePhase.PREPARING,
                detail={"reason": "candidate drifted during prepare"},
            )
        except SelfUpdateError as abort_exc:
            raise SelfUpdateToolError(
                f"{exc}; failed to abort prepared request: {abort_exc}"
            ) from abort_exc
        raise
    try:
        _launch_supervisor(request.update_id)
    except Exception as exc:
        try:
            store.transition(
                request.update_id,
                UpdatePhase.ABORTED,
                expected_phase=UpdatePhase.PREPARING,
                detail={"reason": "supervisor launch failed", "error": str(exc)[:1000]},
            )
        except SelfUpdateError as abort_exc:
            raise SelfUpdateToolError(
                f"supervisor launch failed: {exc}; request abort failed: {abort_exc}"
            ) from abort_exc
        raise SelfUpdateToolError(f"supervisor launch failed: {exc}") from exc
    from openprogram.operations.self_update.delivery.activation import predict
    activation = predict(Path(request.app_path), candidate, candidate_sha)
    return {
        "update_id": request.update_id,
        "phase": state.phase.value,
        "candidate_sha": candidate_sha,
        "base_sha": base_sha,
        "changed_paths": list(changed),
        # hot: nothing restarts; worker: the worker restarts, the App stays
        # open; app: the App quits and reopens.
        "restart": activation.restart,
        "rebuild": list(activation.components) if activation.scope == "incremental" else "complete App",
        "turn_release_pending": True,
    }


def _resolve_record(update_id: str | None, store: SelfUpdateStore):
    if update_id:
        return store.load(update_id)
    record = store.load_active()
    if record is None:
        raise SelfUpdateToolError("no active self-update")
    return record


def _status_update(
    *, update_id: str | None, req: Any, store: SelfUpdateStore
) -> dict[str, Any]:
    _require_local_owner(req)
    from openprogram.operations.self_update.control.projection import ProjectionAccessError
    from openprogram.operations.self_update.control.projection import read_status
    from openprogram.operations.self_update.types import UpdateNotFoundError
    try:
        return read_status(store, session_id=req.session_id, update_id=update_id)
    except ProjectionAccessError:
        raise SelfUpdateToolError("self-update belongs to another origin session") from None
    except UpdateNotFoundError:
        raise SelfUpdateToolError("no matching self-update") from None
    except (SelfUpdateError, ValueError, OSError, KeyError, TypeError):
        raise SelfUpdateToolError("self-update state is unavailable or inconsistent") from None


def _turn_context() -> tuple[Any, str]:
    req = get_turn_request()
    if req is None:
        raise SelfUpdateToolError("self-update tool requires an active chat turn")
    from openprogram.state.store import _current_turn_id

    assistant_id = _current_turn_id.get()
    if not assistant_id:
        raise SelfUpdateToolError("self-update tool requires an active assistant turn")
    return req, assistant_id


ACTIONS = ("status", "prepare", "retry", "cancel")
# Actions the owner signs on a card, even in bypass; each binds one exact candidate.
APPROVED_ACTIONS = frozenset({"prepare", "retry"})


def action_of(args: Mapping[str, Any] | None) -> str:
    """The action a ``self_update`` call names; an omitted action reads status."""
    value = (args or {}).get("action") if isinstance(args, Mapping) else None
    return str(value or "status")


def _overview() -> str:
    return """
        Change and install OpenProgram itself, from a commit in an isolated worktree.

        1. worktree_create a worktree of the OpenProgram repo; edit, test and commit there.
        2. self_update(action="prepare", ...) with that worktree and commit. The owner approves
           a card; the supervisor then rebuilds only the changed parts, installs, verifies the
           assertions and rolls back on failure. The call returns once the request is saved.
        3. self_update() reads status. After a rollback the supervisor diagnoses, repairs the
           source in isolation and tests it; a tested repair is installed with action="retry".
        4. self_update(action="cancel") stops this session's update and everything it started.
           A transaction that already activated still finishes verification or rollback.

        What restarts depends on the changed paths: web, docs and terminal UI swap in while
        everything runs; Python restarts only the worker; the Desktop shell or dependencies
        restart the App. Published CLI/Desktop releases use `openprogram upgrade` instead.
    """


def _prepare_guide() -> str:
    from openprogram.operations.self_update.verification.native_checks import NATIVE_ENTRIES
    from openprogram.operations.self_update.verification.system_probe import DOCS_PAGE, OBSERVATION_ENTRIES
    entries = ", ".join(sorted({*OBSERVATION_ENTRIES, *NATIVE_ENTRIES, "ui:main", DOCS_PAGE}))
    return f"""
        self_update(action="prepare", worktree_id, candidate_sha, goal, assertions,
                    iteration_policy=None, verification_plan=None)

        - worktree_id: an active worktree this session created of the OpenProgram repo.
        - candidate_sha: the full 40-character lowercase SHA of its clean HEAD; it must be
          based on the source checkout HEAD and change at least one path.
        - goal: one sentence on what the change is for.
        - assertions: non-empty list of observable facts the installed App must satisfy.
          They are numbered acceptance-1, acceptance-2, ... in order.
        - iteration_policy: {{"mode": "approve_each_activation" | "bounded_auto",
          "max_attempts": 1-3 (default 3), "deadline": unix seconds, "allowed_paths": [globs],
          "required_tests": [test paths]}}. The default mode asks the owner for each new SHA.
          bounded_auto lets repairs install without another card, inside the attempt budget,
          a future deadline, allowed_paths (the first candidate must fit them too) and
          non-empty required_tests.
        - verification_plan: {{"schema": 1, "checks": [...]}} with one check per assertion:
          {{"id", "assertion_id": "acceptance-N", "entry", "timeout_seconds": 1-60,
          "max_output_bytes": 1-262144 (1-1572864 for ui:main)}}. entry is one of: {entries}.
          /docs/<path>.html reads a page of the installed docs site (for documentation
          changes, e.g. /docs/install/upgrade.html for docs/install/upgrade.md);
          "test:python" adds "argv": [relative script.py, ...] run in the candidate;
          "ui:main" captures the main window (the model needs image input) and may add
          "interaction": {{"kind": "scroll", "delta_y": -1200..1200}} or
          {{"kind": "view", "target": "session" | "dag"}}.
          Without a plan the verifier judges the assertions from its own observations.

        The approval also permits pausing and resuming active tasks at a safe point, a
        follow-up turn in this session after the update, and isolated repair with the listed
        tests after a rollback. The result names the update_id, the predicted restart
        (hot / worker / app) and what will be rebuilt.
    """


def _retry_guide() -> str:
    return """
        self_update(action="retry", update_id, candidate_sha)

        After a rollback, status shows the repaired candidate the supervisor tested. retry
        submits exactly that SHA as the next attempt of the same update: the original goal,
        assertions, scope, model and attempt budget carry over. The owner approves a card
        that shows the candidate's changed paths, tests and remaining budget. The result is
        the new child request, not proof that it installed; read status afterwards.
    """


def _requires_approval(action: str = "status", **_: Any) -> bool:
    return str(action or "status") in APPROVED_ACTIONS


@function(
    name="self_update",
    description=(
        "Install a committed change to OpenProgram itself and follow it through build, "
        "verification, rollback and repair. When the repository has a `stable` branch, prepare "
        "deploys the candidate to the development instance (port 18200) instead, and the stable "
        "App changes only when the owner promotes it. "
        "Actions: status (default), prepare, retry, cancel. "
        "The first result explains the workflow; each action's parameters come from help."
    ),
    toolset=["core"],
    requires_approval=_requires_approval,
    path_params={},
)
def self_update(
    action: str = "status",
    update_id: str | None = None,
    worktree_id: str | None = None,
    candidate_sha: str | None = None,
    goal: str | None = None,
    assertions: list[str] | None = None,
    iteration_policy: dict[str, Any] | None = None,
    verification_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one self-update action.

    Args:
        action: status, prepare, retry or cancel.
        update_id: The update to read, retry or cancel; defaults to this session's active one.
        worktree_id: prepare: the worktree holding the candidate commit.
        candidate_sha: prepare, retry: the exact commit to install.
        goal: prepare: what the change is for.
        assertions: prepare: facts the installed App must satisfy.
        iteration_policy: prepare: approval mode and repair budget.
        verification_plan: prepare: checks bound to each assertion.
    """
    if action in APPROVED_ACTIONS:
        _require_update_backend()
    req, assistant_id = _turn_context()
    if action == "status":
        return _status_update(update_id=update_id, req=req, store=SelfUpdateStore())
    if action == "cancel":
        return _cancel_iteration(update_id=update_id, req=req, store=SelfUpdateStore())
    if action == "prepare":
        return _prepare_update(
            worktree_id=worktree_id or "",
            candidate_sha=candidate_sha or "",
            goal=goal or "",
            assertions=assertions,
            iteration_policy=iteration_policy,
            req=req,
            assistant_id=assistant_id,
            manager=get_manager(),
            store=SelfUpdateStore(),
            verification_plan=verification_plan,
        )
    if action == "retry":
        from openprogram.operations.self_update.repair.next_candidate import submit
        return submit(update_id, candidate_sha, req=req, assistant_id=assistant_id)
    raise SelfUpdateToolError(f"unknown action {action!r}; use one of {', '.join(ACTIONS)}")


def _cancel_iteration(*, update_id: str | None, req: Any, store: SelfUpdateStore) -> dict[str, Any]:
    """Stop this session's update and everything its iteration started."""
    _require_local_owner(req)
    from openprogram.operations.self_update.repair import next_candidate
    try:
        record = _resolve_record(update_id, store)
    except SelfUpdateError as exc:
        raise SelfUpdateToolError(str(exc)) from exc
    if record.request.session_id != req.session_id:
        raise SelfUpdateToolError("self-update belongs to another session")
    if next_candidate._config(store, record) is None:
        # A request without frozen iteration configuration has nothing to stop
        # but itself, and only before activation.
        return _abort_request(record, req=req, store=store)
    try:
        return next_candidate.cancel(record.request.update_id, req, store)
    except (SelfUpdateError, ValueError) as exc:
        raise SelfUpdateToolError(str(exc)) from exc


def _abort_request(record: Any, *, req: Any, store: SelfUpdateStore) -> dict[str, Any]:
    if record.state.phase not in {UpdatePhase.PREPARING, UpdatePhase.STAGING, UpdatePhase.READY}:
        raise SelfUpdateToolError(f"cannot cancel self-update in {record.state.phase.value}")
    try:
        state = store.transition(
            record.request.update_id,
            UpdatePhase.ABORTED,
            expected_phase=record.state.phase,
            detail={**record.state.detail, "reason": "owner requested cancellation",
                    "cancelled_by_session": req.session_id},
        )
    except SelfUpdateError as exc:
        raise SelfUpdateToolError(str(exc)) from exc
    return {"update_id": record.request.update_id, "status": "stopped", "phase": state.phase.value}


from openprogram.programs._authoring import guides as _guides
from openprogram.programs._authoring import prechecks as _prechecks

_prechecks.register("self_update", _precheck)

_guides.register("self_update", [
    _guides.Guide("self_update", _overview, mode="open", activates=("worktree_create",)),
    _guides.Guide("self_update.prepare", _prepare_guide, summary="parameters, iteration policy and verification plan",
                  required_for=lambda args: action_of(args) == "prepare"),
    _guides.Guide("self_update.retry", _retry_guide, summary="install the repaired candidate after a rollback",
                  required_for=lambda args: action_of(args) == "retry"),
])


@function(
    name="self_update_observe",
    description=("For the active post-update verifier only: execute an approved frozen check_id "
                 "and save identity-bound evidence (local HTTP, fixed CLI, candidate script or main-window capture). "
                 "Do not supply execution arguments. Legacy requests accept entry: /api/commands, /api/diagnostics, "
                 "/api/doctor, /healthz, /chat, or a docs page /docs/<path>.html. "
                 "HTML and candidate tests are not installed UI evidence."),
    toolset=["core"],
    path_params={},
)
def self_update_observe(entry: str = "", check_id: str | None = None) -> dict[str, Any]:
    from openprogram.operations.self_update.verification.verification_channel import observe
    result = observe(entry, check_id=check_id)
    if result["entry"] == "ui:main":
        from openprogram.models.providers.types import AgentToolResult
        from openprogram.models.providers.types import ImageContent, TextContent
        capture = json.loads(result["body"])
        image = capture["screenshot"].pop("data")
        result["body"] = json.dumps(capture, allow_nan=False)
        return AgentToolResult(content=[TextContent(text=json.dumps(result, allow_nan=False)),
                                        ImageContent(data=image, mime_type="image/png")])
    return result


__all__ = ["self_update", "self_update_observe", "action_of", "APPROVED_ACTIONS"]
