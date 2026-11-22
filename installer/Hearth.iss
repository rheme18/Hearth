#define AppName "Hearth"
#define AppVersion "0.4.3"
#define AppPublisher "Hearth"
#define AppExeName "Hearth.exe"

[Setup]
AppId={{EFA63148-EFCB-4DB7-A58A-3D94143ED166}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Hearth
DefaultGroupName=Hearth
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=..\dist\installer
OutputBaseFilename=Hearth-{#AppVersion}-Setup
SetupIconFile=..\hearth.ico
WizardStyle=modern dark
DisableWelcomePage=no
WizardImageFile=assets\hearth-wizard.bmp
WizardSmallImageFile=assets\hearth-small.png
LanguageDetectionMethod=none
ShowLanguageDialog=yes
UsePreviousLanguage=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[CustomMessages]
english.LaunchHearth=Launch Hearth
turkish.LaunchHearth=Hearth'i Başlat
english.AddToHearth=Add to Hearth
turkish.AddToHearth=Hearth'a Ekle

[Registry]
Root: HKCU; Subkey: "Software\Hearth"; ValueType: string; ValueName: "Language"; ValueData: "{language}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\Hearth"; ValueType: string; ValueName: ""; ValueData: "{cm:AddToHearth}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\Hearth"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExeName}"""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\Hearth\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Flags: uninsdeletekey

Root: HKCU; Subkey: "Software\Classes\Directory\shell\Hearth"; ValueType: string; ValueName: ""; ValueData: "{cm:AddToHearth}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Hearth"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExeName}"""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Hearth\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Flags: uninsdeletekey

Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Hearth"; ValueType: string; ValueName: ""; ValueData: "{cm:AddToHearth}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Hearth"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExeName}"""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Hearth\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%V"""; Flags: uninsdeletekey

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\Hearth\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Hearth"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\Hearth"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchHearth}"; Flags: nowait postinstall skipifsilent

; User library data in LocalAppData is deliberately preserved on uninstall.

[Code]
function WebView2Present(): Boolean;
var
  Version: String;
begin
  Version := '';
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
  Result := Result and (Version <> '') and (Version <> '0.0.0.0');
end;

function InitializeSetup(): Boolean;
begin
  Result := WebView2Present();
  if not Result then
    if ActiveLanguage = 'turkish' then
      MsgBox('Hearth, Microsoft Edge WebView2 Evergreen Runtime gerektirir. Microsoft''tan yükleyip kurulumu yeniden başlatın.', mbError, MB_OK)
    else
      MsgBox('Hearth requires the Microsoft Edge WebView2 Evergreen Runtime. Install it from Microsoft, then run this setup again.', mbError, MB_OK);
end;
