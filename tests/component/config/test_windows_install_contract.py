from __future__ import annotations

import os
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]


def test_windows_installer_builds_web_and_tui_and_checks_failures() -> None:
    installer = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")

    assert "function Invoke-CheckedNative" in installer
    assert "npm.cmd\" ci --include-workspace-root" in installer
    assert "npm.cmd\" run build --workspace apps/web" in installer
    assert "npm.cmd\" run build --workspace apps/cli" in installer
    assert 'cmd /c "npm install"' not in installer
    assert installer.index("if ($Minimal)") < installer.index(
        'Step "installing web and terminal UI dependencies"'
    )


def test_windows_installer_uses_checkout_virtualenv_by_default() -> None:
    installer = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")

    resolve = installer[installer.index("function Resolve-Python") :]
    resolve = resolve[: resolve.index("$PY = Resolve-Python")]
    assert "CONDA_PREFIX" not in resolve
    assert "VIRTUAL_ENV" not in resolve
    assert '$HostRoot\\.venv\\Scripts\\python.exe' in resolve


def test_windows_installer_exposes_the_isolated_cli_on_user_path() -> None:
    installer = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")

    assert 'Join-Path $env:LOCALAPPDATA "OpenProgram\\bin"' in installer
    assert 'Join-Path $binDir "openprogram.cmd"' in installer
    assert '"$quotedPython" -X utf8 -m openprogram %*' in installer
    assert '$environmentKey.SetValue("Path", $updated, $kind)' in installer
    assert '& $PY -m openprogram programs install $source' in installer


def test_windows_release_installer_replaces_stale_launchers_atomically() -> None:
    installer = (
        ROOT / "scripts" / "release" / "install-release.ps1"
    ).read_text(encoding="utf-8")

    launcher_section = installer[installer.index("$LauncherCmd =") :]
    assert 'set "OPENPROGRAM_IMMUTABLE_RUNTIME=1"' in launcher_section
    assert 'Publish-CliLauncher $CmdTemporary $LauncherCmd' in launcher_section
    assert 'Move-Atomic $Source $Target (Join-Path $Directory "openprogram.previous.cmd")' in installer
    assert 'Remove-PowerShellLaunchers $Directory' in installer
    assert 'if (-not (Test-Path -LiteralPath $LauncherCmd' not in launcher_section
    assert "ConvertTo-CmdBatchLiteral $PythonBin" in launcher_section
    assert '"$CmdPython" -I -B -X utf8 -m openprogram %*' in launcher_section
    assert "powershell.exe -NoLogo" not in launcher_section


def test_packaged_runtime_smoke_detects_managed_release_without_env_marker() -> None:
    smoke = (
        ROOT / "scripts" / "release" / "smoke-packaged-runtime.ps1"
    ).read_text(encoding="utf-8")

    assert "Remove-Item Env:OPENPROGRAM_IMMUTABLE_RUNTIME" in smoke
    assert "detect_install_method() is InstallMethod.MANAGED_RELEASE" in smoke


def test_desktop_upgrade_preparation_is_path_scoped_and_long_path_aware() -> None:
    helper = (
        ROOT / "apps" / "desktop" / "build" / "prepare-upgrade.ps1"
    ).read_text(encoding="utf-8")
    installer = (
        ROOT / "apps" / "desktop" / "build" / "installer.nsh"
    ).read_text(encoding="utf-8")

    assert "OpenProgram.exe" in helper
    assert "resources\\app.asar" in helper
    assert "StartsWith(" in helper
    assert "[StringComparison]::OrdinalIgnoreCase" in helper
    assert "ConvertTo-ExtendedPath" in helper
    assert "[IO.Directory]::EnumerateFileSystemEntries" in helper
    assert "$Entry.Length - $ExtendedRoot.Length) -ge 248" in helper
    assert "[IO.FileAttributes]::ReparsePoint" in helper
    assert "prepare-upgrade.ps1" in installer
    assert "customCheckAppRunning" not in installer


