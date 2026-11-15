# Installs Studio Vision AI from the portable zip for the current user (no admin, no Python needed).
# Run "Install.cmd" next to this file. Each person's data stays in their own %APPDATA%\StudioVisionAI.
$ErrorActionPreference = "Stop"
$AppName = "Studio Vision AI"
$Version = "3.0.0"
$Src  = Join-Path $PSScriptRoot "app"
$Dest = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
if (-not (Test-Path (Join-Path $Src "$AppName.exe"))) { throw "Unzip the whole folder first, then run Install.cmd." }

Get-Process -Name $AppName -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 600
New-Item -ItemType Directory -Force $Dest | Out-Null
robocopy $Src $Dest /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "copy failed (robocopy $LASTEXITCODE)" }
Copy-Item (Join-Path $PSScriptRoot "uninstall.ps1") (Join-Path $Dest "uninstall.ps1") -Force
Get-ChildItem $Dest -Recurse -File | Unblock-File   # files from a downloaded zip carry a "came from the internet" mark
$Exe  = Join-Path $Dest "$AppName.exe"
$Icon = Join-Path $Dest "_internal\assets\app.ico"
if (-not (Test-Path $Icon)) { $Icon = $Exe }

$sh = New-Object -ComObject WScript.Shell
foreach ($lnk in @((Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk"),
                   (Join-Path ([Environment]::GetFolderPath("Programs")) "$AppName.lnk"))) {
    $s = $sh.CreateShortcut($lnk)
    $s.TargetPath = $Exe
    $s.WorkingDirectory = $Dest
    $s.IconLocation = "$Icon,0"
    $s.Description = "Voice, interpreter, QR, logo & card studio"
    $s.Save()
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
Write-Host "Installed $AppName $Version. Open it from the Desktop or Start menu." -ForegroundColor Green
Start-Process $Exe
