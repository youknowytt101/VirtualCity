[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$BindAddress = "127.0.0.1",
    [switch]$Restart,
    [switch]$Open
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VisualizationsDir = Join-Path $Root "reports\visualizations"
$ViewerFile = Join-Path $VisualizationsDir "svg_live_viewer.html"
$Url = "http://${BindAddress}:$Port/svg_live_viewer.html"
$ApiUrl = "http://${BindAddress}:$Port/api/status"
$PidFile = Join-Path $VisualizationsDir ".laneforge_viewer.pid"
$StdoutLog = Join-Path $VisualizationsDir "laneforge_viewer_server.out.log"
$StderrLog = Join-Path $VisualizationsDir "laneforge_viewer_server.err.log"

function Get-PortListeners {
    param([int]$Port)
    @(Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" } |
        Sort-Object OwningProcess -Unique)
}

function Test-LaneForgeReady {
    param([string]$ApiUrl)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $ApiUrl -TimeoutSec 3
        if ([int]$response.StatusCode -ne 200) {
            return $false
        }
        $payload = $response.Content | ConvertFrom-Json
        return $payload.status -eq "ok" -and $payload.system -eq "LaneForge"
    }
    catch {
        return $false
    }
}

function Stop-PortListeners {
    param([int]$Port)
    $listeners = Get-PortListeners -Port $Port
    foreach ($listener in $listeners) {
        $processId = [int]$listener.OwningProcess
        if ($processId -le 0) {
            continue
        }
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            continue
        }
        Write-Output "Stopping listener on port ${Port}: PID $processId ($($process.ProcessName))"
        Stop-Process -Id $processId -Force
    }
}

if (-not (Test-Path -LiteralPath $ViewerFile)) {
    throw "Missing viewer file: $ViewerFile"
}

if ($Restart) {
    Stop-PortListeners -Port $Port
    Start-Sleep -Milliseconds 500
}

if (Test-LaneForgeReady -ApiUrl $ApiUrl) {
    $listeners = Get-PortListeners -Port $Port
    $pids = ($listeners | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique) -join ", "
    Write-Output "LaneForge viewer is already running."
    Write-Output "URL: $Url"
    Write-Output "API: $ApiUrl"
    if ($pids) {
        Write-Output "PID(s): $pids"
    }
    if ($Open) {
        Start-Process $Url
    }
    exit 0
}

$existingListeners = Get-PortListeners -Port $Port
if ($existingListeners.Count -gt 0) {
    Write-Error "Port $Port is occupied, but LaneForge API is not reachable at $ApiUrl. Run with -Restart or choose another -Port."
    exit 2
}

$serverScript = Join-Path $Root "scripts\laneforge_viewer_server.py"
$serverArgs = @($serverScript, "--host", $BindAddress, "--port", "$Port")
$process = Start-Process `
    -FilePath "python" `
    -ArgumentList $serverArgs `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $StdoutLog `
    -RedirectStandardError $StderrLog `
    -PassThru

$deadline = (Get-Date).AddSeconds(12)
while ((Get-Date) -lt $deadline) {
    if (Test-LaneForgeReady -ApiUrl $ApiUrl) {
        Set-Content -LiteralPath $PidFile -Value "$($process.Id)" -Encoding ASCII
        Write-Output "LaneForge viewer is ready."
        Write-Output "URL: $Url"
        Write-Output "API: $ApiUrl"
        Write-Output "PID: $($process.Id)"
        Write-Output "Root: $Root"
        if ($Open) {
            Start-Process $Url
        }
        exit 0
    }

    $process.Refresh()
    if ($process.HasExited) {
        break
    }
    Start-Sleep -Milliseconds 250
}

Write-Error "LaneForge viewer did not become ready at $ApiUrl."
if (Test-Path -LiteralPath $StderrLog) {
    $stderr = Get-Content -Raw -LiteralPath $StderrLog
    if ($stderr.Trim()) {
        Write-Error $stderr
    }
}
exit 1
