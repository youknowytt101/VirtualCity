@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Scripts\reset_worldbuilder_servers.ps1"
if errorlevel 1 (
  echo.
  echo WorldBuilder server reset failed. Press any key to close this window.
  pause >nul
)
endlocal
