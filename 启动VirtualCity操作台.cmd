@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Scripts\launch_virtualcity_console.ps1"
if errorlevel 1 (
  echo.
  echo VirtualCity console launch failed. Press any key to close this window.
  pause >nul
)
endlocal
