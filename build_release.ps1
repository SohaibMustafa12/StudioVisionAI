# Builds Studio Vision AI into files you can share with other people / PCs (nothing from your own data is included):
#   release\StudioVisionAI-Setup-<ver>.exe    a normal installer (only if Inno Setup 6 is installed: jrsoftware.org)
#   release\StudioVisionAI-<ver>-portable.zip unzip, double-click Install.cmd (always made)
#   powershell -ExecutionPolicy Bypass -File build_release.ps1
$ErrorActionPreference = "Stop"
$Root    = $PSScriptRoot
$Version = "3.0.0"
$Out     = Join-Path $Root "release"
$Stage   = Join-Path $env:LOCALAPPDATA "StudioVisionAI\release-stage"

Write-Host "== 1/3  Building" -ForegroundColor Cyan
$Built = & (Join-Path $Root "tools\build_exe.ps1") | Select-Object -Last 1
New-Item -ItemType Directory -Force $Out | Out-Null

Write-Host "== 2/3  Portable zip" -ForegroundColor Cyan
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Force $Stage | Out-Null
robocopy $Built (Join-Path $Stage "app") /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "copy failed (robocopy $LASTEXITCODE)" }
foreach ($f in @("installer\Install.cmd", "installer\install.ps1", "uninstall.ps1")) {
    Copy-Item (Join-Path $Root $f) $Stage -Force
}
$Zip = Join-Path $Out "StudioVisionAI-$Version-portable.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip -CompressionLevel Optimal
Remove-Item $Stage -Recurse -Force

Write-Host "== 3/3  Setup.exe" -ForegroundColor Cyan
$Iscc = @((Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source,
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { $_ -and (Test-Path $_) } |
        Select-Object -First 1
if ($Iscc) {
    & $Iscc /Q "/DSourceDir=$Built" "/DOutDir=$Out" (Join-Path $Root "installer\StudioVision.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
} else {
    Write-Host "   Skipped: install Inno Setup 6 (free, jrsoftware.org) to also get a Setup.exe." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Share these from $Out" -ForegroundColor Green
Get-ChildItem $Out | ForEach-Object { Write-Host ("  {0}  ({1} MB)" -f $_.Name, [math]::Round($_.Length / 1MB)) }
