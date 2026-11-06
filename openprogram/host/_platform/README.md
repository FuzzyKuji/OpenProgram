# `openprogram/host/_platform/`

> Platform operations that differ between POSIX and Windows, one module per area.

## Overview

Callers import the module that owns the operation: ``filesystem`` (paths,
owner-only permissions, directory handles), ``locking`` (``flock``),
``processes`` (liveness, kill trees, port owners), ``process_ownership``
(process groups and Windows jobs), ``terminal`` (shells, PTYs, bundled
tools), ``environment`` (browser, WSL, release and service backends),
``screen_capture_audio`` (audio-only ScreenCaptureKit streams on macOS) and
``asyncio``.

## Files in this directory

- **`asyncio.py`** — Platform asyncio
- **`environment.py`** — Platform environment
- **`filesystem.py`** — Platform filesystem
- **`locking.py`** — Advisory file locking with the POSIX ``fcntl.flock`` surface on every platform
- **`power.py`** — Optional macOS idle-system-sleep assertion for active agent execution
- **`process_ownership.py`** — Platform process ownership
- **`processes.py`** — Platform processes
- **`screen_capture_audio.py`** — Audio-only ScreenCaptureKit streams on macOS, and the WAV their samples become
- **`terminal.py`** — Platform terminal

_Auto-generated from `__init__.py` docstring — keep that as the source of truth; re-run `python scripts/gen_dir_readmes.py` from the repo root to refresh._
