"""Target ``app``: application windows, through ``openprogram/programs/tools/computer_use/computer_use_agent/desktop``.

The model reads an app with ``get_app_state`` (screenshot plus an indexed
Accessibility tree), acts by element index, screenshot pixel or a
description, and gets the changed part of the tree back after every action.
Everything happens in the background: the user's frontmost app, key window
and cursor are not touched. Approval is per application.
"""
from __future__ import annotations

from pathlib import Path
import platform
from typing import Any

from openprogram.programs._host.execution import ToolReturn

NAME = "app"

# Actions that change the app and are followed by its new state.
ACTING_ACTIONS = (
    "click", "type_text", "press_key", "set_value", "scroll", "drag", "perform_secondary_action",
    "select_text", "paste", "focus", "copy", "menu", "show_window", "hover", "wait", "open_file",
)
AUDIO_ACTIONS = ("start_audio_recording", "stop_audio_recording")
READING_ACTIONS = ("list_apps", "list_windows", "get_app_state", "zoom", "find")
ACTIONS = (*READING_ACTIONS, *ACTING_ACTIONS, *AUDIO_ACTIONS)
READ_ONLY_ACTIONS = frozenset({"list_apps"})

_GUIDE = (Path(__file__).parent.parent / "guides" / "app.md").read_text(encoding="utf-8")

# macOS Spaces, Open With and the out-of-process file dialog have no counterpart on the other platforms.
_SPACES_LINE = ("- A window on another Space takes clicks and element actions but not keys: there type_text and paste "
                "insert text into the focused field, and press_key fails.\n")
_OPEN_FILE_LINE = (
    "- open_file(app, path): open a document (absolute path) in that app the way Open With does, without raising it; "
    "the next state is of its window. Use it instead of File > Open or cmd+O: the system Open and Save dialogs take "
    "clicks and set_value but not keys. When a state says a file dialog is open, call open_file: it cancels the "
    "dialog first.\n")

# What differs on Linux: GTK and Qt take pointer and key input only while
# focused, and there is no system clipboard format conversion to borrow.
_LINUX_GUIDE = (
    ("Read and operate macOS application windows in the background: the user keeps the keyboard, mouse and front app, "
     "and nothing is raised or activated.",
     "Read and operate Linux (X11) application windows. Element actions run in the background through AT-SPI; a click "
     "or drag at x,y, a scroll at x,y and press_key bring the window forward for that moment and then give focus and "
     "the pointer back, so prefer element_index."),
    ("When an app exposes little to Accessibility", "When an app exposes little to accessibility (or nothing, "
     "e.g. without AT-SPI)"),
    ('super/cmd is Command. Keys go to that app only, so system-wide shortcuts (Spotlight, Mission Control) cannot be '
     'pressed.', 'super/cmd is the Super key. Return on a focused field runs in the background; other keys bring the '
     'window forward for the moment of the key.'),
    ("rest the pointer there (the real cursor does not move) to open tooltips and hover menus; apps that ignore the "
     "pointer while in the background show nothing.", "move the real pointer there and rest, to open tooltips and "
     "hover menus; the pointer stays there."),
    ("un-minimize a window or unhide the app, still in the background.", "un-minimize a window."),
    ("through the clipboard, which is restored afterwards; md for formatted text in rich editors.",
     "inserted straight into the focused field without the clipboard; plain text only (format=text)."),
    ("the app's own Copy on the current selection; returns the copied text and restores the clipboard.",
     "returns the selected text of the element (or the focused one); the clipboard is not touched."),
    ("Refused: password fields, the Keychain and Passwords apps, system login prompts, and OpenProgram itself.",
     "Refused: password fields, password stores (Seahorse, KWallet), authentication prompts (polkit, gcr), and "
     "OpenProgram itself."),
    (_SPACES_LINE, ""),
    (_OPEN_FILE_LINE, ""),
)
# What differs on Windows: shortcuts read the real keyboard state, and some
# windows (UWP frames, Chromium) take raw input instead of window messages.
_WINDOWS_GUIDE = (
    ("Read and operate macOS application windows in the background: the user keeps the keyboard, mouse and front app, "
     "and nothing is raised or activated.",
     "Read and operate Windows application windows. Element actions run in the background through UI Automation, and "
     "clicks, scrolls and plain keys at a window are posted to it without raising it. A key with modifiers (ctrl+s), "
     "and pointer input to windows that take only real input (Store apps, Chromium), bring the window forward for "
     "that moment and then give focus and the cursor back, so prefer element_index."),
    ("When an app exposes little to Accessibility", "When an app exposes little to UI Automation"),
    ("super/cmd is Command. Keys go to that app only, so system-wide shortcuts (Spotlight, Mission Control) cannot be "
     "pressed.", "super/cmd is the Windows key; ctrl is Control. Use the Windows shortcuts (ctrl+c, not super+c)."),
    ("one of the element's listed actions (AXShowMenu, AXIncrement …).",
     "one of the element's listed actions (expand, collapse, select, or its default action)."),
    ("un-minimize a window or unhide the app, still in the background.",
     "un-minimize a window without activating it."),
    ("through the clipboard, which is restored afterwards; md for formatted text in rich editors.",
     "through the clipboard, whose text is restored afterwards; md for formatted text in rich editors."),
    ("the app's own Copy on the current selection; returns the copied text and restores the clipboard.",
     "returns the selected text of the element (or the focused one); the clipboard is not touched."),
    ("list_windows(app): window ids, titles, minimized / hidden / other-Space state.",
     "list_windows(app): window ids, titles, focused and minimized state."),
    ("Refused: password fields, the Keychain and Passwords apps, system login prompts, and OpenProgram itself.",
     "Refused: password fields, credential and elevation prompts (Credential UI, UAC), the lock screen, and "
     "OpenProgram itself."),
    (_SPACES_LINE, ""),
    (_OPEN_FILE_LINE, ""),
)


