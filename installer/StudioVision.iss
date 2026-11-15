; Inno Setup recipe for a shareable Setup.exe. build_release.ps1 compiles it when Inno Setup 6 is installed:
;   ISCC.exe /DSourceDir=<built app folder> /DOutDir=<release folder> StudioVision.iss
; Installs per user (no admin). Each person's history, voice profiles and settings live in their own
; %APPDATA%\StudioVisionAI + HKCU\Software\StudioVisionAI, are never bundled, and are kept on uninstall.

#define AppName "Studio Vision AI"
#define AppVersion "3.0.0"
#define AppExe "Studio Vision AI.exe"
#define AppUserModelId "StudioVisionAI.App.3"

[Setup]
AppId={{06A9A960-5854-4D1C-807E-94EA4BD98D9A}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Studio Vision
AppComments=Voice, interpreter, QR, logo & card studio
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=StudioVisionAI-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; a fresh copy of the app files on upgrade (user data is elsewhere and untouched)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelId}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelId}"; Tasks: desktopicon

[Registry]
; "Start with Windows" entry the app may have created
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "StudioVisionAI"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im ""{#AppExe}"""; Flags: runhidden; RunOnceId: "StopApp"
