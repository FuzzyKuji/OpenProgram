@echo off
rem Installed as <root>\bin\openprogram.cmd. `versions` runs outside every
rem version, so it works when the current one is broken.
setlocal
set "ROOT=%~dp0.."
for /f "usebackq tokens=1,* delims==" %%A in ("%ROOT%\current") do (
  if "%%A"=="version" set "VERSION=%%B"
  if "%%A"=="base" set "BASE=%%B"
)
if /i "%~1"=="versions" (
  set "BASE_PYTHON=%ROOT%\bases\%BASE%\python\python.exe"
  if not exist "%ROOT%\bases\%BASE%\python\python.exe" (
    for /d %%D in ("%ROOT%\bases\*") do if exist "%%D\python\python.exe" set "BASE_PYTHON=%%D\python\python.exe"
  )
  shift
  goto versions
)
"%ROOT%\versions\%VERSION%\venv\Scripts\python.exe" -I -B -m openprogram %*
exit /b %ERRORLEVEL%

:versions
set "ARGUMENTS="
:collect
if "%~1"=="" goto run
set "ARGUMENTS=%ARGUMENTS% %1"
shift
goto collect
:run
"%BASE_PYTHON%" -I -B "%ROOT%\bootstrap\versions.py" --root "%ROOT%" %ARGUMENTS%
exit /b %ERRORLEVEL%
