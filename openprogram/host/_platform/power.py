"""Optional macOS idle-system-sleep assertion for active agent execution."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import logging
import sys
from collections.abc import Callable, Iterator

_log = logging.getLogger(__name__)
_IOPM_ASSERTION_LEVEL_ON = 255  # kIOPMAssertionLevelOn in IOPMLib.h


def _acquire_assertion() -> Callable[[], None]:
    if sys.platform != "darwin":
        raise OSError("idle sleep prevention is supported only on macOS")
    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    io = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    cf.CFRelease.restype = None
    io.IOPMAssertionCreateWithName.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
    ]
    io.IOPMAssertionCreateWithName.restype = ctypes.c_int32
    io.IOPMAssertionRelease.argtypes = [ctypes.c_uint32]
    io.IOPMAssertionRelease.restype = ctypes.c_int32
    strings = []
    try:
        for value in (b"PreventUserIdleSystemSleep", b"OpenProgram active agent execution"):
            pointer = cf.CFStringCreateWithCString(None, value, 0x08000100)
            if not pointer:
                raise OSError("unable to allocate power assertion description")
            strings.append(pointer)
        assertion_id = ctypes.c_uint32()
        status = io.IOPMAssertionCreateWithName(
            strings[0], _IOPM_ASSERTION_LEVEL_ON, strings[1], ctypes.byref(assertion_id),
        )
        if status:
            raise OSError(f"IOPMAssertionCreateWithName failed: {status}")
    finally:
        for pointer in strings:
            cf.CFRelease(pointer)

    def release() -> None:
        status = io.IOPMAssertionRelease(assertion_id)
        if status:
            raise OSError(f"IOPMAssertionRelease failed: {status}")

    return release


@contextmanager
def prevent_idle_sleep() -> Iterator[None]:
    """Read the opt-in setting once and release this execution's assertion."""
    from openprogram.state.config import read_config

    release = None
    try:
        config = read_config()
        execution = config.get("execution", {})
        if isinstance(execution, dict) and execution.get("prevent_idle_sleep") is True:
            release = _acquire_assertion()
    except Exception:
        _log.warning("Unable to prevent idle system sleep", exc_info=True)
    try:
        yield
    finally:
        if release is not None:
            try:
                release()
            except Exception:
                _log.warning("Unable to release idle sleep assertion", exc_info=True)
