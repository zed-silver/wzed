@echo off
REM Removes the wzed shortcuts (Start Menu + autostart).
REM The repository folder and the .venv are left untouched.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Uninstall
echo.
pause
