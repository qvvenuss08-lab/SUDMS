@echo off
cd /d "%~dp0"
set "SUDMS_RESTART_ROOT=%~dp0"
echo Checking and restarting the active SUDMS server on port 5056...
powershell.exe -NoProfile -Command "& ([ScriptBlock]::Create([IO.File]::ReadAllText((Join-Path $env:SUDMS_RESTART_ROOT 'restart_server.ps1'))))"
if errorlevel 1 (
  echo Restart check failed. Please send a screenshot of this window.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run_latest.py
pause
