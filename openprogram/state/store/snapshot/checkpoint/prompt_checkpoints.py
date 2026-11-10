"""One recovery point per prompt that starts a turn.

Layout under ``.file-recovery/<session_id>/``::

    checkpoints/<user_msg_id>.json   # {path: state} at the moment of the prompt
    blobs/<sha256>                   # immutable content shared by checkpoints

A checkpoint lists every file the session has edited so far, so a change made
by a shell command or by hand between prompts is captured by the next prompt.
A file first appears in the checkpoint of the prompt whose turn first edits it.
Capturing never fails the turn or the tool: a file that cannot be read is
recorded as ``unavailable`` and shows up as skipped at restore time.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from openprogram.host._platform.filesystem import is_link_metadata

from . import manifest
from .paths import session_backup_root

_log = logging.getLogger(__name__)

CHECKPOINT_DIRECTORY = "checkpoints"
BLOB_DIRECTORY = "blobs"
ORIGIN_FILE = "origin.json"
MAX_WRITERS_PER_PATH = 32


def _unavailable(reason: str) -> dict:
    return {"kind": "unavailable", "reason": reason}


class PromptCheckpoints:
    def __init__(self, session_dir: Path):
        self.root = session_backup_root(Path(session_dir))
        self.directory = self.root / CHECKPOINT_DIRECTORY
        self.blobs = self.root / BLOB_DIRECTORY

    @contextmanager
    def _lock(self):
        from openprogram.host._platform import locking

        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / ".lock").open("a+") as handle:
            locking.flock(handle.fileno(), locking.LOCK_EX)
            try:
                yield
            finally:
                locking.flock(handle.fileno(), locking.LOCK_UN)

    def _path(self, user_msg_id: str) -> Path:
        return self.directory / f"{user_msg_id}.json"

    def get(self, user_msg_id: str) -> dict | None:
        try:
            value = json.loads(self._path(user_msg_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def all(self) -> list[dict]:
        """Every readable checkpoint, oldest first."""
        rows: list[dict] = []
        try:
            names = [item.name for item in os.scandir(self.directory)]
        except OSError:
            return rows
        for name in names:
            if name.startswith(".") or not name.endswith(".json"):
                continue
            value = self.get(name[:-len(".json")])
            if value is not None:
                rows.append(value)
        rows.sort(key=lambda row: int(row.get("sequence") or 0))
        return rows

    def ids(self) -> set[str]:
        try:
            return {
                item.name[:-len(".json")] for item in os.scandir(self.directory)
                if item.name.endswith(".json") and not item.name.startswith(".")
            }
        except OSError:
            return set()

    def capture(self, user_msg_id: str) -> None:
        """Record the tracked files as they are when a prompt starts a turn."""
        with self._lock():
            if self._path(user_msg_id).exists():
                return
            rows = self.all()
            latest = rows[-1] if rows else {}
            files = {
                path: self._refresh(path, entry)
                for path, entry in (latest.get("files") or {}).items()
            }
            manifest.save(self._path(user_msg_id), {
                "version": 1,
                "user_msg_id": user_msg_id,
                "sequence": int(latest.get("sequence") or 0) + 1,
                "created_at": time.time(),
                "files": files,
            })

    def track(self, abs_path: str, content_src: str | Path | None = None) -> None:
        """Add a file to the current checkpoint before its first edit."""
        with self._lock():
            rows = self.all()
            if not rows:
                return
            latest = rows[-1]
            files = latest.setdefault("files", {})
            if abs_path in files:
                return
            files[abs_path] = self._snapshot(abs_path, content_src)
            manifest.save(self._path(str(latest["user_msg_id"])), latest)

    def _refresh(self, path: str, entry: dict) -> dict:
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return {"kind": "absent"}
        except OSError:
            return _unavailable("unreadable")
        if (
            entry.get("kind") == "regular"
            and stat.S_ISREG(info.st_mode)
            and entry.get("size") == info.st_size
            and entry.get("mtime_ns") == info.st_mtime_ns
        ):
            return entry
        return self._snapshot(path)

    def _snapshot(self, path: str, content_src: str | Path | None = None) -> dict:
        source = str(content_src) if content_src is not None else path
        # Read before the file, so a write racing this capture counts as later.
        sequence = current_mutation_sequence()
        try:
            info = os.lstat(source)
        except FileNotFoundError:
            return {"kind": "absent", "captured_sequence": sequence}
        except OSError:
            return _unavailable("unreadable")
        if is_link_metadata(info) or not stat.S_ISREG(info.st_mode):
            return _unavailable("unsafe_file_type")
        try:
            digest = self.store_blob(source)
        except OSError:
            _log.warning("checkpoint could not capture %s", path, exc_info=True)
            return _unavailable("unreadable")
        return {
            "kind": "regular",
            "digest": f"sha256:{digest}",
            "mode": f"{stat.S_IMODE(info.st_mode):04o}",
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "captured_sequence": sequence,
        }

    def store_blob(self, source: str | Path) -> str:
        """Copy a regular file into the shared store; return its hex digest."""
        self.blobs.mkdir(parents=True, exist_ok=True)
        temporary = self.blobs / f".tmp-{uuid.uuid4().hex}"
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            with os.fdopen(os.open(source, flags), "rb") as handle:
                before = os.fstat(handle.fileno())
                digest = hashlib.sha256()
                output_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
                with os.fdopen(os.open(temporary, output_flags, 0o600), "wb") as output:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        output.write(chunk)
                        digest.update(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                after = os.fstat(handle.fileno())
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                raise OSError(f"{source} changed while reading")
            name = digest.hexdigest()
            destination = self.blobs / name
            if destination.exists():
                return name
            os.replace(temporary, destination)
            return name
        finally:
            temporary.unlink(missing_ok=True)

    def blob_path(self, digest: str) -> Path:
        return self.blobs / str(digest).removeprefix("sha256:")

    def targets(self, user_ids_oldest_first: list[str]) -> dict[str, dict] | None:
        """Each tracked file's state at the first prompt of the list.

        A file the first checkpoint does not list had not been edited yet, so
        its state is the one recorded just before its first later edit.
        ``None`` means the prompt has no checkpoint.
        """
        if not user_ids_oldest_first:
            return None
        target = self.get(user_ids_oldest_first[0])
        if target is None:
            return None
        states = dict(target.get("files") or {})
        for user_id in user_ids_oldest_first[1:]:
            later = self.get(user_id) or {}
            for path, entry in (later.get("files") or {}).items():
                states.setdefault(path, entry)
        return {path: self._with_blob(entry) for path, entry in states.items()}

    def _with_blob(self, entry: dict) -> dict:
        value = dict(entry)
        if value.get("kind") != "regular":
            return value
        blob = self.blob_path(str(value.get("digest") or ""))
        if not blob.is_file():
            return _unavailable("backup_missing")
        value["blob_path"] = str(blob)
        value.pop("mtime_ns", None)
        return value

    def read_origin(self) -> dict:
        try:
            value = json.loads((self.root / ORIGIN_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}


def carry_checkpoints(
    source_session_dir: Path,
    target_session_dir: Path,
    id_map: dict[str, str],
    *,
    source_session_id: str,
) -> int:
    """Copy a session's checkpoints for the copied messages to a new session.

    A checkpoint is recorded only after every blob it refers to is in place.
    """
    source = PromptCheckpoints(source_session_dir)
    target = PromptCheckpoints(target_session_dir)
    carried = 0
    for row in source.all():
        new_id = id_map.get(str(row.get("user_msg_id")))
        if not new_id:
            continue
        try:
            for entry in (row.get("files") or {}).values():
                if entry.get("kind") == "regular":
                    _copy_blob(source, target, str(entry.get("digest") or ""))
        except OSError:
            _log.warning("checkpoint %s not carried", row.get("user_msg_id"), exc_info=True)
            continue
        manifest.save(target._path(new_id), {**row, "user_msg_id": new_id})
        carried += 1
    if carried:
        manifest.save(target.root / ORIGIN_FILE, {
            "source_session_id": source_session_id,
            "through_sequence": current_mutation_sequence(),
        })
    return carried


def _copy_blob(source: PromptCheckpoints, target: PromptCheckpoints, digest: str) -> None:
    from_path = source.blob_path(digest)
    to_path = target.blob_path(digest)
    if to_path.exists():
        return
    target.blobs.mkdir(parents=True, exist_ok=True)
    temporary = target.blobs / f".tmp-{uuid.uuid4().hex}"
    try:
        shutil.copyfile(from_path, temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, to_path)
    finally:
        temporary.unlink(missing_ok=True)


def _writers_root() -> Path:
    from openprogram.state.paths import get_state_dir

    return get_state_dir() / "mutation-locks" / "last-writers"


def _writers_file(path: str) -> Path:
    name = hashlib.sha256(path.encode("utf-8")).hexdigest()[:32]
    return _writers_root() / f"{name}.json"


def _read_writers(path: str) -> tuple[dict[str, int], dict[str, int]]:
    """``(finished, started)``: each session's newest write to a path."""
    try:
        value = json.loads(_writers_file(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    if not isinstance(value, dict):
        return {}, {}
    if "finished" not in value and value.get("session"):
        return {str(value["session"]): int(value.get("sequence") or 0)}, {}
    return dict(value.get("finished") or {}), dict(value.get("started") or {})


def record_writer(path: str, session: str, sequence: int, stage: str) -> None:
    """Note a session's write to a path through a trusted tool.

    ``stage`` is ``started`` before the file changes, ``finished`` once the
    change is journaled and ``aborted`` when it never happened. A ``started``
    write counts until one of the others arrives, so a rewind planned in the
    middle of another session's edit leaves that file alone. Callers hold the
    workspace sequence lock.
    """
    finished, started = _read_writers(path)
    if stage == "started":
        started[session] = sequence
    else:
        started.pop(session, None)
        if stage == "finished":
            finished[session] = sequence
    newest = dict(sorted(finished.items(), key=lambda item: item[1])[-MAX_WRITERS_PER_PATH:])
    root = _writers_root()
    root.mkdir(parents=True, exist_ok=True)
    manifest.save(_writers_file(path), {"path": path, "finished": newest, "started": started})


def writers_after(path: str, sequence: int) -> list[tuple[str, int]]:
    """Each session's newest write to a path later than ``sequence``."""
    finished, started = _read_writers(path)
    latest: dict[str, int] = {}
    for session, value in (*finished.items(), *started.items()):
        latest[session] = max(latest.get(session, 0), int(value))
    return [(session, value) for session, value in latest.items() if value > sequence]


def current_mutation_sequence() -> int:
    from openprogram.state.paths import get_state_dir

    counter = get_state_dir() / "mutation-locks" / "workspace-sequence"
    try:
        return int(counter.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return 0
