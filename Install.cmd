@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
  echo.
  echo Guardian setup did not finish. Read the error above, then run Install.cmd again.
  pause
  exit /b 1
)
endlocal
