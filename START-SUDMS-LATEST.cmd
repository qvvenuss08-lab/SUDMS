@echo off
cd /d "%~dp0"
set "SUDMS_HTTPS=0"
".venv\Scripts\python.exe" open_current.py
if errorlevel 1 pause
