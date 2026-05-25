@echo off
REM VirtualCity - 一键下载 Google Open Buildings 高度数据
REM 双击运行，或从命令行执行
REM
REM 首次运行会自动打开浏览器进行一次性 Google 账号授权
REM 后续运行无需再次登录（凭据缓存在本地）

cd /d F:\VirtualCity

echo [VirtualCity] 正在下载建筑高度数据...
uv run --with earthengine-api --index-url https://mirrors.aliyun.com/pypi/simple/ ^
    python Scripts/download_building_heights.py %*

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [完成] 数据已更新至 RawData\Overture\
) else (
    echo.
    echo [错误] 下载失败，请检查网络或重新授权：
    echo   run_download_heights.bat --reauth
)
pause