def test_uninstalling_the_app_stops_the_worker_and_its_logon_task_and_keeps_user_data() -> None:
    build = ROOT / "apps" / "desktop" / "build"
    installer = (build / "installer.nsh").read_text(encoding="utf-8")
    helper = (build / "remove-background.ps1").read_text(encoding="utf-8")

    hook = installer[installer.index("!macro customUnInstall"):]
    hook = hook[: hook.index("!macroend")]
    # An upgrade runs the old uninstaller too; that must leave the worker alone.
    assert hook.index("${ifNot} ${isUpdated}") < hook.index("remove-background.ps1")
    assert '-File "$PLUGINSDIR\\remove-background.ps1" -InstallRoot "$INSTDIR"' in hook
    assert "Quit" not in hook and "Abort" not in hook, "a stuck worker must not block the uninstall"

    assert 'Join-Path $env:USERPROFILE ".openprogram"' in helper
    assert '"bin\\openprogram.cmd"' in helper and "worker stop" in helper
    assert "Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false" in helper
    assert "$Arguments.IndexOf($TaskScript" in helper, "only the task this state directory installed"
    # The one name the worker service gives its task and its launcher.
    from openprogram.operations.worker.services import windows as service

    assert f'$TaskName = "{service.TASK_NAME}"' in helper
    assert f'$TaskScriptName = "{service.SCRIPT_NAME}"' in helper
    # Nothing but the generated task launcher is deleted: no conversation, setting or version.
    removals = [line.strip() for line in helper.splitlines()
                if "Remove-Item" in line and not line.lstrip().startswith("#")]
    assert removals == ["Remove-Item -LiteralPath $TaskScript -Force -ErrorAction SilentlyContinue"]
    assert "-Recurse" not in helper and "[IO.Directory]::Delete" not in helper and "rmdir" not in helper.lower()
    assert '$Process.Name -ne "OpenProgram.exe"' in helper
    # An uninstaller run in place is a program under the install folder, and
    # the helper's parent: it is never among the processes the helper ends.
    listing = helper[helper.index("function Get-BackgroundProcess"):]
    listing = listing[: listing.index("\n}")]
    assert "-not $OwnChain.Contains([int]$Process.ProcessId)" in listing
    chain = helper[helper.index("function Get-OwnProcessChain"):helper.index("function Get-BackgroundProcess")]
    assert "$Current = [int]$PID" in chain and "ParentProcessId" in chain
    assert "$OwnChain = Get-OwnProcessChain" in chain
    assert chain.index("} catch {") < chain.index("$Roots = @($Store)"), (
        "without the chain only the version store is searched"
    )
    # electron-builder's own switch covers the Electron profile only, and stays off.
    package = json.loads((ROOT / "apps" / "desktop" / "package.json").read_text(encoding="utf-8"))
    assert package["build"]["nsis"]["deleteAppDataOnUninstall"] is False


def test_windows_product_runtime_uses_short_python_root_without_bytecode() -> None:
    builder = (
        ROOT / "scripts" / "release" / "build-product-runtime.ps1"
    ).read_text(encoding="utf-8")

    assert '$ShortPythonHome = Join-Path $RuntimeRoot "py"' in builder
    assert 'Move-Item -LiteralPath $PythonHome -Destination $ShortPythonHome' in builder
    assert '-Directory -Filter "__pycache__"' in builder
    assert '$_.Extension -in ".pyc", ".pyo"' in builder
    assert 'Invoke-NativeOutput $PythonBin -I -B' in builder
    assert 'Invoke-Native $PythonBin -I -B $Verifier' in builder


