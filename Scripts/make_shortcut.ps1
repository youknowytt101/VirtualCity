param([switch]$Desktop)

# 给 WorldBuilder 启动器生成带自定义图标的快捷方式。
# .cmd 自身无法携带图标，Windows 下正规做法是用 .lnk 指定 IconLocation。
#   powershell -ExecutionPolicy Bypass -File Scripts\make_shortcut.ps1 [-Desktop]

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$icon = Join-Path $Root "Scripts\icons\worldbuilder.ico"
$target = Join-Path $Root "启动WorldBuilder.cmd"

function New-WBShortcut([string]$Path) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($Path)
    $lnk.TargetPath = $target
    $lnk.WorkingDirectory = $Root
    $lnk.IconLocation = "$icon,0"
    $lnk.Description = "WorldBuilder"
    $lnk.WindowStyle = 7  # 启动器控制台最小化（应用窗口由 desktop.py 弹出）
    $lnk.Save()
    Write-Host "Created: $Path"
}

New-WBShortcut (Join-Path $Root "WorldBuilder.lnk")
if ($Desktop) {
    New-WBShortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) "WorldBuilder.lnk")
}
