@echo off
REM wzed one-click installer - double-click this file.
REM Runs install.ps1 with an execution-policy bypass and keeps the window open.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
