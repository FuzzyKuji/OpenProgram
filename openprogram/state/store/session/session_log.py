"""One conversation, one append-only log.

A session is the set of records in its directory:

    <session>/main.jsonl          written by the process holding worker.lock
    <session>/agents/<id>.jsonl   one file per other writing process

Every file has exactly one writer, so no record is ever overwritten and no
file needs a lock. A session's state is the fold of its records in timestamp
order; the same fold rebuilds it after a restart. A line is a JSON object
ending in a CRC of everything before it, so a line cut short by a dying
process is recognised and dropped instead of being half-applied.

Record types:

    node.put     {payload}                a node's full content
    node.patch   {id, set, metadata}      changed fields of a node
    node.delete  {ids}                    nodes removed from the session
    meta.patch   {set, unset}             changed session-level fields
    file.put     {name, content}          a small state file's new content

Unknown types are skipped by the fold, so runtime records can share the file.
"""
from __future__ import annotations

import base64
import copy
import json
import logging
import os
import threading
import time
import uuid
import zlib
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from openprogram.host._platform.filesystem import filesystem_path, remove_tree

_log = logging.getLogger(__name__)

TURN_RECORD_PREFIX = "turn."
RUN_ROWS_RECORD = "turn.rows"
RUN_ROWS_MARKER = b'"turn.rows"'
MAIN_LOG = "main.jsonl"
AGENT_LOG_DIRECTORY = "agents"

_CRC_FIELD = ',"crc":"'
_CRC_SUFFIX_LENGTH = len(_CRC_FIELD) + 8 + len('"}')
_APPEND_FLAGS = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
_META_CACHE_CAPACITY = 1024


# Records


def encode_record(timestamp: int, record_type: str, data: Any) -> bytes:
    """One log line: the record, then a CRC of the bytes before the CRC field."""
    if record_type == "node.patch":
        metadata = data.get("metadata") or {}
        extra = metadata.get("extra")
        if isinstance(extra, str) and len(extra) >= 8192:
            packed = base64.b64encode(zlib.compress(extra.encode("utf-8"), level=1)).decode("ascii")
            if len(packed) < len(extra):
                data = {**data, "metadata": {k: v for k, v in metadata.items() if k != "extra"},
                        "extra_zlib": packed}
    body = json.dumps(
        {"ts": timestamp, "type": record_type, "data": data},
        ensure_ascii=False, default=str, separators=(",", ":"),
    )[:-1].encode("utf-8")
    checksum = zlib.crc32(body) & 0xFFFFFFFF
    return body + f'{_CRC_FIELD}{checksum:08x}"}}\n'.encode("ascii")


def decode_line(line: bytes) -> Optional[dict]:
    """The record on ``line`` (no newline), or None when it fails its CRC."""
    if len(line) <= _CRC_SUFFIX_LENGTH:
        return None
    body, suffix = line[:-_CRC_SUFFIX_LENGTH], line[-_CRC_SUFFIX_LENGTH:]
    if not suffix.startswith(_CRC_FIELD.encode("ascii")):
        return None
    try:
        expected = int(suffix[len(_CRC_FIELD):len(_CRC_FIELD) + 8], 16)
    except ValueError:
        return None
    if zlib.crc32(body) & 0xFFFFFFFF != expected:
        return None
    try:
        record = json.loads(body + b"}")
        data = record.get("data")
        if record.get("type") == "node.patch" and isinstance(data, dict) and "extra_zlib" in data:
            packed = base64.b64decode(data.pop("extra_zlib"), validate=True)
            data.setdefault("metadata", {})["extra"] = zlib.decompress(packed).decode("utf-8")
        return record
    except (ValueError, TypeError, zlib.error):
        return None


def read_appended(path: Path, start: int = 0, *, containing: bytes | None = None,
                  ) -> tuple[list[dict], int, bool]:
    """Whole records in ``path`` after byte ``start``.

    Returns the records, the offset to continue from, and whether reading
    stopped at a damaged line. Bytes after the last newline are a write still
    in progress or cut short, and are never a record. ``containing`` skips,
    undecoded, every line without those bytes.
    """
    try:
        with open(filesystem_path(path), "rb") as handle:
            handle.seek(start)
            content = handle.read()
    except OSError:
        return [], start, False
    end = content.rfind(b"\n")
    if end < 0:
        return [], start, False
    records: list[dict] = []
    for line in content[:end].split(b"\n"):
        if containing is not None and containing not in line:
            continue
        record = decode_line(line)
        if record is None:
            _log.error("session log %s is damaged after byte %d; reading stops there",
                       path, start)
            return records, start + end + 1, True
        records.append(record)
    return records, start + end + 1, False


