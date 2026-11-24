@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\maintenance.ps1" -Action report
set "GUARDIAN_RESULT=%ERRORLEVEL%"
pause
exit /b %GUARDIAN_RESULT%
