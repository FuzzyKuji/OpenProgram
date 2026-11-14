# What a new Windows user does with the App's installer, on a real Windows:
# install without elevation, start the App, let its first run unpack the seed
# and start the worker. The user's folder has a name outside every Western code
# page, as on a Chinese Windows.
#
#   smoke-windows-desktop.ps1 -Installer SETUP.exe [-ExpectedVersion X.Y.Z]
#       [-UserHome DIR] [-HealthOnly] [-ToolCall [-Python PYTHON]] [-Uninstall]
#
# -HealthOnly  an older release, installed first to prove installing over it:
#              only that it reaches a healthy worker.
# -ToolCall    then one real tool call through the App's worker against a
#              loopback stand-in model (smoke-tool-call.py, run by PYTHON):
#              the command's UTF-8 output and exit code must reach the model.
# -Uninstall   afterwards run the uninstaller and prove it stops the worker,
#              removes the logon task and keeps the user's data.
# -LogDirectory DIR  copy the worker, recovery and App logs there at the end,
#              pass or fail, for a workflow to keep when the run fails.
#
# Run by .github/workflows/release.yml before a Windows App is uploaded, and by
# .github/workflows/windows-install-smoke.yml. This file stays ASCII so
# Windows PowerShell 5.1 reads it the same as PowerShell 7.
param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [string]$ExpectedVersion = "",
    [string]$UserHome = "",
    [int]$Port = 18100,
    [int]$TimeoutSeconds = 900,
    [switch]$HealthOnly,
    [switch]$ToolCall,
    [string]$Python = "python",
    [switch]$Uninstall,
    [string]$LogDirectory = ""
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AppId = "ai.openprogram.desktop"
$TaskName = "OpenProgram Worker"
$Failures = [Collections.Generic.List[string]]::new()

function Add-Failure([string]$Message) {
    $Failures.Add($Message)
    Write-Host "FAILED: $Message"
}

function Get-StoreProcess([string]$Root) {
    $Prefix = $Root + [IO.Path]::DirectorySeparatorChar
    @(Get-CimInstance Win32_Process -Property Name, ExecutablePath, ProcessId, ParentProcessId, CommandLine |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase) })
}

function Test-Window([int]$ProcessId) {
    $Found = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    return ($null -ne $Found) -and ($Found.MainWindowHandle -ne [IntPtr]::Zero)
}

function Test-Healthy {
    try {
        return (Invoke-RestMethod -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 5).status -eq "ok"
    } catch {
        return $false
    }
}

if (-not $UserHome) {
    # U+7528 U+6237: "user" in Chinese.
    $UserHome = Join-Path $env:RUNNER_TEMP ("op-" + [char]0x7528 + [char]0x6237 + "-home")
}
New-Item -ItemType Directory -Force -Path $UserHome | Out-Null
$Install = Join-Path $UserHome "Programs\OpenProgram"
$State = Join-Path $UserHome ".openprogram"
$Root = Join-Path $State "runtime"
$env:USERPROFILE = $UserHome
$env:HOME = $UserHome
Remove-Item Env:OPENPROGRAM_WEB_PORT -ErrorAction SilentlyContinue
Remove-Item Env:OPENPROGRAM_STATE_DIR -ErrorAction SilentlyContinue

# /S is silent, /currentuser installs for this user with no elevation, and /D
# has to come last and unquoted.
$Setup = Start-Process -FilePath $Installer -ArgumentList "/S", "/currentuser", "/D=$Install" -Wait -PassThru
if ($Setup.ExitCode -ne 0) { throw "the installer exited with code $($Setup.ExitCode)" }
$Exe = Join-Path $Install "OpenProgram.exe"
if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw "OpenProgram.exe is missing after the install" }
$Installed = (Get-Item -LiteralPath $Exe).VersionInfo.ProductVersion
# electron-builder writes the product version in Windows' four-part form,
# 1.2.0.0 for 1.2.0; only a zero fourth part is dropped, as
# desktop_bundle_metadata does.
if ($Installed -match '^(\d+\.\d+\.\d+)\.0$') { $Installed = $Matches[1] }
if ($ExpectedVersion -and $Installed -ne $ExpectedVersion) {
    throw "the install left version $Installed, not $ExpectedVersion"
}

