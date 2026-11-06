"""``MEMORY.md``: the entry point of a memory workspace.

It is the one file every session sees. Two parts:

- **The map** — what each part of the workspace holds, which subjects
  ``topics/`` covers, what has been active lately. The memory agents keep
  it; the Runtime only writes a first version for a workspace that has
  none, generated from the tree as it stands.
- **The core** — the facts and rules every session needs without asking:
  who the owner is, standing preferences. It is rendered from
  ``topics/core.md`` (the editable, evidence-carrying master) between
  ``CORE_START`` and ``CORE_END``, only from blocks whose evidence is
  trusted and within ``core_max_tokens``. The render replaces that section
  each time; anything outside it is the agents' own.

The prompt shows the map cut to ``GUIDE_MAX_BYTES``, then the core.
"""
from __future__ import annotations

import re
from pathlib import Path

GUIDE_FILE = "MEMORY.md"
#: What reaches the prompt; the file itself may be longer.
GUIDE_MAX_BYTES = 6_000
#: Directory depth the generated map lists below ``topics/``.
_MAP_DEPTH = 3
_RECENT = 6

_LAYOUT = """\
## Layout

- The core section at the end of this file — what every session needs, rendered from `topics/core.md`. Edit `topics/core.md`; the section is replaced on every write.
- `topics/` — the organised memory: one file per person, project or recurring theme. A subject with parts of its own is a directory with `overview.md` and one file per part. Paragraphs end in a `^block-id` and cite footnotes that link the chat message they came from, `/s/<session>#<message>`. Pass that link to `memory_get` to read what was actually said.
- `timeline/` — the same facts by date: a file per year, with month and day files below it, for "what happened when".
- `relations.json`, `recent_events.jsonl` — links between paragraphs and the latest changes.

Search with `memory_search` first; read the Topic file a hit points to for the surrounding facts."""


CORE_START = "<!-- core: rendered from topics/core.md, edit that file instead -->"
CORE_END = "<!-- /core -->"
_CORE_SECTION = re.compile(
    re.escape(CORE_START) + r"[\s\S]*?" + re.escape(CORE_END) + r"\n?")


def split(text: str) -> tuple[str, str]:
    """``(map, core)``: the agents' part of the file and the rendered core."""
    found = _CORE_SECTION.search(text or "")
    if not found:
        return (text or "").strip(), ""
    core = found.group(0)[len(CORE_START):].rsplit(CORE_END, 1)[0].strip()
    rest = (text[:found.start()] + text[found.end():]).strip()
    return rest, core


def write_core(memory_dir: Path, core: str) -> None:
    """Put the rendered core into ``MEMORY.md``, keeping the map as it is.

    A workspace without a map gets the generated one first. An empty
    ``core`` removes the section."""
    path = Path(memory_dir) / GUIDE_FILE
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = generate(memory_dir)
    map_text, _old = split(current)
    parts = [map_text]
    if core.strip():
        parts.append(f"{CORE_START}\n{core.strip()}\n{CORE_END}")
    path.write_text("\n\n".join(p for p in parts if p).rstrip() + "\n", encoding="utf-8")


def _summary(path: Path) -> str:
    """The first sentence of a Topic file's first paragraph, without markup."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "[^", ">", "|", "-", "*")):
            continue
        line = re.sub(r"\[\^[^\]]+\]", "", line)
        line = re.sub(r"\s\^[A-Za-z0-9-]+\s*$", "", line)
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
        line = re.split(r"(?<=[。！？；])|(?<=[.!?;])(?=\s)", line, maxsplit=1)[0].strip()
        return line if len(line) <= 60 else line[:59] + "…"
    return ""


def _map_lines(directory: Path, root: Path, depth: int) -> list[str]:
    lines: list[str] = []
    indent = "  " * depth
    entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
    for entry in entries:
        relative = entry.relative_to(root).as_posix()
        if entry.is_dir():
            overview = entry / "overview.md"
            note = _summary(overview) if overview.is_file() else ""
            lines.append(f"{indent}- `{relative}/`" + (f" — {note}" if note else ""))
            if depth + 1 < _MAP_DEPTH:
                lines.extend(_map_lines(entry, root, depth + 1))
        elif (entry.suffix == ".md" and entry.name != "overview.md"
              and entry != root / "topics" / "core.md"):
            note = _summary(entry)
            lines.append(f"{indent}- `{relative}`" + (f" — {note}" if note else ""))
    return lines


def _recent_lines(memory_dir: Path) -> list[str]:
    import json

    from ..markdown import parse_topic_tree

    events = memory_dir / "recent_events.jsonl"
    if not events.is_file():
        return []
    try:
        paths = {u.memory_id: u.topic_path for u in parse_topic_tree(memory_dir / "topics")}
    except Exception:
        return []
    seen: list[str] = []
    for raw in reversed(events.read_text(encoding="utf-8").splitlines()):
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        topic = paths.get(event.get("memory_id", ""))
        if topic and topic != "core.md" and topic not in seen:
            seen.append(topic)
        if len(seen) >= _RECENT:
            break
    return [f"- `topics/{path}`" for path in seen]


def generate(memory_dir: Path) -> str:
    """A first ``MEMORY.md`` for the workspace as it stands."""
    memory_dir = Path(memory_dir)
    topics = memory_dir / "topics"
    parts = [
        "# Memory map",
        "What this memory holds and where to find it. Memory agents keep this "
        "file current; rewrite it whenever the structure or the current focus changes.",
        _LAYOUT,
    ]
    if topics.is_dir():
        subjects = _map_lines(topics, memory_dir, 0)
        if subjects:
            parts.append("## Subjects\n\n" + "\n".join(subjects))
    recent = _recent_lines(memory_dir)
    if recent:
        parts.append("## Recently active\n\n" + "\n".join(recent))
    return "\n\n".join(parts) + "\n"


def ensure(memory_dir: Path) -> bool:
    """Write the generated map when the workspace has none. True if written."""
    path = Path(memory_dir) / GUIDE_FILE
    if path.exists():
        return False
    path.write_text(generate(memory_dir), encoding="utf-8")
    return True


def prompt_text(memory_dir: Path) -> str:
    """``MEMORY.md`` as the prompt shows it: the map cut to
    ``GUIDE_MAX_BYTES``, then the core in full (the render already holds
    it to its own budget)."""
    try:
        text = (Path(memory_dir) / GUIDE_FILE).read_text(encoding="utf-8")
    except OSError:
        text = ""
    map_text, core = split(text)
    data = map_text.encode("utf-8")
    shown = data[:GUIDE_MAX_BYTES].decode("utf-8", errors="ignore").strip()
    if len(data) > GUIDE_MAX_BYTES:
        shown += "\n… (MEMORY.md continues; read it for the rest)"
    if not core:
        core = _legacy_core(Path(memory_dir))
    return "\n\n".join(part for part in (shown, core) if part)


def _legacy_core(memory_dir: Path) -> str:
    """A root ``core.md`` from before the core moved into this file; the
    next write renders it here and removes it."""
    try:
        text = (memory_dir / "core.md").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    body = [line for line in text.splitlines() if not line.startswith("# ")]
    return text if "\n".join(body).strip() else ""