def guide(system: str | None = None) -> str:
    """The app guide for this host's platform."""
    text = _GUIDE
    pairs = {"Linux": _LINUX_GUIDE, "Windows": _WINDOWS_GUIDE}.get(system or platform.system(), ())
    for mac, other in pairs:
        text = text.replace(mac, other)
    return text


def available() -> bool:
    """macOS with the PyObjC frameworks, Linux on X11 with AT-SPI, or Windows with UI Automation."""
    if platform.system() not in ("Darwin", "Linux", "Windows"):
        return False
    from openprogram.programs.tools.computer_use.computer_use_agent.desktop.backends import support
    return bool(support()["available"])


def normalized_app(app: Any) -> str:
    """The key an approval rule is written for: the app as the model named it, lower-cased."""
    return " ".join(str(app or "").split()).lower()


def approval(steps: list[tuple[str, dict]], args: dict) -> str | bool:
    """Every action except the read-only listing asks once per application."""
    if steps and all(action in READ_ONLY_ACTIONS for action, _ in steps):
        return False
    return f"computer_use_agent controls {normalized_app(args.get('app')) or 'an application'}"


def _images(observation) -> list[bytes]:
    return [observation.image] if observation.image else []


def _clip_text(clip, *, transcribe: bool) -> str:
    """What the model learns of a recording: where it is, how long, and what was said."""
    head = f"Recorded {clip.seconds:g} seconds of {clip.app}, saved to {clip.path}."
    if clip.silent:
        return head + " It is silent: the app played no sound while recording."
    if not transcribe:
        return head
    from openprogram.runtime import speech_link
    try:
        spoken = speech_link.transcribe(clip.data)
    except speech_link.TranscriptionError as exc:
        return f"{head} Not transcribed: {exc}"
    text = spoken.get("text", "").strip()
    if not text:
        return head + f" No speech was recognized ({spoken.get('engine')})."
    return f"{head}\nTranscript ({spoken.get('engine')}, {spoken.get('model')}):\n{text}"


def open_target(args: dict, session: str) -> ToolReturn:
    """Opening the target: the named app's state, or the app list."""
    if str(args.get("app") or "").strip():
        return run([("get_app_state", {})], args, session)
    return run([("list_apps", {})], args, session)


def _step(action: str, step: dict, app: str) -> dict:
    """One acting step with the defaults the backend expects."""
    return {
        "mouse_button": "left", "click_count": 1, "key": "", "text": "", "value": None, "direction": "down",
        "pages": 1, "pixels": None, "action_name": "", "prefix": "", "suffix": "", "selection_type": "text",
        "format": "text", "duration": 0, "menu_path": None, "window": None, "window_id": None, "path": None,
        "element_index": None, "x": None, "y": None, "to_x": None, "to_y": None,
        **{key: value for key, value in step.items() if value is not None},
        "action": action, "app": app,
    }


