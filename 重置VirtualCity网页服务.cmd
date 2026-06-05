@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Scripts\reset_virtualcity_servers.ps1"
if errorlevel 1 (
  echo.
  echo VirtualCity web server reset failed. Press any key to close this window.
  pause >nul
)
endlocal
