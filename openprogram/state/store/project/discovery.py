"""Bounded cross-platform project lookup on startup and explicit access."""
from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from pathlib import Path

from . import identity, project_store as projects
from .location import reconcile_registered_projects, refresh_project_location

_log = logging.getLogger(__name__)
_SKIP = {"node_modules", "vendor", "venv", "build", "dist", "target", "__pycache__"}


def find_project_folder(project, *, roots=None, max_directories: int = 4000) -> Path | None:
    """Return one marker match in a completed bounded search, or no match.

    Limits count all directory entries, including files, to bound large flat
    directories. Symbolic links and hidden directories are never traversed.
    """
    if not identity.is_portable(project) or max_directories < 1:
        return None
    if roots is None:
        roots = [Path(p.path).expanduser().parent for p in projects.list_projects()
                 if not p.is_default and p.path]
    home = Path.home().resolve()
    selected = set()
    for item in roots:
        root = Path(item).expanduser()
        if root.is_symlink():
            continue
        root = root.resolve()
        # A moved parent no longer exists at its recorded path. Use its
        # nearest surviving ancestor, without expanding into a home scan.
        while not root.is_dir() and root.parent != root:
            root = root.parent
        if root == home or root in home.parents:
            continue
        if root.is_dir():
            selected.add(root)
    queue = deque((root, 0) for root in sorted(selected))
    visited = set()
    matches = set()
    entries = 0
    while queue:
        folder, depth = queue.popleft()
        if folder in visited:
            continue
        visited.add(folder)
        if identity.read_marker(folder) == project.directory_identity:
            matches.add(folder)
            if len(matches) > 1:
                return None
        if depth >= 3:
            continue
        try:
            with os.scandir(folder) as children:
                for child in children:
                    entries += 1
                    if entries > max_directories:
                        return None
                    if child.name.startswith(".") or child.name in _SKIP:
                        continue
                    if child.is_dir(follow_symlinks=False):
                        queue.append((Path(child.path), depth + 1))
        except OSError:
            return None
    return next(iter(matches)) if len(matches) == 1 else None


def discover_moved_projects(roots=None, *, max_directories=4000) -> list[str]:
    moved = []
    for project in projects.list_projects():
        if project.is_default or not project.path:
            continue
        before = project.path
        state = refresh_project_location(project.id, roots=roots, max_directories=max_directories)
        current = projects.get_project(project.id)
        if current and current.path != before and state == "available":
            moved.append(project.id)
    return moved


async def run_discovery(stop: asyncio.Event, notify) -> None:
    """Startup reconciliation; later access checks run at their public entry."""
    try:
        moved = await asyncio.to_thread(reconcile_registered_projects)
        if moved:
            notify()
    except Exception:
        _log.exception("Project location reconciliation failed")
    await stop.wait()
