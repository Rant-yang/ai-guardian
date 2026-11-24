@echo off
title Guardian - OpenCode Demo
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open-opencode-demo.ps1"
if errorlevel 1 (
  echo.
  echo Startup failed. Keep the message above for troubleshooting.
  pause
)
