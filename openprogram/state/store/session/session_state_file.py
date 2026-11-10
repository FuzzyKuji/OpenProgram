"""Small named pieces of a session's state, stored as lines of its log.

Jobs, notices, the inbox, todos, open work and always-on state each read and
replace a whole small document. Every replacement is one ``file.put`` line in
the session's log, so their full history stays with the session. Reading folds
those lines and only looks at what was appended since the last read.
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

from openprogram.host._platform.filesystem import filesystem_path

from .session_log import AGENT_LOG_DIRECTORY, MAIN_LOG, read_appended

if TYPE_CHECKING:
    from .session_store.service import SessionStore

_MARKER = b'"file.put"'
_CACHED_DIRECTORIES = 512


class _Folded:
    def __init__(self) -> None:
        self.offsets: dict[str, int] = {}
        self.damaged: set[str] = set()
        self.files: dict[str, str] = {}
        self.lock = threading.Lock()


_folded: "OrderedDict[str, _Folded]" = OrderedDict()
_folded_lock = threading.Lock()


def _folded_for(directory: Path) -> _Folded:
    key = str(directory)
    with _folded_lock:
        state = _folded.get(key)
        if state is None:
            state = _Folded()
            _folded[key] = state
            while len(_folded) > _CACHED_DIRECTORIES:
                _folded.popitem(last=False)
        _folded.move_to_end(key)
        return state


def forget_directory(directory: Path) -> None:
    """A session's directory was deleted or rewritten."""
    with _folded_lock:
        _folded.pop(str(directory), None)


def _log_files(directory: Path) -> list[Path]:
    agents = directory / AGENT_LOG_DIRECTORY
    try:
        names = sorted(os.listdir(filesystem_path(agents)))
    except OSError:
        names = []
    return [directory / MAIN_LOG, *(agents / name for name in names if name.endswith(".jsonl"))]


def _new_records(path: Path, state: _Folded) -> list[dict]:
    key = str(path)
    start = state.offsets.get(key, 0)
    try:
        if key in state.damaged or os.stat(filesystem_path(path)).st_size == start:
            return []
    except OSError:
        return []
    records, state.offsets[key], damaged = read_appended(path, start, containing=_MARKER)
    if damaged:
        state.damaged.add(key)
    return [record for record in records if record.get("type") == "file.put"]


def read_files(directory: Path) -> dict[str, str]:
    """Every state file of the session in ``directory``, current content."""
    state = _folded_for(directory)
    with state.lock:
        records: list[dict] = []
        for path in _log_files(directory):
            records.extend(_new_records(path, state))
        records.sort(key=lambda record: record.get("ts", 0))
        for record in records:
            data = record.get("data") or {}
            name = data.get("name")
            if not name:
                continue
            if data.get("content") is None:
                state.files.pop(name, None)
            else:
                state.files[name] = data["content"]
        return dict(state.files)


class SessionStateFile:
    """One named document; reads and writes like a text file."""

    def __init__(self, store: "SessionStore", directory: Path, name: str):
        self._store = store
        self.directory = directory
        self.name = name

    def exists(self) -> bool:
        return self.name in read_files(self.directory)

    def read_text(self, encoding: str = "utf-8") -> str:
        del encoding
        content = read_files(self.directory).get(self.name)
        if content is None:
            raise FileNotFoundError(f"{self.directory}: {self.name}")
        return content

    def write_text(self, content: str, encoding: str = "utf-8") -> None:
        del encoding
        self._store.write_state_line(self.directory, self.name, content)

    def with_suffix(self, suffix: str) -> Path:
        """A real file beside the log, used as this document's lock."""
        return self.directory / (Path(self.name).stem + suffix)
