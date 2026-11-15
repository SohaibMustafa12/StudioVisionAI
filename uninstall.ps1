# Removes Studio Vision AI (app files, shortcuts, start-up entry). Your history and voice profiles in
# %APPDATA%\StudioVisionAI are kept — delete that folder yourself if you want them gone too.
$AppName = "Studio Vision AI"
$Dest = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
Get-Process -Name $AppName -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 600
foreach ($lnk in @((Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk"),
                   (Join-Path ([Environment]::GetFolderPath("Programs")) "$AppName.lnk"))) {
    if (Test-Path $lnk) { Remove-Item $lnk -Force }
}
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "StudioVisionAI" -ErrorAction SilentlyContinue
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\StudioVisionAI" -Recurse -ErrorAction SilentlyContinue
# the script lives inside the folder it deletes, so finish from a detached shell
Start-Process cmd.exe -ArgumentList "/c timeout /t 2 >nul & rmdir /s /q `"$Dest`"" -WindowStyle Hidden
Write-Host "$AppName removed. (History & voice profiles kept in $env:APPDATA\StudioVisionAI)"