def read_log_file(path: Path, *, containing: bytes | None = None) -> list[dict]:
    """Every whole record in ``path``, stopping at the first damaged line."""
    return read_appended(path, containing=containing)[0]


# Fold


@dataclass
class FoldedSession:
    """What a session's records add up to."""

    nodes: dict[str, dict] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)


def apply_record(state: FoldedSession, record: dict) -> None:
    """Advance ``state`` by one record."""
    record_type = record.get("type")
    data = record.get("data") or {}
    if record_type == "node.put":
        payload = data.get("payload") or {}
        node_id = payload.get("id")
        if node_id:
            state.nodes[node_id] = payload
    elif record_type == "node.patch":
        node = state.nodes.get(data.get("id"))
        if node is None:
            return
        # A new dict: earlier folds handed this payload out to readers.
        node = {**node, **(data.get("set") or {})}
        state.nodes[data["id"]] = node
        metadata = data.get("metadata")
        if metadata:
            current = node.get("metadata")
            node["metadata"] = {**(current if isinstance(current, dict) else {}), **metadata}
    elif record_type == "node.delete":
        for node_id in data.get("ids") or []:
            state.nodes.pop(node_id, None)
    elif record_type == "meta.patch":
        state.meta.update(data.get("set") or {})
        for key in data.get("unset") or []:
            state.meta.pop(key, None)
    elif record_type == "file.put":
        name = data.get("name")
        if not name:
            return
        if data.get("content") is None:
            state.files.pop(name, None)
        else:
            state.files[name] = data["content"]


@dataclass
class _LogPosition:
    offset: int = 0
    inode: int = 0
    damaged: bool = False


@dataclass
class _FoldProgress:
    """How far a session's files have been folded, and what that added up to."""

    positions: dict[str, _LogPosition] = field(default_factory=dict)
    folded: FoldedSession = field(default_factory=FoldedSession)
    newest: int = 0


def fold_records(records: Iterable[dict]) -> FoldedSession:
    state = FoldedSession()
    for record in records:
        apply_record(state, record)
    return state


def node_sort_key(payload: dict) -> tuple:
    return (int(payload.get("seq", -1)), str(payload.get("role") or "x")[:1],
            str(payload.get("id") or ""))


# Process identity and clock


_main_writer_pid: Optional[int] = None
_agent_log_name: tuple[int, str] | None = None
_clock_lock = threading.Lock()
_last_timestamp = 0
# Serialises appends to one file from threads in this process.
_append_locks = tuple(threading.Lock() for _ in range(64))
# Files whose tail this process has already checked.
_prepared_files: set[str] = set()
_meta_cache: "OrderedDict[str, tuple[tuple, dict]]" = OrderedDict()
_meta_cache_lock = threading.Lock()
# Told of each durable conversation write by this process, and nothing else.
_record_observer: Optional[Any] = None
_record_observer_pid: Optional[int] = None
_foreign_change_observer: Optional[Any] = None
_OBSERVED_RECORDS = {"node.put", "node.patch", "node.delete", "meta.patch"}


def set_record_observer(observer: Optional[Any]) -> None:
    """``observer(session_id, record_type, node_ids, changed_keys)`` after each conversation write."""
    global _record_observer, _record_observer_pid
    _record_observer = observer
    _record_observer_pid = os.getpid()


def set_foreign_change_observer(observer: Optional[Any]) -> None:
    """``observer(session_id)`` when this process finds another process's writes."""
    global _foreign_change_observer
    _foreign_change_observer = observer


def report_foreign_change(session_id: str) -> None:
    observer = _foreign_change_observer
    if observer is not None:
        observer(session_id)


def _observed_change(record_type: str, data: dict) -> tuple[tuple[str, ...], frozenset[str]]:
    """The ids a record touches and the keys it changed."""
    if record_type == "node.put":
        payload = data.get("payload") or {}
        return ((payload["id"],) if payload.get("id") else ()), frozenset(payload)
    if record_type == "node.patch":
        return (str(data.get("id") or ""),), frozenset((data.get("set") or {})) | frozenset((data.get("metadata") or {}))
    if record_type == "node.delete":
        return tuple(data.get("ids") or ()), frozenset()
    return (), frozenset((data.get("set") or {})) | frozenset(data.get("unset") or ())