$Shortcut = $null
if (-not $HealthOnly) {
    if (-not (Test-Path -LiteralPath (Join-Path $Install "resources\seed\openprogram-launcher.exe") -PathType Leaf)) {
        Add-Failure "the App carries no seed launcher"
    }
    # The installer puts the shortcut in the Start menu folder the shell
    # resolves for this user. With USERPROFILE moved that need not be under
    # APPDATA, which this script leaves alone; this process asks the shell the
    # same way, with the environment the installer inherited.
    $StartMenu = [Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
    if ($StartMenu -and (Test-Path -LiteralPath $StartMenu -PathType Container)) {
        $Shortcut = Get-ChildItem -LiteralPath $StartMenu -Filter "OpenProgram.lnk" -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
    }
    if (-not $Shortcut) {
        $Searched = @(@(
            (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"),
            (Join-Path $UserHome "AppData\Roaming\Microsoft\Windows\Start Menu\Programs"),
            [Environment]::GetFolderPath([Environment+SpecialFolder]::CommonPrograms)
        ) | Where-Object { $_ -and $_ -ne $StartMenu -and (Test-Path -LiteralPath $_ -PathType Container) })
        $Elsewhere = @($Searched | ForEach-Object {
            Get-ChildItem -LiteralPath $_ -Filter "OpenProgram.lnk" -Recurse -ErrorAction SilentlyContinue
        } | ForEach-Object { $_.FullName })
        if ($Elsewhere.Count -gt 0) {
            Add-Failure "the Start menu shortcut is at $($Elsewhere -join ', '), not in this user's Start menu ($StartMenu)"
        } else {
            Add-Failure "the install made no Start menu shortcut (looked in $StartMenu and $($Searched -join ', '))"
        }
    } else {
        Write-Host "Start menu shortcut: $($Shortcut.FullName)"
        # Windows groups the taskbar button and the notifications under the
        # shortcut's id, so it has to be the one the App sets for itself.
        $Shell = New-Object -ComObject Shell.Application
        $Found = $Shell.Namespace($Shortcut.DirectoryName).ParseName($Shortcut.Name).ExtendedProperty("System.AppUserModel.ID")
        if ($Found -ne $AppId) { Add-Failure "the Start menu shortcut's application id is '$Found', not '$AppId'" }
    }
}

$App = Start-Process -FilePath $Exe -PassThru
try {
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while (-not (Test-Healthy) -and (Get-Date) -lt $Deadline) { Start-Sleep -Seconds 2 }
    if (-not (Test-Healthy)) {
        $AppProcess = Get-Process -Id $App.Id -ErrorAction SilentlyContinue
        if ($AppProcess) { Write-Host "the App (process $($App.Id)) is still running" }
        else { Write-Host "the App (process $($App.Id)) has exited with code $($App.ExitCode)" }
        Get-CimInstance Win32_Process -Filter "Name = 'OpenProgram.exe' OR Name = 'python.exe' OR Name = 'openprogram-launcher.exe'" |
            Format-Table ProcessId, ParentProcessId, Name, CommandLine -AutoSize -Wrap | Out-String -Width 400 | Write-Host
        foreach ($Log in (Join-Path $State "worker.log"), (Join-Path $Root "recovery.log")) {
            Write-Host "--- $Log"
            Get-Content -LiteralPath $Log -Tail 200 -ErrorAction SilentlyContinue
        }
        Get-ChildItem -LiteralPath $Root -Force -ErrorAction SilentlyContinue | Format-Table Name, Length
        throw "version $Installed did not reach a healthy worker in $TimeoutSeconds seconds"
    }
    $Chat = Invoke-WebRequest "http://127.0.0.1:$Port/chat" -UseBasicParsing
    if ($Chat.StatusCode -ne 200) { Add-Failure "/chat answered $($Chat.StatusCode)" }
    Write-Host "version $Installed is healthy under $UserHome"

    if (-not $HealthOnly) {
        foreach ($Name in "current", "identity\openprogram-launcher.exe", "bin\openprogram.cmd", "bootstrap\versions.py") {
            if (-not (Test-Path -LiteralPath (Join-Path $Root $Name) -PathType Leaf)) { Add-Failure "the first run left no runtime\$Name" }
        }
        foreach ($Name in ".seeding", ".seed-work", ".seed-links") {
            if (Test-Path -LiteralPath (Join-Path $Root $Name)) { Add-Failure "the first run left runtime\$Name behind" }
        }

        # The worker must not open a console window of its own.
        $Running = @(Get-StoreProcess $Root)
        if ($Running.Count -eq 0) { Add-Failure "no process runs from the version store" }
        $Ids = @($Running | ForEach-Object { $_.ProcessId })
        foreach ($Process in $Running) {
            if (Test-Window $Process.ProcessId) { Add-Failure "$($Process.ExecutablePath) shows a window" }
        }
        $Consoles = @(Get-CimInstance Win32_Process -Filter "Name = 'conhost.exe' OR Name = 'OpenConsole.exe' OR Name = 'WindowsTerminal.exe'" |
            Where-Object { $Ids -contains $_.ParentProcessId })
        foreach ($Console in $Consoles) {
            if (Test-Window $Console.ProcessId) { Add-Failure "the worker has a visible console (process $($Console.ProcessId))" }
        }

        # The worker is the Python the launcher started, in UTF-8 mode. The
        # launcher quotes every argument ("-X" "utf8" "-m" "openprogram"
        # "worker" "run"), and the venv's python.exe passes that line on to the
        # base Python it starts, so the quotes are dropped before matching.
        $Worker = @($Running | Where-Object {
            $_.Name -eq "python.exe" -and $_.CommandLine -and
            ($_.CommandLine -replace '"', '') -match '(^|\s)-m openprogram worker run(\s|$)'
        })
        if ($Worker.Count -eq 0) {
            $Seen = ($Running | ForEach-Object { "$($_.ProcessId): $($_.CommandLine)" }) -join "; "
            Add-Failure "no Python from the version store runs the worker; running from the store: $Seen"
        } else {
            $Plain = @($Worker | Where-Object { ($_.CommandLine -replace '"', '') -notmatch '(^|\s)-X utf8(\s|$)' })
            if ($Plain.Count -gt 0) { Add-Failure "the worker's Python is not in UTF-8 mode: $($Plain[0].CommandLine)" }
        }

        $Log = Join-Path $State "worker.log"
        if (-not (Test-Path -LiteralPath $Log -PathType Leaf) -or (Get-Item -LiteralPath $Log).Length -eq 0) {
            Add-Failure "worker.log is empty: the worker's output went somewhere else"
        }

        $Command = Join-Path $Root "bin\openprogram.cmd"
        $Reported = (& $Command --version | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $Reported) { Add-Failure "the installed command does not run (exit $LASTEXITCODE)" }
        & $Command versions list
        if ($LASTEXITCODE -ne 0) { Add-Failure "'openprogram versions list' does not run (exit $LASTEXITCODE)" }

        # Without the system-wide long path switch, a program that does not ask
        # for long paths itself cannot open a file whose path has 260 characters.
        $Extended = "\\?\" + $Root
        $Longest = ""
        $Links = 0
        $Pending = [Collections.Generic.Stack[string]]::new()
        $Pending.Push($Extended)
        while ($Pending.Count -gt 0) {
            $Directory = $Pending.Pop()
            foreach ($Entry in [IO.Directory]::EnumerateFileSystemEntries($Directory)) {
                $Attributes = [IO.File]::GetAttributes($Entry)
                if (($Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { $Links += 1; continue }
                if (($Attributes -band [IO.FileAttributes]::Directory) -ne 0) { $Pending.Push($Entry) }
                elseif ($Entry.Length -gt $Longest.Length) { $Longest = $Entry }
            }
        }
        $Length = $Longest.Length - 4
        $Relative = $Length - $Root.Length - 1
        Write-Host "longest path in the version store: $Length characters, $Relative below runtime\ ($($Longest.Substring(4)))"
        Write-Host "links in the version store: $Links"
        if ($Length -ge 260) { Add-Failure "a file in the version store has a path of $Length characters" }
        # C:\Users\ plus a 20 character name plus \.openprogram\runtime\ is 52.
        if ($Relative + 52 -ge 260) { Add-Failure "the version store is $Relative characters deep, too deep for a 20 character user name" }
    }

    if ($ToolCall) {
        $Command = Join-Path $Root "bin\openprogram.cmd"
        & $Python (Join-Path $PSScriptRoot "smoke-tool-call.py") --openprogram $Command --home $UserHome
        if ($LASTEXITCODE -ne 0) { Add-Failure "one tool call through the installed App failed (exit $LASTEXITCODE)" }
    }

    if ($Uninstall) {
        $Marker = Join-Path $State "smoke-user-data.txt"
        Set-Content -LiteralPath $Marker -Value "kept" -Encoding ascii
        # A logon task as the worker service registers it, pointing at this
        # state directory and never started.
        $TaskScript = Join-Path $State "worker-service.cmd"
        Set-Content -LiteralPath $TaskScript -Value "@echo off" -Encoding ascii
        $Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/d /s /c `"`"$TaskScript`"`""
        Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger (New-ScheduledTaskTrigger -AtLogOn) -Force | Out-Null

        Get-Process -Name OpenProgram -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        $Uninstaller = Join-Path $Install "Uninstall OpenProgram.exe"
        if (-not (Test-Path -LiteralPath $Uninstaller -PathType Leaf)) { throw "the install has no uninstaller" }
        # _?= keeps the uninstaller in place, so waiting for it waits for the whole uninstall.
        $Removal = Start-Process -FilePath $Uninstaller -ArgumentList "/S", "_?=$Install" -Wait -PassThru
        if ($Removal.ExitCode -ne 0) { Add-Failure "the uninstaller exited with code $($Removal.ExitCode)" }

        if (Test-Path -LiteralPath $Exe) { Add-Failure "the uninstall left OpenProgram.exe" }
        if ($Shortcut -and (Test-Path -LiteralPath $Shortcut.FullName)) { Add-Failure "the uninstall left the Start menu shortcut" }
        $Left = @(Get-StoreProcess $Root)
        if ($Left.Count -gt 0) { Add-Failure "after the uninstall these still run: $(($Left | ForEach-Object { $_.ExecutablePath }) -join ', ')" }
        if (Test-Healthy) { Add-Failure "after the uninstall a worker still answers on port $Port" }
        if ($null -ne (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
            Add-Failure "the uninstall left the logon task"
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $TaskScript) { Add-Failure "the uninstall left the logon task's launcher" }
        if (-not (Test-Path -LiteralPath $Marker -PathType Leaf)) { Add-Failure "the uninstall deleted the user's data" }
        if (-not (Test-Path -LiteralPath (Join-Path $Root "current") -PathType Leaf)) { Add-Failure "the uninstall removed the version store" }
    }
} finally {
    $Command = Join-Path $Root "bin\openprogram.cmd"
    if (Test-Path -LiteralPath $Command -PathType Leaf) {
        & $Command worker stop 2>$null | Out-Null
    }
    Stop-Process -Id $App.Id -Force -ErrorAction SilentlyContinue
    Get-Process -Name OpenProgram -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    if ($LogDirectory) {
        # Whatever there is; a missing log is itself the finding.
        try {
            New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
            $Sources = @(
                (Join-Path $State "worker.log"),
                (Join-Path $Root "recovery.log"),
                (Join-Path $State "config.json"),
                (Join-Path $Root "current")
            )
            foreach ($Source in $Sources) {
                if (Test-Path -LiteralPath $Source -PathType Leaf) {
                    Copy-Item -LiteralPath $Source -Destination $LogDirectory -Force -ErrorAction SilentlyContinue
                }
            }
            $AppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)
            foreach ($Folder in (Join-Path $State "logs"), (Join-Path $AppData "OpenProgram\logs")) {
                if (Test-Path -LiteralPath $Folder -PathType Container) {
                    Copy-Item -LiteralPath $Folder -Destination (Join-Path $LogDirectory ((Split-Path -Leaf (Split-Path -Parent $Folder)) + "-logs")) -Recurse -Force -ErrorAction SilentlyContinue
                }
            }
            Get-ChildItem -LiteralPath $Root -Force -ErrorAction SilentlyContinue |
                Format-Table Mode, LastWriteTime, Length, Name -AutoSize | Out-String -Width 200 |
                Set-Content -LiteralPath (Join-Path $LogDirectory "runtime-listing.txt") -Encoding ascii
        } catch {
            Write-Host "could not keep the logs in ${LogDirectory}: $($_.Exception.Message)"
        }
    }
}

if ($Failures.Count -gt 0) {
    throw "the Windows App smoke found $($Failures.Count) problem(s):`n  " + ($Failures -join "`n  ")
}
Write-Host "the Windows App smoke passed for version $Installed"
