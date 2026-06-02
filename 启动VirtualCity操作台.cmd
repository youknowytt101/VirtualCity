@echo off
setlocal
cd /d "%~dp0Scripts"
set "VC_AREA_PICKER_SHUTDOWN_WITH_PAGE=1"
uv --cache-dir "%~dp0Scripts\.uv-cache" run python -u area_picker.py
endlocal
