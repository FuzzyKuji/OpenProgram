"""The runtime packages depend on each other in one direction.

``openprogram.runtime`` is split by concept:

* ``agent`` — one model call: the ``Agent`` class, ``agent()``, and the
  tool loop (the code of Agentic Programming).
* ``context`` — the ``Context`` class and what the model sees.
* ``permissions`` — what a tool call may do, and who decides.
* ``execution`` — the pause, cancel and recovery control plane.
* ``events`` — the event bus.
* ``conversation`` — chat sessions and turns, built on the Agent.
* ``jobs`` — background runs.
* ``agent_registry`` — saved Agent configurations.
* ``scheduler``, ``proactive``, ``commands`` — features built on the above.

The lower packages must not reach up into the features built on them,
``execution`` does not depend on the model-call core, and ``context``,
``permissions`` and ``events`` do not either. ``execution`` does not know
about Programs either: the engines built on it register hooks for the
tools they run (a chat Goal's settlement, for one). The package now named
``openprogram.runtime.agent`` once mixed all of these; no module imports
one of its former submodules that moved elsewhere, nor the call core's
former name ``openprogram.runtime.agentic_programming``.

The scan reads every module under ``openprogram/`` as source, so it also sees
imports inside functions and string imports through
``importlib.import_module`` and ``__import__``. Imports that break a rule
today are listed in ``ALLOWED``; the test fails on a new one and on an entry
that no longer occurs, so the list only shrinks.
"""
from __future__ import annotations

import ast
from pathlib import Path

from openprogram.runtime.execution._schema import _RUNTIME_ENTRYPOINT_PREFIXES

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "openprogram"
RUNTIME = "openprogram.runtime"

# Old module paths, from the execution store's rename table.
REMOVED = tuple(
    old for old, _ in _RUNTIME_ENTRYPOINT_PREFIXES if old.startswith(RUNTIME + ".")
)

FEATURES = tuple(
    f"{RUNTIME}.{name}"
    for name in ("conversation", "jobs", "agent_registry", "scheduler", "proactive", "commands")
)
CALL_CORE = (f"{RUNTIME}.agent",)
PROGRAMS = ("openprogram.programs",)

# (importing package, packages it must not import)
RULES = (
    (f"{RUNTIME}.agent", FEATURES),
    (f"{RUNTIME}.context", FEATURES + CALL_CORE),
    (f"{RUNTIME}.permissions", FEATURES + CALL_CORE),
    (f"{RUNTIME}.execution", FEATURES + CALL_CORE),
    # execution imports programs
    (f"{RUNTIME}.execution", PROGRAMS),
    (f"{RUNTIME}.events", FEATURES + CALL_CORE),
)

# (file, imported module) pairs that break a rule today. Remove an entry
# when its import goes away; never add one.
ALLOWED: frozenset[tuple[str, str]] = frozenset({
})


def _within(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


def _module_name(path: Path) -> str:
    parts = path.relative_to(ROOT).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imported_modules(path: Path) -> set[str]:
    """Every module ``path`` imports, resolved to absolute names."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                source = ".".join(base + ([node.module] if node.module else []))
            else:
                source = node.module or ""
            found.add(source)
            # ``from openprogram.runtime import conversation`` imports a package.
            found.update(f"{source}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            callee = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute) else ""
            )
            first = node.args[0]
            if callee in {"import_module", "__import__"} and isinstance(first, ast.Constant):
                if isinstance(first.value, str):
                    found.add(first.value)
    return found


def _existing(names: set[str], modules: set[str]) -> set[str]:
    """Keep the names that are modules (drop ``package.attribute`` guesses)."""
    return {name for name in names if name in modules}


def _scan() -> tuple[dict[tuple[str, str], str], list[str]]:
    paths = [p for p in sorted(PACKAGE.rglob("*.py")) if "__pycache__" not in p.parts]
    modules = {_module_name(p) for p in paths}
    violations: dict[tuple[str, str], str] = {}
    removed: list[str] = []
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        importer = _module_name(path)
        raw = _imported_modules(path)
        removed += [f"{relative}: {name}" for name in sorted(raw) if _within(name, REMOVED)]
        imported = _existing(raw, modules)
        for package, forbidden in RULES:
            if not _within(importer, (package,)):
                continue
            for name in sorted(imported):
                if _within(name, forbidden):
                    violations[(relative, name)] = package
    return violations, removed


def test_no_module_imports_a_removed_runtime_package():
    _, removed = _scan()
    assert removed == []


def test_runtime_packages_import_in_one_direction():
    violations, _ = _scan()
    new = sorted(pair for pair in violations if pair not in ALLOWED)
    stale = sorted(pair for pair in ALLOWED if pair not in violations)
    assert new == [], "new layering violations (fix the import; do not allow it):\n" + "\n".join(
        f"  {file}: {name}  [{violations[(file, name)]}]" for file, name in new
    )
    assert stale == [], "these allowed imports are gone; delete them from ALLOWED:\n" + "\n".join(
        f"  {pair!r}," for pair in stale
    )
