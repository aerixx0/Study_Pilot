#ifndef Payload
  #error Supply the staged payload path with /DPayload=...
#endif

[Setup]
AppId={{AD54C72B-4C81-48F3-A36C-1F43145CD27E}
AppName=StudyPilot
AppVersion=0.6.6
DefaultDirName={localappdata}\Programs\StudyPilot
DefaultGroupName=StudyPilot
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputBaseFilename=StudyPilot-Windows-x64-Setup
Compression=lzma2/fast
SolidCompression=yes
ChangesEnvironment=yes
CloseApplications=no
UninstallDisplayIcon={app}\bin\studypilot.exe
WizardStyle=modern
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut / 创建桌面快捷方式"; Flags: unchecked

[Files]
Source: "{#Payload}\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs ignoreversion
Source: "{#Payload}\runtime\*"; DestDir: "{app}\runtime"; Flags: recursesubdirs ignoreversion
Source: "{#Payload}\bin\studypilot.exe"; DestDir: "{app}\bin"; Flags: ignoreversion

[Icons]
Name: "{group}\StudyPilot"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-B ""{app}\app\start_studypilot.py"" _open"; WorkingDir: "{app}\app"
Name: "{group}\停止 StudyPilot"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-B ""{app}\app\start_studypilot.py"" _stop"; WorkingDir: "{app}\app"
Name: "{group}\导入旧版 StudyPilot 数据"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-B ""{app}\app\start_studypilot.py"" _migrate"; WorkingDir: "{app}\app"
Name: "{group}\配置 StudyPilot AI"; Filename: "{app}\bin\studypilot.exe"; Parameters: "ai configure"; WorkingDir: "{app}"
Name: "{userdesktop}\StudyPilot"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-B ""{app}\app\start_studypilot.py"" _open"; WorkingDir: "{app}\app"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: "-B ""{app}\app\start_studypilot.py"" _open"; WorkingDir: "{app}\app"; Description: "Open StudyPilot / 打开 StudyPilot"; Flags: postinstall nowait skipifsilent unchecked

[Code]
const
  EnvironmentKey = 'Environment';
  InstallerKey = 'Software\StudyPilot\Installer';

function StopInstalledService(): Boolean;
var
  ExitCode: Integer;
  CLI: String;
begin
  CLI := ExpandConstant('{app}\bin\studypilot.exe');
  Result := not FileExists(CLI);
  if not Result then
    if Exec(CLI, 'stop', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      Result := ExitCode = 0;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not StopInstalledService() then
    Result := 'StudyPilot could not stop. Close StudyPilot before continuing.';
end;

function InitializeUninstall(): Boolean;
begin
  Result := StopInstalledService();
  if not Result then
    SuppressibleMsgBox('StudyPilot could not stop. Close StudyPilot and retry uninstall.',
      mbError, MB_OK, IDOK);
end;

function HasPathEntry(Value, Entry: String): Boolean;
var
  Parts: TArrayOfString;
  I: Integer;
begin
  Result := True;
  Parts := StringSplit(Value, [';'], stAll);
  for I := 0 to GetArrayLength(Parts) - 1 do
    if CompareText(Trim(Parts[I]), Entry) = 0 then
      Exit;
  Result := False;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  UserPath, BinDir: String;
begin
  if CurStep <> ssPostInstall then Exit;
  BinDir := ExpandConstant('{app}\bin');
  if not RegQueryStringValue(HKCU, EnvironmentKey, 'Path', UserPath) then UserPath := '';
  if HasPathEntry(UserPath, BinDir) then Exit;
  if UserPath <> '' then UserPath := UserPath + ';';
  if RegWriteExpandStringValue(HKCU, EnvironmentKey, 'Path', UserPath + BinDir) then
    RegWriteStringValue(HKCU, InstallerKey, 'AddedPath', BinDir)
  else
    Log('Could not add StudyPilot to the user PATH.');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserPath, BinDir, NewPath: String;
  Parts: TArrayOfString;
  I, Count: Integer;
  Removed: Boolean;
begin
  if CurUninstallStep <> usPostUninstall then Exit;
  if not RegQueryStringValue(HKCU, InstallerKey, 'AddedPath', BinDir) then Exit;
  if RegQueryStringValue(HKCU, EnvironmentKey, 'Path', UserPath) then begin
    Parts := StringSplit(UserPath, [';'], stAll);
    NewPath := '';
    Count := 0;
    Removed := False;
    for I := 0 to GetArrayLength(Parts) - 1 do begin
      if (not Removed) and (CompareText(Trim(Parts[I]), BinDir) = 0) then
        Removed := True
      else begin
        if Count > 0 then NewPath := NewPath + ';';
        NewPath := NewPath + Parts[I];
        Count := Count + 1;
      end;
    end;
    if Removed then RegWriteExpandStringValue(HKCU, EnvironmentKey, 'Path', NewPath);
  end;
  RegDeleteValue(HKCU, InstallerKey, 'AddedPath');
  RegDeleteKeyIfEmpty(HKCU, InstallerKey);
end;
