; Verbaliox-Installer.exe: the program files and the launcher in one installer (Inno Setup 6).
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
; The same id in app/autostart.py (UNINSTALL_KEY): the program keeps the version shown in "Installed apps"
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
; The folder page is shown on every install, an update too: it says where Verbaliox is installed, and
; another folder moves the program there with its environment and models ([Code] below)
DisableDirPage=no
; OLLAMA_MODELS may point into the program folder (app/ollama_client.py): its change is announced
ChangesEnvironment=yes
DefaultGroupName=Verbaliox
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=Verbaliox-Installer-v{#AppVersion}
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
ru.AlreadyInstalled=Verbaliox уже установлен в папке:%n%1%n%nНажмите «Далее», чтобы обновить его там. Другая папка: программа переедет туда вместе со средой Python и моделями.
en.AlreadyInstalled=Verbaliox is already installed in:%n%1%n%nPress Next to update it there. Another folder: the program moves there with its Python environment and models.
ru.Moving=Перенос среды Python и моделей в новую папку…
en.Moving=Moving the Python environment and the models to the new folder…
ru.RemoveOld=Verbaliox перенесён в %1.%n%nУдалить старую папку %2? В ней остались только файлы прежней установки.
en.RemoveOld=Verbaliox has moved to %1.%n%nRemove the old folder %2? Only the files of the previous install are left there.

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
Type: filesandordirs; Name: "{app}\.uv-cache"
Type: filesandordirs; Name: "{app}\python"

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6F2C1B8E-4E7A-4C3B-9A51-7D0E2B5C9F14}_is1';

var
  RemoveUserData: Boolean;
  OldAppDir: String;  // where an earlier install is ('' for none)
  Moved: Boolean;

function InitializeSetup(): Boolean;
begin
  OldAppDir := '';
  if RegQueryStringValue(HKCU, UninstallKey, 'Inno Setup: App Path', OldAppDir) then
    if not FileExists(AddBackslash(OldAppDir) + 'Verbaliox.exe') then
      OldAppDir := '';
  Result := True;
end;

procedure InitializeWizard();
begin
  if OldAppDir <> '' then
    WizardForm.SelectDirBrowseLabel.Caption := FmtMessage(CustomMessage('AlreadyInstalled'), [OldAppDir]);
end;

function Norm(Dir: String): String;
begin
  Result := Lowercase(AddBackslash(Dir));
end;

// The new folder is another one, and neither holds the other (moving into itself would loop)
function MovesElsewhere(): Boolean;
var
  OldD, NewD: String;
begin
  OldD := Norm(OldAppDir);
  NewD := Norm(ExpandConstant('{app}'));
  Result := (OldAppDir <> '') and (OldD <> NewD) and (Pos(OldD, NewD) <> 1) and (Pos(NewD, OldD) <> 1);
end;

// A folder the program made next to itself goes to the new place: renamed on the same disk, else moved
// by robocopy. Never over a folder of the same name that is already there
procedure MoveHeavy(Name: String);
var
  Src, Dst: String;
  Code: Integer;
begin
  Src := AddBackslash(OldAppDir) + Name;
  Dst := ExpandConstant('{app}\') + Name;
  if (not DirExists(Src)) or DirExists(Dst) then
    Exit;
  ForceDirectories(ExpandConstant('{app}'));
  if not RenameFile(Src, Dst) then
    Exec(ExpandConstant('{sys}\robocopy.exe'), '"' + Src + '" "' + Dst + '" /E /MOVE /NFL /NDL /NJH /NJS /NP',
      '', SW_HIDE, ewWaitUntilTerminated, Code);
  Moved := True;
end;

// pyvenv.cfg names the Python the environment was made from: a Python in the old folder (the one uv
// installs next to the program) is now in the new one. The case of the path may differ
procedure FixVenv(Name: String);
var
  Cfg, S, Done, OldD, OldL, NewD: String;
  Text: AnsiString;
  P: Integer;
begin
  Cfg := ExpandConstant('{app}\') + Name + '\pyvenv.cfg';
  if not LoadStringFromFile(Cfg, Text) then
    Exit;
  S := String(Text);
  OldD := RemoveBackslash(OldAppDir);
  OldL := Lowercase(OldD);
  NewD := RemoveBackslash(ExpandConstant('{app}'));
  Done := '';
  P := Pos(OldL, Lowercase(S));
  while P > 0 do
  begin
    Done := Done + Copy(S, 1, P - 1) + NewD;
    S := Copy(S, P + Length(OldD), Length(S));
    P := Pos(OldL, Lowercase(S));
  end;
  SaveStringToFile(Cfg, AnsiString(Done + S), False);
end;

// OLLAMA_MODELS set by the program into its folder follows the move
procedure FixOllamaModels();
var
  V: String;
begin
  if RegQueryStringValue(HKCU, 'Environment', 'OLLAMA_MODELS', V) and (Pos(Norm(OldAppDir), Norm(V)) = 1) then
    RegWriteStringValue(HKCU, 'Environment', 'OLLAMA_MODELS',
      RemoveBackslash(ExpandConstant('{app}')) + Copy(V, Length(RemoveBackslash(OldAppDir)) + 1, Length(V)));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssInstall) and MovesElsewhere() then
  begin
    WizardForm.StatusLabel.Caption := CustomMessage('Moving');
    MoveHeavy('.venv');
    MoveHeavy('.venv-dub');
    MoveHeavy('models');
    MoveHeavy('python');
  end;
  if (CurStep = ssPostInstall) and Moved then
  begin
    FixVenv('.venv');
    FixVenv('.venv-dub');
    FixOllamaModels();
    // What is left in the old folder is the previous install; the user decides
    if (not WizardSilent) and DirExists(OldAppDir) and
       (MsgBox(FmtMessage(CustomMessage('RemoveOld'), [ExpandConstant('{app}'), OldAppDir]),
               mbConfirmation, MB_YESNO) = IDYES) then
      DelTree(OldAppDir, True, True, True);
  end;
end;

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
var
  V: String;
begin
  if (CurUninstallStep = usPostUninstall) and RemoveUserData then
  begin
    DelTree(ExpandConstant('{app}\models'), True, True, True);
    // The folder of Ollama's models the program chose was in models: the variable goes with it
    if RegQueryStringValue(HKCU, 'Environment', 'OLLAMA_MODELS', V) and (Pos(Norm(ExpandConstant('{app}')), Norm(V)) = 1) then
      RegDeleteValue(HKCU, 'Environment', 'OLLAMA_MODELS');
    DelTree(ExpandConstant('{localappdata}\Verbaliox'), True, True, True);
    RemoveDir(ExpandConstant('{app}'));
  end;
end;