def claim_main_writer() -> None:
    """This process now holds worker.lock and writes ``main.jsonl``."""
    global _main_writer_pid
    _main_writer_pid = os.getpid()


def release_main_writer() -> None:
    global _main_writer_pid
    _main_writer_pid = None


def is_main_writer() -> bool:
    return _main_writer_pid == os.getpid()


def _next_timestamp() -> int:
    global _last_timestamp
    with _clock_lock:
        _last_timestamp = max(_last_timestamp + 1, time.time_ns())
        return _last_timestamp


def _this_process_agent_log() -> str:
    global _agent_log_name
    pid = os.getpid()
    if _agent_log_name is None or _agent_log_name[0] != pid:
        _agent_log_name = (pid, f"{pid}-{uuid.uuid4().hex[:8]}.jsonl")
    return _agent_log_name[1]


def _discard_torn_tail(path: Path) -> None:
    """Cut bytes after the last newline left by a writer that died mid-line."""
    native = filesystem_path(path)
    try:
        with open(native, "r+b") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size == 0:
                return
            handle.seek(size - 1)
            if handle.read(1) == b"\n":
                return
            position = size
            keep = 0
            while position > 0 and keep == 0:
                start = max(0, position - 65536)
                handle.seek(start)
                found = handle.read(position - start).rfind(b"\n")
                if found >= 0:
                    keep = start + found + 1
                position = start
            handle.truncate(keep)
            handle.flush()
            os.fsync(handle.fileno())
            _log.warning("dropped an unfinished record at the end of %s", path)
    except FileNotFoundError:
        return


# The log