def run(steps: list[tuple[str, dict]], args: dict, session: str) -> ToolReturn:
    """Run one action, or several acting steps on one app."""
    from openprogram.programs.tools.computer_use.computer_use_agent.desktop.backends import backend
    from openprogram.programs.tools.computer_use.computer_use_agent.desktop.base import ComputerUseError, Report

    try:
        computer = backend()
        if len(steps) == 1 and steps[0][0] not in ACTING_ACTIONS:
            action, step = steps[0]
            merged = {**args, **step}
            app = str(merged.get("app") or "")
            if action == "list_apps":
                return ToolReturn(text=computer.list_apps())
            if action not in ACTIONS:
                raise ComputerUseError(f"unknown app action {action!r}; actions: {', '.join(ACTIONS)}")
            if not app.strip():
                raise ComputerUseError(f"{action} needs app")
            if action == "list_windows":
                return ToolReturn(text=computer.list_windows(app))
            if action == "get_app_state":
                full = bool(merged.get("full"))
                observation = computer.get_state(session, app, window=merged.get("window") or None,
                                                 window_id=merged.get("window_id"), full=full, as_diff=not full,
                                                 include=merged.get("include") or "all")
                return ToolReturn(text=observation.text, images=_images(observation))
            if action == "zoom":
                observation = computer.zoom(session, app, merged.get("x"), merged.get("y"),
                                            merged.get("width"), merged.get("height"))
                return ToolReturn(text=observation.text, images=_images(observation))
            if action == "find":
                return ToolReturn(text=computer.find(session, app, merged.get("text") or "", merged.get("role") or ""))
            if action == "start_audio_recording":
                return ToolReturn(text=computer.start_audio(session, app, merged.get("max_duration")))
            clip = computer.stop_audio(session, app)
            # Models that accept audio input hear the recording itself; others get the text.
            return ToolReturn(text=_clip_text(clip, transcribe=merged.get("transcribe") is not False),
                              audio=[] if clip.silent else [clip.data])
        app = str(args.get("app") or "")
        batch = len(steps) > 1
        prepared = []
        for number, (action, step) in enumerate(steps, 1):
            if action not in ACTING_ACTIONS:
                if not batch:
                    raise ComputerUseError(f"unknown app action {action!r}; actions: {', '.join(ACTIONS)}")
                raise ComputerUseError(f"step {number}: {action!r} cannot run among several steps; steps are one "
                                       f"of {', '.join(ACTING_ACTIONS)}")
            named = str(step.get("app") or "")
            # The approval names one app, so a step cannot name another one.
            if named and app and normalized_app(named) != normalized_app(app):
                raise ComputerUseError(f"step {number} names another app; these steps drive {app} only")
            app = app or named
            prepared.append((action, step))
        if not app.strip():
            raise ComputerUseError(f"{steps[0][0]} needs app")
        done: list[str] = []
        changed, failure = False, None
        for number, (action, step) in enumerate(prepared, 1):
            try:
                summary = computer.act(session, action, _step(action, step, app))
            except ComputerUseError as exc:
                failure = f"step {number} ({action}) failed: {exc}" if batch else str(exc)
                break
            changed = changed or not isinstance(summary, Report)
            done.append(f"{number}. {summary}" if batch else str(summary))
        if not changed:
            if failure:
                return ToolReturn(text="\n".join([*done, f"Error: {failure}"]), is_error=True)
            return ToolReturn(text="\n".join(done))
        computer.settle(session, app)
        observation = computer.get_state(session, app, as_diff=True)
        head = ("Done:\n" + "\n".join(done)) if batch else f"Done: {done[0]}."
        if failure:
            head = (head + "\n" if done else "") + f"Error: {failure} The steps after it did not run."
        return ToolReturn(text=f"{head}\n\n{observation.text}", images=_images(observation), is_error=bool(failure))
    except ComputerUseError as exc:
        return ToolReturn(text=f"Error: {exc}", is_error=True)


__all__ = ["ACTING_ACTIONS", "ACTIONS", "AUDIO_ACTIONS", "NAME", "available", "approval", "guide", "normalized_app",
           "open_target", "run"]
