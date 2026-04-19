; Inno Setup script for Cove Universal Converter (Windows)
; Invoked from build.ps1 via:
;   iscc /DAppVersion=X.Y.Z /DSourceDir=<abs dist\cove-universal-converter> \
;        /DOutputDir=<abs release> /DIconFile=<abs cove_icon.ico> installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\cove-universal-converter"
#endif
#ifndef OutputDir
  #define OutputDir "..\release"
#endif
#ifndef IconFile
  #define IconFile "..\cove_icon.ico"
#endif

[Setup]
AppId={{B3E4D290-5AF7-4A58-9D10-3E45F8C2A701}
AppName=Cove Universal Converter
AppVersion={#AppVersion}
AppPublisher=Cove
AppPublisherURL=https://github.com/Sin213/cove-universal-converter
AppSupportURL=https://github.com/Sin213/cove-universal-converter/issues
AppUpdatesURL=https://github.com/Sin213/cove-universal-converter/releases
DefaultDirName={autopf}\Cove Universal Converter
DefaultGroupName=Cove Universal Converter
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\cove-universal-converter.exe
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=cove-universal-converter-{#AppVersion}-Setup
SetupIconFile={#IconFile}
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Cove Universal Converter"; Filename: "{app}\cove-universal-converter.exe"
Name: "{group}\Uninstall Cove Universal Converter"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Cove Universal Converter"; Filename: "{app}\cove-universal-converter.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\cove-universal-converter.exe"; Description: "Launch Cove Universal Converter"; Flags: nowait postinstall skipifsilent