class SessionLog:
    """Reads and appends one session's records."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self._synced_fingerprint: Optional[tuple] = None
        self._folded: Optional[tuple[tuple, FoldedSession]] = None
        self._fold_progress = _FoldProgress()
        self._fold_lock = threading.Lock()
        self._initialized = False

    # Layout

    @property
    def main_path(self) -> Path:
        return self.path / MAIN_LOG

    @property
    def agent_directory(self) -> Path:
        return self.path / AGENT_LOG_DIRECTORY

    @property
    def workdir_path(self) -> Path:
        """Per-session scratch workspace for agents with no project directory."""
        return self.path / "workdir"

    def _agent_files(self) -> list[Path]:
        try:
            names = os.listdir(filesystem_path(self.agent_directory))
        except OSError:
            return []
        return [self.agent_directory / name for name in sorted(names)
                if name.endswith(".jsonl")]

    def _writer_path(self) -> Path:
        if is_main_writer():
            return self.main_path
        return self.agent_directory / _this_process_agent_log()

    def exists(self) -> bool:
        return self.main_path.exists() or bool(self._agent_files())

    def _ensure_init(self, target: Optional[Path] = None) -> None:
        """Create the session directory and this process's log file."""
        target = self._writer_path() if target is None else target
        target.parent.mkdir(parents=True, exist_ok=True)
        (self.path / "context").mkdir(exist_ok=True)
        self.workdir_path.mkdir(exist_ok=True)
        os.close(os.open(filesystem_path(target), _APPEND_FLAGS, 0o600))

    # Freshness. Files only grow, so total size changes exactly when
    # anything was appended.

    def stat_fingerprint(self) -> tuple:
        try:
            main_size = os.stat(filesystem_path(self.main_path)).st_size
        except OSError:
            main_size = -1
        agent_count = agent_size = 0
        try:
            with os.scandir(filesystem_path(self.agent_directory)) as entries:
                for entry in entries:
                    if entry.name.endswith(".jsonl"):
                        agent_count += 1
                        agent_size += entry.stat().st_size
        except OSError:
            pass
        return (main_size, agent_count, agent_size)

    def mark_synced(self, fingerprint: Optional[tuple] = None) -> None:
        self._synced_fingerprint = (
            self.stat_fingerprint() if fingerprint is None else fingerprint
        )
        self._folded = None

    def stale(self) -> bool:
        """True when records appeared that this process has not loaded."""
        return self._synced_fingerprint != self.stat_fingerprint()

    def _mark_own_write(self, was_synced: bool) -> None:
        """Absorb our own append into the synced stamp, never a foreign one."""
        if was_synced:
            self.mark_synced()

    # Appending

    def _append(self, record_type: str, data: Any, *, durable: bool) -> None:
        # One choice per append: the writer role can change while it runs.
        target = self._writer_path()
        self._ensure_parent(target)
        key = str(target)
        with _append_locks[hash(key) % len(_append_locks)]:
            if key not in _prepared_files:
                _discard_torn_tail(target)
                if len(_prepared_files) > 8192:
                    _prepared_files.clear()
                _prepared_files.add(key)
            line = encode_record(_next_timestamp(), record_type, data)
            descriptor = os.open(filesystem_path(target), _APPEND_FLAGS, 0o600)
            try:
                written = 0
                while written < len(line):
                    written += os.write(descriptor, line[written:])
                if durable:
                    os.fsync(descriptor)
            except BaseException:
                # The next append must look at the tail again.
                _prepared_files.discard(key)
                raise
            finally:
                os.close(descriptor)
        self._notify_observer(record_type, data, durable)

    def _notify_observer(self, record_type: str, data: Any, durable: bool) -> None:
        """Only enqueues, on the writer's thread. A forked child never reaches it."""
        observer = _record_observer
        if observer is None or record_type not in _OBSERVED_RECORDS or os.getpid() != _record_observer_pid:
            return
        if record_type == "node.patch" and not durable:
            return  # the quiet path: a reply's streaming text
        node_ids, keys = _observed_change(record_type, data)
        observer(self.path.name, record_type, node_ids, keys)

    def _ensure_parent(self, target: Path) -> None:
        if not self._initialized:
            self._ensure_init(target)
            self._initialized = True
        else:
            # The directory may have been moved or removed since.
            target.parent.mkdir(parents=True, exist_ok=True)

    def write_history(self, seq: int, role: str, node_id: str, payload: dict) -> None:
        """Record a node's full content, new or replacing an earlier version."""
        was_synced = not self.stale()
        self._append("node.put", {"payload": payload}, durable=True)
        self._mark_own_write(was_synced)

    def patch_node(
        self, node_id: str, fields: dict, metadata: Optional[dict] = None, *, quiet: bool = False,
    ) -> None:
        """Record changed top-level fields and merged metadata of one node.

        ``quiet`` is for a reply's streaming text: no fsync, so a process
        crash loses nothing written and a power loss can lose only the tail.
        """
        data: dict[str, Any] = {"id": node_id, "set": fields}
        if metadata:
            data["metadata"] = metadata
        was_synced = not self.stale()
        self._append("node.patch", data, durable=not quiet)
        self._mark_own_write(was_synced)

    def delete_nodes(self, node_ids: list[str]) -> None:
        was_synced = not self.stale()
        self._append("node.delete", {"ids": list(node_ids)}, durable=True)
        self._mark_own_write(was_synced)

    def write_meta(self, meta: dict) -> None:
        """Record what changed between the stored meta and ``meta``."""
        new = json.loads(json.dumps(meta, ensure_ascii=False, default=str))
        old = self.read_meta()
        changed = {key: value for key, value in new.items()
                   if key not in old or old[key] != value}
        removed = [key for key in old if key not in new]
        if not changed and not removed:
            return
        data: dict[str, Any] = {"set": changed}
        if removed:
            data["unset"] = removed
        was_synced = not self.stale()
        self._append("meta.patch", data, durable="head_id" in changed)
        self._mark_own_write(was_synced)
        self._remember_meta(self.stat_fingerprint(), new)

    # Reading

    def append_turn_record(self, record_type: str, data: dict) -> None:
        """Append a turn's progress line; folding sessions skips these."""
        was_synced = not self.stale()
        self._append(record_type, data, durable=False)
        self._mark_own_write(was_synced)

    def append_state_file(self, name: str, content: str | None) -> None:
        """Replace one small state document; ``None`` removes it."""
        was_synced = not self.stale()
        self._append("file.put", {"name": name, "content": content}, durable=False)
        self._mark_own_write(was_synced)

    def read_turn_records(self, execution_id: str | None,
                          record_type: str | None = None) -> list[dict]:
        """The turn progress lines of one execution (``None``: of every
        execution), in written order; ``record_type`` keeps one kind."""
        records: list[dict] = []
        containing = f'"type":"{record_type}"'.encode() if record_type else None
        for path in (self.main_path, *self._agent_files()):
            if not path.exists():
                continue
            for record in read_log_file(path, containing=containing):
                kind = str(record.get("type", ""))
                if (kind.startswith(TURN_RECORD_PREFIX)
                        and (record_type is None or kind == record_type)
                        and (execution_id is None
                             or (record.get("data") or {}).get("execution_id") == execution_id)):
                    records.append(record)
        records.sort(key=lambda record: record["ts"])
        return records

    def read_run_rows(self) -> list[list[dict]]:
        """The run-state rows of every committed change, in written order."""
        records: list[dict] = []
        for path in (self.main_path, *self._agent_files()):
            records.extend(record for record in read_log_file(path, containing=RUN_ROWS_MARKER)
                           if record.get("type") == RUN_ROWS_RECORD)
        records.sort(key=lambda record: record["ts"])
        return [(record.get("data") or {}).get("rows") or [] for record in records]

    def _fold(self) -> tuple[tuple, FoldedSession]:
        with self._fold_lock:
            fingerprint = self.stat_fingerprint()
            if self._folded is None or self._folded[0] != fingerprint:
                self._folded = (fingerprint, self._catch_up())
            return self._folded

    def _catch_up(self) -> FoldedSession:
        """Apply what was appended since the last fold; start over only when
        a file was replaced or a new line sorts before one already applied."""
        progress = self._fold_progress
        records = self._read_new(progress)
        if records is None or (records and records[0].get("ts", 0) <= progress.newest):
            progress = self._fold_progress = _FoldProgress()
            records = self._read_new(progress) or []
        if not records:
            return progress.folded
        base = progress.folded
        folded = FoldedSession(dict(base.nodes), dict(base.meta), dict(base.files))
        for record in records:
            apply_record(folded, record)
        progress.folded = folded
        progress.newest = records[-1].get("ts", 0)
        return folded

    def _read_new(self, progress: _FoldProgress) -> Optional[list[dict]]:
        """New records in time order, or None when a known file was replaced."""
        records: list[dict] = []
        seen = 0
        for path in (self.main_path, *self._agent_files()):
            try:
                info = os.stat(filesystem_path(path))
            except OSError:
                continue
            position = progress.positions.get(str(path))
            if position is None:
                position = progress.positions[str(path)] = _LogPosition(inode=info.st_ino)
            elif position.inode != info.st_ino or info.st_size < position.offset:
                return None
            seen += 1
            if position.damaged or info.st_size == position.offset:
                continue
            found, position.offset, position.damaged = read_appended(path, position.offset)
            records.extend(found)
        if seen < len(progress.positions):
            return None
        records.sort(key=lambda record: record.get("ts", 0))
        return records

    def _remember_meta(self, fingerprint: tuple, meta: dict) -> None:
        with _meta_cache_lock:
            _meta_cache[str(self.path)] = (fingerprint, meta)
            _meta_cache.move_to_end(str(self.path))
            while len(_meta_cache) > _META_CACHE_CAPACITY:
                _meta_cache.popitem(last=False)

    def read_meta(self) -> dict:
        fingerprint = self.stat_fingerprint()
        with _meta_cache_lock:
            cached = _meta_cache.get(str(self.path))
        if cached is not None and cached[0] == fingerprint:
            return copy.deepcopy(cached[1])
        fingerprint, folded = self._fold()
        self._remember_meta(fingerprint, copy.deepcopy(folded.meta))
        return copy.deepcopy(folded.meta)

    def list_history(self) -> list[dict]:
        """Current node payloads in seq order."""
        _fingerprint, folded = self._fold()
        return sorted(folded.nodes.values(), key=node_sort_key)

    def read_context_file(self, name: str) -> Optional[Any]:
        target = self.path / "context" / name
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # Cleanup

    def destroy(self) -> None:
        """Delete the session directory."""
        with _meta_cache_lock:
            _meta_cache.pop(str(self.path), None)
        if self.path.exists():
            remove_tree(self.path, ignore_errors=True)
        self._folded = None
        self._fold_progress = _FoldProgress()
        self._initialized = False
        from .session_state_file import forget_directory
        forget_directory(self.path)
