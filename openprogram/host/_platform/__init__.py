"""Platform operations that differ between POSIX and Windows, one module per area.

Callers import the module that owns the operation: ``filesystem`` (paths,
owner-only permissions, directory handles), ``locking`` (``flock``),
``processes`` (liveness, kill trees, port owners), ``process_ownership``
(process groups and Windows jobs), ``terminal`` (shells, PTYs, bundled
tools), ``environment`` (browser, WSL, release and service backends),
``screen_capture_audio`` (audio-only ScreenCaptureKit streams on macOS) and
``asyncio``.
"""
