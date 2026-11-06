"""Keep a POSIX process-group identity alive until its ordinary children exit.

This small detached group leader has no runtime/config dependencies. A parent
supervisor owns its Popen handle and may terminate this exact group. Commands
that deliberately create another session are outside this managed group.

Without a terminal the command's stdin is closed, as in Codex. With one, the
leader makes a new pseudo-terminal its controlling terminal with this group in
the foreground, so input arrives raw and Ctrl-C (``\x03``) interrupts the
whole group.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time

_log = logging.getLogger(__name__)


def _other_members():
    # ps itself runs in our group; exclude it after collecting its snapshot.
    inspector = subprocess.Popen(["ps", "-axo", "pid=,pgid=,stat="],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output, _ = inspector.communicate(timeout=3)
    if inspector.returncode:
        raise RuntimeError("process group inspection failed")
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and int(fields[1]) == os.getpid():
            if int(fields[0]) not in {os.getpid(), inspector.pid} and not fields[2].startswith("Z"):
                return True
    return False


def _pump(source, target):
    try:
        while chunk := os.read(source, 8192):
            offset = 0
            while offset < len(chunk):
                offset += os.write(target, chunk[offset:])
    except OSError:
        pass  # EIO once every terminal descriptor of the command is closed


def _spawn_in_terminal(launch, pending_input):
    import fcntl
    import pty
    import struct
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
    # This leader started a session of its own and has no controlling
    # terminal yet; its group becomes the terminal's foreground group.
    fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
    os.tcsetpgrp(slave, os.getpgrp())
    env = dict(launch.pop("env", None) or os.environ)
    env.setdefault("TERM", "xterm-256color")
    proc = subprocess.Popen(**launch, env=env, stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    output = threading.Thread(target=_pump, args=(master, sys.stdout.fileno()), daemon=True)
    output.start()

    def forward_input():
        if pending_input:
            os.write(master, pending_input)
        _pump(sys.stdin.fileno(), master)

    threading.Thread(target=forward_input, daemon=True).start()
    return proc, output


def main():
    # A caught signal is reset by exec in the backend child; unlike SIG_IGN,
    # this does not accidentally make the launched command ignore SIGTERM.
    signal.signal(signal.SIGTERM, lambda *_: None)
    signal.signal(signal.SIGINT, lambda *_: None)
    try:
        # Use raw pipe I/O throughout: a daemon holding a buffered stdin
        # lock would abort the interpreter when the managed group finishes.
        frame = bytearray()
        while b"\n" not in frame:
            chunk = os.read(sys.stdin.fileno(), 8192)
            if not chunk:
                raise EOFError("missing process launch frame")
            frame.extend(chunk)
        header, _, pending_input = bytes(frame).partition(b"\n")
        launch = json.loads(header)
        output = None
        if launch.pop("_tty", False):
            proc, output = _spawn_in_terminal(launch, pending_input)
        else:
            proc = subprocess.Popen(**launch, stdin=subprocess.DEVNULL)
        code = proc.wait()
        while _other_members():
            time.sleep(0.1)
        if output is not None:
            output.join(timeout=2)
        return code if code >= 0 else 128 - code
    except BaseException as exc:
        _log.error("process group failed: %s", type(exc).__name__)
        # Losing the group owner must not silently detach live descendants.
        os.killpg(os.getpid(), signal.SIGKILL)
        return 1


if __name__ == "__main__":
    sys.exit(main())
