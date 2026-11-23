#define AppName "小满桌面助手"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppSource
  #define AppSource "..\dist\DesktopPet"
#endif

[Setup]
AppId={{7F3C9F2A-6D1B-4C8E-9A54-2B1F0D8E7C31}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}.0
DefaultDirName={localappdata}\Programs\DesktopPet
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
MinVersion=10.0
OutputDir=.
OutputBaseFilename=DesktopPet-{#AppVersion}-setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\DesktopPet.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
AppMutex=DesktopPetSingleInstance
CloseApplications=no
RestartApplications=no
UsePreviousAppDir=yes
DisableDirPage=auto

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\DesktopPet.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\DesktopPet.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DesktopPet.exe"; Description: "启动{#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  RunValue = 'DesktopPet';

procedure CurStepChanged(CurStep: TSetupStep);
var
  existing: string;
begin
  if CurStep = ssPostInstall then
  begin
    if RegQueryStringValue(HKCU, RunKey, RunValue, existing) and
       (Pos(LowerCase(ExpandConstant('{app}\DesktopPet.exe')), LowerCase(existing)) = 0) then
      RegWriteStringValue(HKCU, RunKey, RunValue,
        '"' + ExpandConstant('{app}\DesktopPet.exe') + '" --background');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  existing: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if RegQueryStringValue(HKCU, RunKey, RunValue, existing) and
       (Pos(LowerCase(ExpandConstant('{app}\DesktopPet.exe')), LowerCase(existing)) > 0) then
      RegDeleteValue(HKCU, RunKey, RunValue);
  end;
end;
