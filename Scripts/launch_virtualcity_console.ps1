param(
    [int]$Port = 8765,
    [int]$StartupTimeoutSec = 25,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Scripts = Join-Path $Root "Scripts"
$Url = "http://127.0.0.1:$Port/"
$HealthUrl = "http://127.0.0.1:$Port/health"
$LogDir = Join-Path $Scripts "logs"
$LogPath = Join-Path $LogDir "virtualcity_console_launcher.log"

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

function Open-ConsoleUrl {
    if ($NoOpen) {
        return
    }

    try {
        Start-Process -FilePath $Url
        Write-LauncherLog "Opened browser with Start-Process: $Url"
        return
    }
    catch {
        Write-LauncherLog "Start-Process URL failed: $($_.Exception.Message)"
    }

    try {
        $rundll = Join-Path $env:SystemRoot "System32\rundll32.exe"
        Start-Process -FilePath $rundll -ArgumentList @("url.dll,FileProtocolHandler", $Url)
        Write-LauncherLog "Opened browser with FileProtocolHandler: $Url"
        return
    }
    catch {
        Write-LauncherLog "FileProtocolHandler failed: $($_.Exception.Message)"
        throw "VirtualCity console is ready, but Windows could not open the browser automatically. Open $Url manually."
    }
}

function Start-AreaPickerHost {
    $uv = (Get-Command "uv.exe" -ErrorAction Stop).Source
    $cacheDir = Join-Path $Scripts ".uv-cache"
    $command = 'set "VC_AREA_PICKER_SHUTDOWN_WITH_PAGE=1" && set "VC_AREA_PICKER_NO_BROWSER=1" && cd /d "{0}" && "{1}" --cache-dir "{2}" run python -u area_picker.py' -f $Scripts, $uv, $cacheDir
    $proc = Start-Process -FilePath $env:ComSpec -ArgumentList @("/d", "/c", $command) -WorkingDirectory $Scripts -WindowStyle Minimized -PassThru
    Write-LauncherLog "Started area_picker host pid=$($proc.Id)."
}

try {
    Write-LauncherLog "Launching VirtualCity console."
    if (-not (Test-AreaPickerReady)) {
        Start-AreaPickerHost
    }
    else {
        Write-LauncherLog "Existing area_picker service is already ready."
    }

    if (-not (Wait-AreaPickerReady)) {
        throw "VirtualCity console did not become ready within $StartupTimeoutSec seconds."
    }

    Write-LauncherLog "VirtualCity console ready: $Url"
    Open-ConsoleUrl
    exit 0
}
catch {
    Write-LauncherLog "ERROR: $($_.Exception.Message)"
    Write-Host ""
    Write-Host "VirtualCity console failed to open."
    Write-Host $_.Exception.Message
    Write-Host "Log: $LogPath"
    Write-Host ""
    Write-Host "Press any key to close this window."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}
