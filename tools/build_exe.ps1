# Shared build step: makes the standalone app folder with PyInstaller and prints its path on the last line.
# Used by build_and_install.ps1 (this PC) and build_release.ps1 (files to share).
$ErrorActionPreference = "Stop"
$Root    = Split-Path $PSScriptRoot -Parent
$AppName = "Studio Vision AI"
$Work    = Join-Path $env:LOCALAPPDATA "StudioVisionAI"
$Venv    = Join-Path $Work "build-venv"
$Py      = Join-Path $Venv "Scripts\python.exe"

Write-Host "== Build environment" -ForegroundColor Cyan
if (-not (Test-Path $Py)) { python -m venv $Venv }
& $Py -m pip install -q --upgrade pip
& $Py -m pip install -q -r (Join-Path $Root "requirements.txt") pyinstaller pywin32
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "== App icon" -ForegroundColor Cyan
& $Py (Join-Path $Root "tools\make_icon.py")

Write-Host "== Building the .exe (takes a minute or two)" -ForegroundColor Cyan
Push-Location $Root
& $Py -m PyInstaller --noconfirm --clean --log-level WARN `
    --distpath (Join-Path $Work "dist") --workpath (Join-Path $Work "build") (Join-Path $Root "StudioVision.spec")
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { throw "PyInstaller failed" }
Join-Path $Work "dist\$AppName"
