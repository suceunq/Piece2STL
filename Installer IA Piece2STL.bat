@echo off
setlocal
cd /d "%~dp0"
set "SETUP_SCRIPT=%~dp0setup_ai.ps1"
if not exist "%SETUP_SCRIPT%" set "SETUP_SCRIPT=%~dp0scripts\setup_ai.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SETUP_SCRIPT%"
if errorlevel 1 (
    echo.
    echo L'installation du mode IA a echoue.
)
pause
