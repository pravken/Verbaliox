; Verbaliox-Setup.exe: the program files and the launcher in one installer (Inno Setup 6).
; Built by the release workflow (.github/workflows/release.yml) from the same folder as the zip:
;   ISCC.exe /DAppVersion=0.7.0-beta.6 /DNumericVersion=0.7.0 /DSourceDir=<full path>\dist\Verbaliox-v0.7.0-beta.6 /DOutputDir=<full path> installer\verbaliox.iss
; Installed for the current user (no administrator rights), into %LOCALAPPDATA%\Programs\Verbaliox:
; the program updates itself there and creates .venv and models next to itself. The first start opens
; the setup window of Verbaliox.exe, which downloads the program environment.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef NumericVersion
  #define NumericVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\Verbaliox"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{6F2C1B8E-4E7A-4C3B-9A51-7D0E2B5C9F14}
AppName=Verbaliox
AppVersion={#AppVersion}
AppVerName=Verbaliox {#AppVersion}
VersionInfoVersion={#NumericVersion}
AppPublisher=pravken
AppPublisherURL=https://github.com/pravken/Verbaliox
AppSupportURL=https://github.com/pravken/Verbaliox/issues
AppUpdatesURL=https://github.com/pravken/Verbaliox/releases
; Only for the current user: the program updates itself and writes .venv and models next to itself,
; which a Program Files install (administrator) would not allow
PrivilegesRequired=lowest
DefaultDirName={userpf}\Verbaliox
DefaultGroupName=Verbaliox
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=Verbaliox-Setup-v{#AppVersion}
SetupIconFile={#SourceDir}\assets\icon.ico
UninstallDisplayIcon={app}\Verbaliox.exe
UninstallDisplayName=Verbaliox
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The program files are replaced by the program's own updates: an old file the new version no longer has
; is removed by the updater, not here
CloseApplications=yes
; The running window (run.py makes this mutex): setup and uninstall ask to close it first
AppMutex=Local\Verbaliox.Desktop.Window
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ru.DesktopIcon=Значок на рабочем столе
en.DesktopIcon=Desktop icon
ru.RunAfter=Запустить Verbaliox (дальше программа предложит установить свои компоненты)
en.RunAfter=Start Verbaliox (it then offers to install its components)
ru.RemoveData=Удалить также записи, настройки и скачанные модели?%n%nЗаписи и база: %1%nМодели: %2%n%nНажмите «Нет», чтобы оставить их (например, для новой установки).
en.RemoveData=Also remove the recordings, the settings and the downloaded models?%n%nRecordings and database: %1%nModels: %2%n%nPress No to keep them (for example, for a new install).

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Verbaliox"; Filename: "{app}\Verbaliox.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Verbaliox"; Filename: "{app}\Verbaliox.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Verbaliox.exe"; Description: "{cm:RunAfter}"; Flags: nowait postinstall skipifsilent

[Registry]
; "Start with Windows" (app/autostart.py) is removed with the program; nothing is written at install
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Verbaliox"; Flags: uninsdeletevalue dontcreatekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "VerbaScribe"; Flags: uninsdeletevalue dontcreatekey

[UninstallDelete]
; What the program made next to itself: the environment, caches, the dubbing environment, the launcher
; it built. The models and the user data are asked about (below)
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\.venv-dub"
Type: filesandordirs; Name: "{app}\.venv-new"
Type: filesandordirs; Name: "{app}\.venv-old"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\static"
Type: filesandordirs; Name: "{app}\assets"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
var
  RemoveUserData: Boolean;

function InitializeUninstall(): Boolean;
var
  DataDir, ModelsDir: String;
begin
  DataDir := ExpandConstant('{localappdata}\Verbaliox');
  ModelsDir := ExpandConstant('{app}\models');
  RemoveUserData := False;
  if (not UninstallSilent) and (DirExists(DataDir) or DirExists(ModelsDir)) then
    RemoveUserData := MsgBox(FmtMessage(CustomMessage('RemoveData'), [DataDir, ModelsDir]),
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and RemoveUserData then
  begin
    DelTree(ExpandConstant('{app}\models'), True, True, True);
    DelTree(ExpandConstant('{localappdata}\Verbaliox'), True, True, True);
    RemoveDir(ExpandConstant('{app}'));
  end;
end;
