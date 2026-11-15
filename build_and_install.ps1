# Builds Studio Vision AI into a real Windows app and installs it for the current user (no admin needed).
#   powershell -ExecutionPolicy Bypass -File build_and_install.ps1
$ErrorActionPreference = "Stop"
$Root    = $PSScriptRoot
$AppName = "Studio Vision AI"
$AppId   = "StudioVisionAI.App.3"
$Version = "3.0.0"
$Work    = Join-Path $env:LOCALAPPDATA "StudioVisionAI"
$Venv    = Join-Path $Work "build-venv"
$Py      = Join-Path $Venv "Scripts\python.exe"
$Dest    = Join-Path $env:LOCALAPPDATA "Programs\$AppName"

Write-Host "== 1/3  Building" -ForegroundColor Cyan
$Built = & (Join-Path $Root "tools\build_exe.ps1") | Select-Object -Last 1

Write-Host "== 2/3  Installing to $Dest" -ForegroundColor Cyan
Get-Process -Name $AppName -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 600
New-Item -ItemType Directory -Force $Dest | Out-Null
robocopy $Built $Dest /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "copy failed (robocopy $LASTEXITCODE)" }
Copy-Item (Join-Path $Root "uninstall.ps1") (Join-Path $Dest "uninstall.ps1") -Force
$Exe = Join-Path $Dest "$AppName.exe"

Write-Host "== 3/3  Shortcuts & Installed-apps entry" -ForegroundColor Cyan
$Desktop   = [Environment]::GetFolderPath("Desktop")
$StartMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "$AppName.lnk"
$Icon      = Join-Path $Dest "_internal\assets\app.ico"
if (-not (Test-Path $Icon)) { $Icon = $Exe }
foreach ($lnk in @((Join-Path $Desktop "$AppName.lnk"), $StartMenu)) {
    & $Py (Join-Path $Root "tools\shortcut.py") $lnk $Exe $Icon $AppId "Voice, interpreter, QR, logo & card studio"
}
$Key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\StudioVisionAI"
New-Item -Path $Key -Force | Out-Null
$size = [int]((Get-ChildItem $Dest -Recurse | Measure-Object Length -Sum).Sum / 1KB)
$props = @{
    DisplayName = $AppName; DisplayVersion = $Version; Publisher = "Studio Vision"; DisplayIcon = $Icon
    InstallLocation = $Dest; EstimatedSize = $size; NoModify = 1; NoRepair = 1
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Dest\uninstall.ps1`""
}
foreach ($k in $props.Keys) {
    $type = if ($props[$k] -is [int]) { "DWord" } else { "String" }
    New-ItemProperty -Path $Key -Name $k -Value $props[$k] -PropertyType $type -Force | Out-Null
}
Write-Host ""
Write-Host "Installed $AppName $Version  ($([math]::Round($size/1024)) MB)" -ForegroundColor Green
Write-Host "  App:        $Exe"
Write-Host "  Shortcuts:  Desktop + Start menu"
Write-Host "  Uninstall:  Settings > Apps > Installed apps > $AppName"
