[CmdletBinding()]
param(
    [int]$AreaPickerPort = 8765,
    [string]$BindAddress = "127.0.0.1",
    [int]$StartupTimeoutSec = 25,
    [switch]$NoStart,
    [switch]$NoOpen,
    [switch]$StopUnknownPortOwners
)

$ErrorActionPreference = "Stop"

$Scripts = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Scripts
$AreaPickerUrl = "http://${BindAddress}:$AreaPickerPort/"
$AreaPickerHealthUrl = "http://${BindAddress}:$AreaPickerPort/health"
$AreaPickerShutdownUrl = "http://${BindAddress}:$AreaPickerPort/shutdown"

function Write-ResetStep {
    param([string]$Message)
    Write-Output "[VirtualCity reset] $Message"
}

function Get-JsonEndpoint {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        if ([int]$response.StatusCode -ne 200) {
            return $null
        }
        return $response.Content | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Test-AreaPickerReady {
    $payload = Get-JsonEndpoint -Url $AreaPickerHealthUrl
    return $null -ne $payload -and $payload.app -eq "VirtualCity area_picker"
}

function Get-PortListeners {
    param([int]$Port)
    @(Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" } |
        Sort-Object OwningProcess -Unique)
}

function Get-ProcessCommandLine {
    param([int]$ProcessId)
    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
        return [string]$proc.CommandLine
    }
    catch {
        return ""
    }
}

function Test-VirtualCityServerProcess {
    param(
        [System.Diagnostics.Process]$Process,
        [string]$CommandLine
    )
    $path = [string]$Process.Path
    return (
        $CommandLine -match "area_picker\.py" -or
        $CommandLine -match [regex]::Escape($Root) -or
        ($path -and $path.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase))
    )
}

function Stop-PortListeners {
    param(
        [int]$Port,
        [string]$Label
    )
    $listeners = Get-PortListeners -Port $Port
    if ($listeners.Count -eq 0) {
        Write-ResetStep "$Label port $Port is already free."
        return
    }

    foreach ($listener in $listeners) {
        $processId = [int]$listener.OwningProcess
        if ($processId -le 0) {
            continue
        }
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            continue
        }
        $commandLine = Get-ProcessCommandLine -ProcessId $processId
        $isVirtualCity = Test-VirtualCityServerProcess -Process $process -CommandLine $commandLine
        if (-not $isVirtualCity -and -not $StopUnknownPortOwners) {
            Write-Warning "$Label port $Port is owned by unknown PID $processId ($($process.ProcessName)); not stopping it. Re-run with -StopUnknownPortOwners if this is expected."
            continue
        }
        if (-not $isVirtualCity) {
            Write-Warning "$Label port $Port is owned by unknown PID $processId ($($process.ProcessName)); stopping because -StopUnknownPortOwners was requested."
        }
        else {
            Write-ResetStep "Stopping $Label listener on port ${Port}: PID $processId ($($process.ProcessName))."
        }
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

function Wait-PortFree {
    param(
        [int]$Port,
        [int]$TimeoutMs = 5000
    )
    $deadline = (Get-Date).AddMilliseconds($TimeoutMs)
    while ((Get-Date) -lt $deadline) {
        if ((Get-PortListeners -Port $Port).Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds 200
    }
    return (Get-PortListeners -Port $Port).Count -eq 0
}

function Request-AreaPickerShutdown {
    if (-not (Test-AreaPickerReady)) {
        return
    }
    Write-ResetStep "Requesting graceful shutdown for area_picker on port $AreaPickerPort."
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $AreaPickerShutdownUrl -Method Post -Body "{}" -ContentType "application/json" -TimeoutSec 2 | Out-Null
    }
    catch {
        Write-Warning "Graceful area_picker shutdown request failed: $($_.Exception.Message)"
    }
    Start-Sleep -Milliseconds 900
}

function Start-AreaPickerLauncher {
    $launcher = Join-Path $Root "启动VirtualCity操作台.cmd"
    if (-not (Test-Path -LiteralPath $launcher)) {
        throw "Missing launcher: $launcher"
    }
    Write-ResetStep "Starting VirtualCity main console."
    $proc = Start-Process -FilePath $launcher -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    Write-ResetStep "Launcher PID: $($proc.Id)"
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

Write-ResetStep "Resetting local web servers only. Data, caches, Houdini, and UE are not touched."
Write-ResetStep "AreaPicker: $AreaPickerUrl"

Request-AreaPickerShutdown

Stop-PortListeners -Port $AreaPickerPort -Label "area_picker"

$areaFree = Wait-PortFree -Port $AreaPickerPort
if (-not $areaFree) {
    throw "Could not release area_picker port. area_picker_free=$areaFree"
}

if ($NoStart) {
    Write-ResetStep "Reset complete. Main console restart was skipped by -NoStart."
    exit 0
}

Start-AreaPickerLauncher
if (Wait-AreaPickerReady) {
    Write-ResetStep "Main console is ready: $AreaPickerUrl"
    if (-not $NoOpen) {
        Write-ResetStep "The main launcher will open the browser automatically."
    }
    exit 0
}

throw "Main console did not become ready within $StartupTimeoutSec seconds. Check the new VirtualCity console window."
