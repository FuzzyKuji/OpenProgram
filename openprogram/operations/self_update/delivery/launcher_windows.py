"""Run the self-update controller as a Scheduled Task on Windows.

Unverified until a Windows machine or VM runs it.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
from xml.sax.saxutils import escape


def _task(label: str) -> str:
    return "OpenProgram\\" + label


def _definition(argv: list[str], env: dict[str, str], log: Path) -> str:
    variables = " & ".join(f'set "{name}={value}"' for name, value in env.items())
    quoted = " ".join(f'"{part}"' for part in argv)
    script = f'/c {variables} & {quoted} >> "{log}" 2>&1'
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>10</Count></RestartOnFailure>
  </Settings>
  <Actions><Exec><Command>cmd.exe</Command><Arguments>{escape(script)}</Arguments></Exec></Actions>
</Task>
"""


def submit_controller(label: str, argv: list[str], env: dict[str, str], log: Path) -> None:
    from .controller import ControllerLaunchError

    definition = log.with_name("controller-task.xml")
    definition.write_text(_definition(argv, env, log), encoding="utf-16")
    for arguments in (["/Create", "/TN", _task(label), "/XML", str(definition), "/F"], ["/Run", "/TN", _task(label)]):
        result = subprocess.run(["schtasks", *arguments], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise ControllerLaunchError(f"schtasks failed: {(result.stderr or result.stdout).strip()[:500]}")


def retire_controller(label: str) -> None:
    subprocess.run(["schtasks", "/Delete", "/TN", _task(label), "/F"], capture_output=True, text=True, timeout=30)


__all__ = ["retire_controller", "submit_controller"]
