"""The never-writable paths, resolved without importing anything heavy.

The sandbox used to reach into ``openprogram.programs`` for these, which
dragged the whole tool registry into every policy construction — one
unrelated tool failing to import took the sandbox down with it. Both paths
only depend on where the ``openprogram`` package sits and on ``paths``, so
they live here and both sides import this instead.
"""
from __future__ import annotations

import os

PROGRAM_SOURCES_FILE = "program-sources.json"


def applications_root() -> str:
    """Absolute path to ``openprogram/programs/applications``.

    Computed from the top-level package so it works for editable and
    site-packages installs, and without importing the agentics package
    (which would recurse during its own load).
    """
    import openprogram
    return os.path.join(
        os.path.dirname(os.path.abspath(openprogram.__file__)),
        "programs", "applications",
    )


def program_sources_path() -> str:
    from openprogram.state import paths
    return str(paths.get_state_dir() / PROGRAM_SOURCES_FILE)


def installed_program_roots() -> list[str]:
    """The owner-recorded harness directories in ``program-sources.json``.

    The host imports their code at startup, outside any sandbox, so they
    are as protected as the built-in applications. Read straight from the
    record file: importing the programs package here would load every
    Program.
    """
    import json
    try:
        with open(program_sources_path(), encoding="utf-8") as stream:
            rows = json.load(stream).get("programs", [])
    except (OSError, ValueError, AttributeError):
        return []
    roots = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("scope") is not None or row.get("kind") == "application":
            continue
        path = os.path.expanduser(str(row.get("path", "")).strip())
        if os.path.isabs(path):
            roots.append(os.path.abspath(path))
    return list(dict.fromkeys(roots))


def application_catalog_path() -> str:
    from openprogram.state.program_directory import catalog_path
    return str(catalog_path())
