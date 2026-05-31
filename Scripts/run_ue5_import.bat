@echo off
setlocal
REM VirtualCity - 一键启动 UE5 并导入 FBX
REM 首次运行会编译 Shader，需要等待较长时间（5~15 分钟）

set "UE5_CMD=C:\Program Files\Epic Games\UE_5.6\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT=%%~fI"
set "PROJECT=%ROOT%\UE5\VirtualCityUE\VirtualCityUE.uproject"
set "SCRIPT=%ROOT%\Scripts\ue5_import_fbx.py"

echo [VirtualCity] 正在启动 UE5 并导入 FBX...
echo 首次运行需要编译 Shader，请耐心等待...
echo.

"%UE5_CMD%" "%PROJECT%" -run=pythonscript -script="%SCRIPT%" -unattended -nopause -nosplash -nullrhi

if errorlevel 1 (
    echo.
    echo [错误] 导入失败，错误码: %ERRORLEVEL%
    echo 请检查 UE5 日志：%%APPDATA%%\Unreal Engine\
    pause
    exit /b 1
)

echo.
echo [完成] FBX 已导入到 /Game/City/
pause
