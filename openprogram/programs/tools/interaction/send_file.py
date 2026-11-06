"""send_file — hand a file the agent has to the person it is talking to.

The tool does NOT deliver. It validates the path and reports success;
when the turn ends, the turn runtime reads the turn's recorded
``send_file`` calls (:func:`with_attachments`), turns each into an
attachment marker on the end of the assistant message text, and each
surface delivers it its own way (web chat renders a file card that opens
the file; a chat channel uploads the bytes with the platform's own file
API). Because the record is the source, a turn that paused and resumed
keeps what it attached before the pause. The tool therefore
knows nothing about channels, and a new channel needs no change here.

Why a tool rather than a bare ``MEDIA:/path`` line in the reply prose
(openclaw / hermes) or an implicit scan for absolute paths (weclaw): the
failure mode of a prose convention is that an imperfect extraction leaks
the raw line to the user as text — a bill this repo has already paid
once, on inbound channel attachments. A tool call has somewhere to put
an honest "that file isn't there" and cannot be triggered by the model
merely mentioning a path.

SECURITY. This is the direction where a model names a path and the
system reads it out to a chat platform, so the path check is the whole
boundary — note in particular that ``openprogram/host/sandbox/`` does NOT
cover it: the sandbox wraps SHELL commands, and this tool is in-process
Python, so nothing else stands between a bad path and the wire. The
allowed set is :func:`openprogram.state.attachments.sendable_roots` — the
session's own workdir plus the project the session is explicitly bound
to — and symlinks are fully resolved BEFORE containment is tested, so a
link planted inside an allowed root cannot point outside it. A rejected
path returns a spelled-out error naming the roots; it never fails
silently.
"""
from __future__ import annotations

import json

from openprogram.programs._host.runtime import ToolReturn, function


_DESCRIPTION = (
    "Send a file to the user as a real attachment — an image, a PDF, a "
    "generated chart, a log, anything on disk. Use it whenever you have "
    "produced or found a file the user should actually see, instead of "
    "only writing its path in your reply.\n"
    "\n"
    "- `path` MUST be absolute, and must live in the session working "
    "directory or the project bound to this session.\n"
    "- Web chat shows it as a file card under your reply that opens the "
    "file (images, video, audio and PDFs preview in place); on a chat "
    "platform the file is uploaded as an attachment.\n"
    "- Do not also paste the path into your reply, least of all in a code "
    "block: the user sees the card, not a path to copy.\n"
    "- Still describe the file in your reply — this tool attaches it, it "
    "does not speak for you."
)

#: Upper bound on one outbound file. Separate knob from the inbound
#: ``MAX_ATTACH_BYTES`` even though the number matches today: this one
#: is about what chat platforms accept on upload, that one is about not
#: committing giant blobs into a session's git history.
MAX_SEND_BYTES = 32 * 1024 * 1024


def outbound_files(tool_calls: list[dict] | None, session_id: str | None) -> list[dict]:
    """The files this turn's successful ``send_file`` calls attached.

    Read from the turn's recorded tool calls rather than kept in memory,
    so a turn that paused (an approval, a worker restart) and resumed
    still delivers what it attached before the pause. Each path is
    checked again here: what goes out is what is allowed now.
    """
    entries: list[dict] = []
    for call in tool_calls or []:
        if call.get("tool") != "send_file" or call.get("is_error"):
            continue
        if not str(call.get("result") or "").startswith("Attached "):
            continue
        args = call.get("input")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                continue
        path = args.get("path") if isinstance(args, dict) else None
        entry = _check(str(path or ""), session_id)
        if isinstance(entry, dict) and all(e["path"] != entry["path"] for e in entries):
            entries.append(entry)
    return entries


def markers_for(entries: list[dict]) -> str:
    """The entries as attachment markers, one per line ("" when empty)."""
    from openprogram.state.attachments import format_marker
    return "\n".join(
        format_marker(e["name"], e["path"], int(e.get("size") or 0))
        for e in entries
    )


def with_attachments(final_text: str, tool_calls: list[dict] | None,
                     session_id: str | None) -> str:
    """The reply text with this turn's attachment markers on the end."""
    from openprogram.state.attachments import find_markers
    sent = {path for _name, _meta, path in find_markers(final_text or "")}
    entries = [e for e in outbound_files(tool_calls, session_id) if e["path"] not in sent]
    if not entries:
        return final_text
    markers = markers_for(entries)
    return (final_text + "\n\n" + markers).strip() if final_text else markers


@function(
    name="send_file",
    description=_DESCRIPTION,
    toolset=["core"],
    # Surfaces with no attachment channel at all. Rather than telling the
    # model in the system prompt that it can't send files here (hermes'
    # approach), don't hand it the tool — it can't try and fail.
    # The CLI/TUI is a terminal.
    unsafe_in=["cli", "tui", "plan"],
)
def send_file(path: str) -> str | ToolReturn:
    """Attach a file to your reply so the user receives it.

    Args:
        path: Absolute path of the file to send.
    """
    out = _send_file_impl(path)
    # A refused or missing file attached nothing: the call failed.
    if out.startswith("Error:"):
        return ToolReturn(text=out, is_error=True)
    return out


def _send_file_impl(path: str) -> str:
    """Implementation body — kept apart from the @function binding so
    tests can call it directly (the binding object is not callable)."""
    from openprogram.runtime.execution.run_control import get_current_session_id

    entry = _check(path, get_current_session_id())
    if isinstance(entry, str):
        return entry
    return (f"Attached {entry['name']} ({entry['size']} bytes). It goes out "
            f"with your reply as a file card the user opens (an upload on a "
            f"chat platform) — describe it in your message and do not paste "
            f"its path.")


def _check(path: str, session_id: str | None) -> dict | str:
    """``{path, name, size}`` for a file this session may send, else an
    ``Error:`` sentence that says why not."""
    from openprogram.state import attachments as _att

    raw = (path or "").strip()
    if not raw:
        return "Error: path is required."
    roots = _att.sendable_roots(session_id)
    if not roots:
        return ("Error: no allowed directory is configured for outgoing "
                "files (no session workdir and no bound project), so "
                "send_file cannot deliver anything right now.")
    target = _att.resolve_session_attachment(
        raw, session_id, roots, allow_missing=True,
    )
    if target is None:
        listed = ", ".join(str(r) for r in roots)
        return (f"Error: {raw!r} is outside the directories this session "
                f"may send files from. Allowed (symlinks resolved): "
                f"{listed}. Copy the file into the working directory "
                f"first, then send that copy.")
    if not target.is_file():
        return f"Error: no such file: {target}"
    try:
        size = target.stat().st_size
    except OSError as e:
        return f"Error: cannot stat {target}: {type(e).__name__}: {e}"
    if size > MAX_SEND_BYTES:
        return (f"Error: {target.name} is {size / 1024 / 1024:.1f} MB, over "
                f"the {MAX_SEND_BYTES // 1024 // 1024} MB limit for an "
                f"outgoing file.")
    return {"path": str(target), "name": target.name, "size": size}


# ponytail: no caption parameter. The reply text is delivered next to
# the file on every surface, so a per-file caption would only duplicate
# it; add one when a platform needs the text welded to the upload.

__all__ = ["send_file", "_send_file_impl", "outbound_files", "markers_for",
           "with_attachments", "MAX_SEND_BYTES"]
