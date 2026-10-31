#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define ProjectRoot SourcePath + ".."

[Setup]
AppId={code:SetupAppId}
AppName=DayNest
AppVersion={#AppVersion}
AppVerName=DayNest {#AppVersion}
AppPublisher=DayNest contributors
DefaultDirName={localappdata}\Programs\DayNest
DefaultGroupName=DayNest
DisableProgramGroupPage=yes
UsePreviousLanguage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\DayNest.exe
SetupIconFile={#ProjectRoot}\assets\DayNest.ico
OutputDir={#ProjectRoot}\release
OutputBaseFilename=DayNest-{#AppVersion}-Setup-win-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex={code:SetupMutex}
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#ProjectRoot}\dist\DayNest\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{code:ShortcutName}"; Filename: "{app}\DayNest.exe"; AppUserModelID: "DayNest.Desktop"
Name: "{autoprograms}\{code:ShortcutName} - 恢复普通窗口"; Filename: "{app}\DayNest.exe"; Parameters: "--restore-window"; AppUserModelID: "DayNest.Desktop"
Name: "{autodesktop}\{code:ShortcutName}"; Filename: "{app}\DayNest.exe"; Tasks: desktopicon; AppUserModelID: "DayNest.Desktop"

[Run]
Filename: "{app}\DayNest.exe"; Description: "{cm:LaunchProgram,DayNest}"; Flags: nowait postinstall skipifsilent

[Code]
function IsTestInstall: Boolean;
begin
  Result := ExpandConstant('{param:TESTINSTALL|0}') = '1';
end;

function SetupAppId(Param: String): String;
begin
  if IsTestInstall then
    Result := 'DayNest.PackagingTest'
  else
    Result := '{A144735D-0709-4A25-B44B-E5752E025F3E}';
end;

function ShortcutName(Param: String): String;
begin
  if IsTestInstall then
    Result := 'DayNest Packaging Test'
  else
    Result := 'DayNest';
end;

function SetupMutex(Param: String): String;
begin
  if IsTestInstall then
    Result := 'Local\DayNest.PackagingTest'
  else
    Result := 'Local\DayNest.SingleInstance';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  StartupValue, AppExe: String;
begin
  if (CurUninstallStep = usPostUninstall) and
     RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DayNest', StartupValue) then
  begin
    AppExe := ExpandConstant('{app}\DayNest.exe');
    if (CompareText(Trim(StartupValue), AppExe) = 0) or
       (CompareText(Trim(StartupValue), '"' + AppExe + '"') = 0) then
      RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DayNest');
  end;
end;
