@echo off
title Guardian Dashboard
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open-dashboard.ps1"
if errorlevel 1 pause