@pytest.mark.skipif(sys.platform != "win32", reason="Windows installer contract")
def test_uninstall_helper_spares_the_uninstaller_that_runs_it_in_place(tmp_path: Path) -> None:
    """`Uninstall OpenProgram.exe /S _?=<folder>` runs from the install folder."""

    install = tmp_path / "OpenProgram"
    install.mkdir()
    (install / "OpenProgram.exe").write_bytes(b"marker")
    state = tmp_path / "state"
    state.mkdir()
    command = shutil.which("cmd.exe")
    powershell = shutil.which("powershell.exe")
    assert command and powershell
    # Stands for the uninstaller: a program in the install folder that starts
    # the helper and waits for it.
    uninstaller = install / "Uninstall OpenProgram.exe"
    shutil.copy2(command, uninstaller)
    helper = ROOT / "apps" / "desktop" / "build" / "remove-background.ps1"

    done = subprocess.run(
        [str(uninstaller), "/d", "/c", powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-File", str(helper),
         "-InstallRoot", str(install), "-StateDir", str(state)],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    output = done.stdout.decode("ascii", "replace") + done.stderr.decode("ascii", "replace")
    assert done.returncode == 0, output
    assert "ended 0 process(es)" in output


@pytest.mark.skipif(sys.platform != "win32", reason="Windows installer contract")
def test_desktop_upgrade_helper_stops_embedded_process_and_removes_long_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "OpenProgram"
    resources = root / "resources"
    resources.mkdir(parents=True)
    (root / "OpenProgram.exe").write_bytes(b"marker")
    (resources / "app.asar").write_bytes(b"marker")

    # Keep every component below NTFS's limit while crossing the legacy
    # MAX_PATH threshold that electron-builder's old-install move expands.
    deep = resources / "runtime"
    index = 0
    while len(str(deep / "legacy.pyc")) < 250:
        deep /= f"legacy-{index:02d}-" + ("x" * 32)
        index += 1
    legacy_file = deep / "legacy.pyc"
    extended_deep = Path("\\\\?\\" + str(deep))
    extended_deep.mkdir(parents=True)
    (extended_deep / legacy_file.name).write_bytes(b"old bytecode")
    assert len(str(legacy_file)) >= 248

    command = shutil.which("cmd.exe")
    powershell = shutil.which("powershell.exe")
    assert command and powershell
    embedded = root / "resources" / "runtime" / "worker.exe"
    shutil.copy2(command, embedded)
    # A cmd builtin blocks on our open stdin pipe without spawning a ping
    # child outside the installation root or exiting naturally on a timer.
    worker = subprocess.Popen(
        [str(embedded), "/d", "/q", "/c", "set /p OPENPROGRAM_UPGRADE_FIXTURE=waiting"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        completed = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(
                    ROOT
                    / "apps"
                    / "desktop"
                    / "build"
                    / "prepare-upgrade.ps1"
                ),
                "-InstallRoot",
                str(root),
            ],
            check=False,
            capture_output=True,
            text=True,
            # Allow cold PowerShell/CIM startup on loaded native runners,
            # plus the helper's bounded CIM queries and process-exit window.
            # The fixture waits on stdin, so natural exit cannot pass.
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        worker.wait(timeout=5)
        assert not os.path.exists("\\\\?\\" + str(legacy_file))
        assert "stopped 1 process(es)" in completed.stdout
        assert "removed 1 legacy long-path file(s)" in completed.stdout
    finally:
        assert worker.stdin is not None
        worker.stdin.close()
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)


def test_windows_release_installer_reads_the_architecture_on_old_dotnet() -> None:
    """Windows PowerShell on .NET Framework before 4.7.1 has no
    RuntimeInformation.OSArchitecture; strict mode stopped the installer on
    it ("The property 'OSArchitecture' cannot be found"). The read is guarded
    and falls back to the native processor the environment names."""
    installer = (
        ROOT / "scripts" / "release" / "install-release.ps1"
    ).read_text(encoding="utf-8")

    function = installer[installer.index("function Get-OSArchitecture"):installer.index("$Architecture = Get-OSArchitecture")]
    assert function.index("try {") < function.index("::OSArchitecture") < function.index("} catch {")
    assert "$env:PROCESSOR_ARCHITEW6432" in function
    assert '"AMD64" { return "x64" }' in function
    assert '"ARM64" { return "arm64" }' in function
    assert installer.count("::OSArchitecture") == 1


def test_windows_release_installer_names_a_release_without_windows_packages() -> None:
    """A release built without Windows assets answered with a bare
    "release download failed with HTTP 404"; it says what is missing and
    where the source installation is."""
    installer = (
        ROOT / "scripts" / "release" / "install-release.ps1"
    ).read_text(encoding="utf-8")

    download = installer[installer.index('Download-ReleaseFile "$ReleaseUrl/$ArchiveName" $Archive') - 200:]
    assert '-match "HTTP 404"' in download[:600]
    assert "has no Windows $Arch package" in download[:900]
    assert "install.html#development-checkout" in download[:900]


def test_the_last_uninstall_offers_to_delete_the_version_store_unticked() -> None:
    build = ROOT / "apps" / "desktop" / "build"
    installer = (build / "installer.nsh").read_text(encoding="utf-8")
    helper = (build / "runtime-users.ps1").read_text(encoding="utf-8")

    install = installer[installer.index("!macro customInstall"):]
    install = install[: install.index("!macroend")]
    assert '-File "$PLUGINSDIR\\runtime-users.ps1" -Action add -InstallRoot "$INSTDIR"' in install

    hook = installer[installer.index("!macro customUnInstall"):]
    hook = hook[: hook.index("!macroend")]
    # Only a real uninstall, after the worker that runs from the store stopped.
    assert hook.index("${ifNot} ${isUpdated}") < hook.index("remove-background.ps1") < hook.index("-Action remove")
    # Default No; a silent uninstall keeps the store.
    assert "MB_YESNO|MB_DEFBUTTON2" in hook and "/SD IDNO IDNO keep_runtime" in hook
    assert hook.index("IDNO keep_runtime") < hook.index("-Action delete") < hook.index("keep_runtime:")
    assert "Quit" not in hook and "Abort" not in hook

    # The helper deletes the store folder and nothing else.
    removals = [line.strip() for line in helper.splitlines()
                if "Remove-Item" in line and not line.lstrip().startswith("#")]
    assert len(removals) == 1 and "Remove-Item -LiteralPath $Store -Recurse" in removals[0]
    assert '$Store = Join-Path ([IO.Path]::GetFullPath($StateDir)) "runtime"' in helper
    assert 'Get-InstallId "app" $InstallRoot' in helper
