; main.py stores user data in %LOCALAPPDATA%\Cerastilo. Uninstall keeps it.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8E3B2C4A-6F1D-4B7E-9A25-C3D41F0E7B19}
AppName=Cerastilo
AppVersion={#AppVersion}
AppPublisher=Cerastilo
AppPublisherURL=https://github.com/pioner14/Cerastilo
DefaultDirName={autopf}\Cerastilo
DefaultGroupName=Cerastilo
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SourceDir=..\..
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\cerastilo.exe
UninstallDisplayName=Cerastilo
LicenseFile=LICENSE
OutputDir=dist
OutputBaseFilename=Cerastilo-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "dist\cerastilo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Cerastilo"; Filename: "{app}\cerastilo.exe"
Name: "{autodesktop}\Cerastilo"; Filename: "{app}\cerastilo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\cerastilo.exe"; Description: "{cm:LaunchProgram,Cerastilo}"; Flags: nowait postinstall skipifsilent
