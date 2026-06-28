param(
    [int]$Port = 8765,
    [int]$StartupTimeoutSec = 25
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Scripts = Join-Path $Root "Scripts"
$Url = "http://127.0.0.1:$Port/"
$HealthUrl = "http://127.0.0.1:$Port/health"
$LogDir = Join-Path $Scripts "logs"
$LogPath = Join-Path $LogDir "worldbuilder_console_launcher.log"

function Write-LauncherLog {
    param([string]$Message)
    if (-not (Test-Path -LiteralPath $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $LogPath -Value "[$stamp] $Message" -Encoding UTF8
}

function Test-AreaPickerReady {
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 2
        return ($resp.StatusCode -eq 200)
    }
    catch {
        return $false
    }
}

function Wait-AreaPickerReady {
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-AreaPickerReady) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Start-AreaPickerHost {
    $uv = (Get-Command "uv.exe" -ErrorAction Stop).Source
    $cacheDir = Join-Path $Scripts ".uv-cache"
    # desktop.py 用 pywebview 开原生窗口、同进程内嵌服务，关窗口即整体退出；
    # 不再需要 SHUTDOWN_WITH_PAGE 心跳，也不再开浏览器（窗口由 desktop.py 自己弹出）。
    # 直接以隐藏窗口启动 uv（不经 cmd /c），控制台不再露面；uv run 仍确保 .venv 同步。
    $uvArgs = @("--cache-dir", $cacheDir, "run", "python", "-u", "desktop.py")
    $proc = Start-Process -FilePath $uv -ArgumentList $uvArgs -WorkingDirectory $Scripts -WindowStyle Hidden -PassThru
    Write-LauncherLog "Started area_picker host pid=$($proc.Id)."
}

try {
    Write-LauncherLog "Launching WorldBuilder console."
    # Always enter the Python host once: it decides whether the current server
    # version can be reused or an older process must be replaced.
    Start-AreaPickerHost

    if (-not (Wait-AreaPickerReady)) {
        throw "WorldBuilder console did not become ready within $StartupTimeoutSec seconds."
    }

    Write-LauncherLog "WorldBuilder console ready: $Url (native window opened by desktop.py)"
    exit 0
}
catch {
    Write-LauncherLog "ERROR: $($_.Exception.Message)"
    Write-Host ""
    Write-Host "WorldBuilder console failed to open."
    Write-Host $_.Exception.Message
    Write-Host "Log: $LogPath"
    Write-Host ""
    Write-Host "Press any key to close this window."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}
