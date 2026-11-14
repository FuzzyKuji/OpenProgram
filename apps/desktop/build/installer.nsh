; Stop background processes that run from the managed application runtime
; before electron-builder launches the previous uninstaller. `customInit` runs
; after initMultiUser has restored the existing InstallLocation, so $INSTDIR is
; authoritative for both default and user-selected installation directories.
;
; The visible Electron process remains handled by electron-builder's default
; CHECK_APP_RUNNING implementation. This hook only owns processes that run from
; the installation root. A thin install runs its worker from the version store
; in the user's state directory, which an upgrade of the shell does not touch.
!macro customInit
  DetailPrint "Stopping OpenProgram background processes..."
  InitPluginsDir
  File /oname=$PLUGINSDIR\prepare-upgrade.ps1 "${BUILD_RESOURCES_DIR}\prepare-upgrade.ps1"
  nsExec::ExecToStack `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\prepare-upgrade.ps1" -InstallRoot "$INSTDIR"`
  Pop $0
  Pop $1
  ${if} $0 != 0
    DetailPrint "Unable to stop OpenProgram background processes: $1"
    MessageBox MB_OK|MB_ICONSTOP "OpenProgram could not stop its background worker. Close OpenProgram and try the installer again." /SD IDOK
    SetErrorLevel 12
    Quit
  ${endif}
!macroend

; List this App among the version store's users (runtime-users.ps1), so the
; last uninstaller knows whether the store is still needed. Only a store that
; already holds a version is touched: a first launch seeds into an empty
; folder, and the worker lists the App itself once it runs. A failure here only
; means the uninstaller later will not offer to delete the store.
!macro customInstall
  InitPluginsDir
  File /oname=$PLUGINSDIR\runtime-users.ps1 "${BUILD_RESOURCES_DIR}\runtime-users.ps1"
  nsExec::ExecToStack `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\runtime-users.ps1" -Action add -InstallRoot "$INSTDIR"`
  Pop $0
  Pop $1
!macroend

; A real uninstall, not the old copy that an upgrade or a reinstall removes
; first (electron-builder passes that one --updated). The worker and its logon
; task run from the version store in the user's state directory, so they would
; outlive the App. Stop them here. The state directory is left as it is:
; conversations, settings and the version store are the user's to keep or
; delete. A worker that will not stop does not block the uninstall.
!macro customUnInstall
  ${ifNot} ${isUpdated}
    DetailPrint "Stopping the OpenProgram background worker..."
    InitPluginsDir
    File /oname=$PLUGINSDIR\remove-background.ps1 "${BUILD_RESOURCES_DIR}\remove-background.ps1"
    nsExec::ExecToStack `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\remove-background.ps1" -InstallRoot "$INSTDIR"`
    Pop $0
    Pop $1
    ${if} $0 != 0
      DetailPrint "The OpenProgram background worker is still running: $1"
    ${endif}
    ; The last install that used the downloaded runtime versions offers to
    ; delete them. The answer defaults to No, and a silent uninstall keeps
    ; them; ~\.openprogram's conversations, settings and credentials stay.
    File /oname=$PLUGINSDIR\runtime-users.ps1 "${BUILD_RESOURCES_DIR}\runtime-users.ps1"
    nsExec::ExecToStack `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\runtime-users.ps1" -Action remove -InstallRoot "$INSTDIR"`
    Pop $0
    Pop $1
    ${if} $0 == 10
      MessageBox MB_YESNO|MB_DEFBUTTON2|MB_ICONQUESTION "No other OpenProgram install uses the downloaded runtime versions (about $1 GB).$\r$\n$\r$\nAlso delete them? Your conversations, settings and credentials are kept." /SD IDNO IDNO keep_runtime
        nsExec::ExecToStack `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\runtime-users.ps1" -Action delete`
        Pop $0
        Pop $1
      keep_runtime:
    ${endif}
  ${endif}
!macroend
