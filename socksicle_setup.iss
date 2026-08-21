[Setup]
AppName=Socksicle
AppVersion=1.5
WizardStyle=modern dynamic
DefaultDirName={autopf}\Socksicle
DefaultGroupName=Socksicle
Compression=lzma2
SolidCompression=yes
OutputDir=.\
DisableWelcomePage=no

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Code]

var
  EnginePage: TInputOptionWizardPage;
  PythonPage: TWizardPage;
  VersionPage: TWizardPage;
  DownloadPage: TDownloadWizardPage;
  PipPage: TOutputProgressWizardPage;
  ShortcutPage: TWizardPage;

  PythonStatusLabel: TNewStaticText;
  PythonHelpLabel: TNewStaticText;
  DownloadPyButton: TNewButton;
  DirectDownloadPyButton: TNewButton;
  RecheckPyButton: TNewButton;

  StatusLabel: TNewStaticText;
  EngineVersionLabel: TNewStaticText;
  SocksicleVersionLabel: TNewStaticText;

  ShortcutStatusLabel: TNewStaticText;
  MakeShortcutButton: TNewButton;

  DetectedPythonExe: String;
  SelectedEngine: String;
  EngineRepo: String;
  EngineVersion: String;
  SocksicleVersion: String;
  EngineDownloadUrl: String;
  SocksicleDownloadUrl: String;

  PipInstallDone: Boolean;


function HttpGet(const Url: String): String;
var
  Http: Variant;
begin
  Result := '';
  try
    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.Open('GET', Url, False);
    Http.SetRequestHeader('User-Agent', 'Socksicle-Installer');
    Http.SetRequestHeader('Accept', 'application/vnd.github+json');
    Http.Send;
    if Http.Status = 200 then
      Result := Http.ResponseText;
  except
    Result := '';
  end;
end;


function GetJsonTag(const Json: String): String;
var
  P: Integer;
  StartPos: Integer;
  EndPos: Integer;
begin
  Result := '';
  P := Pos('"tag_name"', Json);
  if P = 0 then Exit;

  P := P + Length('"tag_name"');
  while (P <= Length(Json)) and (Json[P] <> ':') do P := P + 1;
  if P > Length(Json) then Exit;

  P := P + 1;
  while (P <= Length(Json)) and ((Json[P] = ' ') or (Json[P] = #9) or (Json[P] = '"')) do P := P + 1;

  StartPos := P;
  while (P <= Length(Json)) and (Json[P] <> '"') do P := P + 1;
  EndPos := P;

  if EndPos > StartPos then
    Result := Copy(Json, StartPos, EndPos - StartPos);
end;


function GetLatestVersion(const Repo: String): String;
var
  Json: String;
begin
  Result := '';
  Json := HttpGet('https://api.github.com/repos/' + Repo + '/releases/latest');
  if Json = '' then Exit;
  Result := GetJsonTag(Json);
end;


function ParsePythonVersion(const RawVer: String; var OutMajor, OutMinor: Integer): Boolean;
var
  S, VerStr: String;
  P, P2: Integer;
begin
  Result := False;
  OutMajor := 0;
  OutMinor := 0;
  S := Trim(RawVer);
  if Pos('Python ', S) = 1 then
    VerStr := Trim(Copy(S, 8, Length(S)))
  else
    VerStr := S;

  P := Pos('.', VerStr);
  if P > 0 then
  begin
    OutMajor := StrToIntDef(Copy(VerStr, 1, P - 1), 0);
    VerStr := Copy(VerStr, P + 1, Length(VerStr));
    P2 := Pos('.', VerStr);
    if P2 > 0 then
      OutMinor := StrToIntDef(Copy(VerStr, 1, P2 - 1), 0)
    else
      OutMinor := StrToIntDef(VerStr, 0);

    if (OutMajor > 3) or ((OutMajor = 3) and (OutMinor >= 10)) then
      Result := True;
  end;
end;


function TestPythonExe(const ExePath: String; var OutVersion: String): Boolean;
var
  TmpFile: String;
  Cmd: String;
  ResultCode: Integer;
  Lines: TArrayOfString;
  Major, Minor: Integer;
begin
  Result := False;
  OutVersion := '';
  TmpFile := ExpandConstant('{tmp}\pyver.txt');
  DeleteFile(TmpFile);

  Cmd := '/C """' + ExePath + '"" --version > """' + TmpFile + '""" 2>&1"';
  if Exec(ExpandConstant('{cmd}'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if FileExists(TmpFile) and LoadStringsFromFile(TmpFile, Lines) and (GetArrayLength(Lines) > 0) then
    begin
      if ParsePythonVersion(Lines[0], Major, Minor) then
      begin
        OutVersion := IntToStr(Major) + '.' + IntToStr(Minor);
        Result := True;
      end;
    end;
  end;
  DeleteFile(TmpFile);
end;


function CheckRegistryPython(RootKey: Integer; const BaseKey: String; var OutExe, OutVersion: String): Boolean;
var
  SubKeys: TArrayOfString;
  I, Major, Minor: Integer;
  KeyName, RegPath, InstallPath, Candidate: String;
begin
  Result := False;
  if RegGetSubkeyNames(RootKey, BaseKey, SubKeys) then
  begin
    for I := GetArrayLength(SubKeys) - 1 downto 0 do
    begin
      KeyName := SubKeys[I];
      if ParsePythonVersion(KeyName, Major, Minor) then
      begin
        RegPath := BaseKey + '\' + KeyName + '\InstallPath';

        if RegQueryStringValue(RootKey, RegPath, 'ExecutablePath', InstallPath) and FileExists(InstallPath) then
        begin
          OutExe := InstallPath;
          OutVersion := IntToStr(Major) + '.' + IntToStr(Minor);
          Result := True;
          Exit;
        end;

        if RegQueryStringValue(RootKey, RegPath, '', InstallPath) then
        begin
          Candidate := AddBackslash(InstallPath) + 'python.exe';
          if FileExists(Candidate) then
          begin
            OutExe := Candidate;
            OutVersion := IntToStr(Major) + '.' + IntToStr(Minor);
            Result := True;
            Exit;
          end;
        end;
      end;
    end;
  end;
end;


function CheckKnownPaths(var OutExe, OutVersion: String): Boolean;
var
  I: Integer;
  Candidate: String;
begin
  Result := False;
  for I := 14 downto 10 do
  begin
    Candidate := ExpandConstant('{localappdata}\Programs\Python\Python3' + IntToStr(I) + '\python.exe');
    if FileExists(Candidate) then
    begin
      OutExe := Candidate;
      OutVersion := '3.' + IntToStr(I);
      Result := True;
      Exit;
    end;
  end;

  for I := 14 downto 10 do
  begin
    Candidate := ExpandConstant('{autopf}\Python3' + IntToStr(I) + '\python.exe');
    if FileExists(Candidate) then
    begin
      OutExe := Candidate;
      OutVersion := '3.' + IntToStr(I);
      Result := True;
      Exit;
    end;
  end;
end;


function FindAndVerifyPython(var OutExe: String; var OutVersion: String): Boolean;
begin
  Result := False;
  OutExe := 'python';
  OutVersion := '';

  if CheckRegistryPython(HKCU, 'Software\Python\PythonCore', OutExe, OutVersion) then
  begin
    Result := True;
    Exit;
  end;

  if CheckRegistryPython(HKLM, 'Software\Python\PythonCore', OutExe, OutVersion) then
  begin
    Result := True;
    Exit;
  end;

  if CheckKnownPaths(OutExe, OutVersion) then
  begin
    Result := True;
    Exit;
  end;

  if TestPythonExe('python', OutVersion) then
  begin
    OutExe := 'python';
    Result := True;
    Exit;
  end;

  if TestPythonExe('py', OutVersion) then
  begin
    OutExe := 'py';
    Result := True;
    Exit;
  end;
end;


function CleanVersion(const Ver: String): String;
begin
  Result := Ver;
  if (Length(Result) > 0) and (Result[1] = 'v') then
    Delete(Result, 1, 1);
end;


procedure BuildEngineDownloadUrl;
var
  VerNoV: String;
begin
  VerNoV := CleanVersion(EngineVersion);

  case SelectedEngine of
    'xray':
      EngineDownloadUrl := 'https://github.com/XTLS/Xray-core/releases/download/' + EngineVersion + '/Xray-windows-64.zip';

    'sing-box':
      EngineDownloadUrl := 'https://github.com/SagerNet/sing-box/releases/download/' + EngineVersion + '/sing-box-' + VerNoV + '-windows-amd64.zip';

    'sslocal':
      EngineDownloadUrl := 'https://github.com/shadowsocks/shadowsocks-rust/releases/download/' + EngineVersion + '/shadowsocks-' + EngineVersion + '.x86_64-pc-windows-msvc.zip';
  end;
end;


procedure BuildSocksicleDownloadUrl;
begin
  if SocksicleVersion <> '' then
    SocksicleDownloadUrl := 'https://github.com/iwtsyddd/Socksicle/archive/refs/tags/' + SocksicleVersion + '.zip'
  else
    SocksicleDownloadUrl := 'https://github.com/iwtsyddd/Socksicle/archive/refs/heads/main.zip';
end;


procedure CheckPythonStatus;
var
  PyVer: String;
begin
  WizardForm.NextButton.Enabled := False;

  if FindAndVerifyPython(DetectedPythonExe, PyVer) then
  begin
    PythonStatusLabel.Caption := 'Python ' + PyVer + ' detected (' + DetectedPythonExe + ').';
    PythonHelpLabel.Caption :=
      'Compatible Python environment found. You can now click Next to continue the installation.';
    WizardForm.NextButton.Enabled := True;
  end
  else
  begin
    PythonStatusLabel.Caption := 'Python is not installed or not found on this computer.';
    PythonHelpLabel.Caption :=
      'Socksicle requires Python 3.10 or higher.'#13#10 +
      'Click "Download Python 3.12 (64-bit)" below to download the official installer.'#13#10 +
      'IMPORTANT: Make sure to check the box "Add Python to PATH" during Python installation!'#13#10#13#10 +
      'Once installed, click "Re-check Python" to continue.';
    WizardForm.NextButton.Enabled := False;
  end;
end;


procedure DownloadPythonPageClick(Sender: TObject);
var
  ErrorCode: Integer;
begin
  ShellExec('open', 'https://www.python.org/downloads/', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;


procedure DirectDownloadPythonClick(Sender: TObject);
var
  ErrorCode: Integer;
begin
  ShellExec('open', 'https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;


procedure RecheckPythonClick(Sender: TObject);
begin
  CheckPythonStatus;
end;


procedure CreatePythonPage;
begin
  PythonPage := CreateCustomPage(
    EnginePage.ID,
    'Python Environment Check',
    'Checking for Python 3.10+ installation...'
  );

  PythonStatusLabel := TNewStaticText.Create(PythonPage);
  PythonStatusLabel.Parent := PythonPage.Surface;
  PythonStatusLabel.Left := ScaleX(0);
  PythonStatusLabel.Top := ScaleY(10);
  PythonStatusLabel.Width := PythonPage.SurfaceWidth;
  PythonStatusLabel.Height := ScaleY(24);
  PythonStatusLabel.Font.Style := [fsBold];
  PythonStatusLabel.Caption := 'Checking Python installation...';

  PythonHelpLabel := TNewStaticText.Create(PythonPage);
  PythonHelpLabel.Parent := PythonPage.Surface;
  PythonHelpLabel.Left := ScaleX(0);
  PythonHelpLabel.Top := ScaleY(40);
  PythonHelpLabel.Width := PythonPage.SurfaceWidth;
  PythonHelpLabel.Height := ScaleY(75);
  PythonHelpLabel.AutoSize := False;
  PythonHelpLabel.WordWrap := True;
  PythonHelpLabel.Caption :=
    'Socksicle requires Python 3.10 or higher.'#13#10 +
    'If Python is not installed, click one of the download buttons below to install it.'#13#10 +
    'IMPORTANT: Check the box "Add Python to PATH" during installation!'#13#10#13#10 +
    'After installing Python, click "Re-check Python" to proceed.';

  DirectDownloadPyButton := TNewButton.Create(PythonPage);
  DirectDownloadPyButton.Parent := PythonPage.Surface;
  DirectDownloadPyButton.Left := ScaleX(0);
  DirectDownloadPyButton.Top := ScaleY(125);
  DirectDownloadPyButton.Width := ScaleX(200);
  DirectDownloadPyButton.Height := ScaleY(26);
  DirectDownloadPyButton.Caption := 'Download Python 3.12 (64-bit)';
  DirectDownloadPyButton.OnClick := @DirectDownloadPythonClick;

  DownloadPyButton := TNewButton.Create(PythonPage);
  DownloadPyButton.Parent := PythonPage.Surface;
  DownloadPyButton.Left := ScaleX(210);
  DownloadPyButton.Top := ScaleY(125);
  DownloadPyButton.Width := ScaleX(180);
  DownloadPyButton.Height := ScaleY(26);
  DownloadPyButton.Caption := 'Python Downloads Page';
  DownloadPyButton.OnClick := @DownloadPythonPageClick;

  RecheckPyButton := TNewButton.Create(PythonPage);
  RecheckPyButton.Parent := PythonPage.Surface;
  RecheckPyButton.Left := ScaleX(0);
  RecheckPyButton.Top := ScaleY(160);
  RecheckPyButton.Width := ScaleX(150);
  RecheckPyButton.Height := ScaleY(26);
  RecheckPyButton.Caption := 'Re-check Python';
  RecheckPyButton.OnClick := @RecheckPythonClick;
end;


procedure CreateVersionPage;
begin
  VersionPage := CreateCustomPage(
    PythonPage.ID,
    'Checking for Updates',
    'Checking the latest versions from GitHub...'
  );

  StatusLabel := TNewStaticText.Create(VersionPage);
  StatusLabel.Parent := VersionPage.Surface;
  StatusLabel.Left := ScaleX(0);
  StatusLabel.Top := ScaleY(20);
  StatusLabel.Width := VersionPage.SurfaceWidth;
  StatusLabel.Height := ScaleY(25);
  StatusLabel.Caption := 'Checking connection to GitHub...';

  EngineVersionLabel := TNewStaticText.Create(VersionPage);
  EngineVersionLabel.Parent := VersionPage.Surface;
  EngineVersionLabel.Left := ScaleX(0);
  EngineVersionLabel.Top := ScaleY(65);
  EngineVersionLabel.Width := VersionPage.SurfaceWidth;
  EngineVersionLabel.Height := ScaleY(25);
  EngineVersionLabel.Caption := 'Engine: Checking...';

  SocksicleVersionLabel := TNewStaticText.Create(VersionPage);
  SocksicleVersionLabel.Parent := VersionPage.Surface;
  SocksicleVersionLabel.Left := ScaleX(0);
  SocksicleVersionLabel.Top := ScaleY(95);
  SocksicleVersionLabel.Width := VersionPage.SurfaceWidth;
  SocksicleVersionLabel.Height := ScaleY(25);
  SocksicleVersionLabel.Caption := 'Socksicle: Checking...';
end;


procedure MakeShortcutButtonClick(Sender: TObject);
var
  IconPath: String;
  ExePath: String;
  Params: String;
  WorkDir: String;
  PythonDir: String;
begin
  if Pos('.exe', LowerCase(DetectedPythonExe)) > 0 then
  begin
    PythonDir := ExtractFileDir(DetectedPythonExe);
    ExePath := AddBackslash(PythonDir) + 'pythonw.exe';
    if not FileExists(ExePath) then
      ExePath := DetectedPythonExe;
  end
  else
    ExePath := 'pythonw.exe';

  Params := '"' + ExpandConstant('{app}\main.py') + '"';
  WorkDir := ExpandConstant('{app}');
  IconPath := ExpandConstant('{app}\icon.ico');

  try
    CreateShellLink(
      ExpandConstant('{autodesktop}\Socksicle.lnk'),
      'Socksicle',
      ExePath,
      Params,
      WorkDir,
      IconPath,
      0,
      SW_SHOWNORMAL
    );
    ShortcutStatusLabel.Caption := 'Shortcut created on the Desktop.';
    MakeShortcutButton.Enabled := False;
  except
    ShortcutStatusLabel.Caption := 'Failed to create shortcut: ' + GetExceptionMessage;
  end;
end;


procedure CreateShortcutPage;
begin
  ShortcutPage := CreateCustomPage(
    wpInstalling,
    'Desktop Shortcut',
    'Optionally create a shortcut for Socksicle.'
  );

  MakeShortcutButton := TNewButton.Create(ShortcutPage);
  MakeShortcutButton.Parent := ShortcutPage.Surface;
  MakeShortcutButton.Left := ScaleX(0);
  MakeShortcutButton.Top := ScaleY(20);
  MakeShortcutButton.Width := ScaleX(160);
  MakeShortcutButton.Height := ScaleY(23);
  MakeShortcutButton.Caption := 'Make a shortcut';
  MakeShortcutButton.OnClick := @MakeShortcutButtonClick;

  ShortcutStatusLabel := TNewStaticText.Create(ShortcutPage);
  ShortcutStatusLabel.Parent := ShortcutPage.Surface;
  ShortcutStatusLabel.Left := ScaleX(0);
  ShortcutStatusLabel.Top := ScaleY(55);
  ShortcutStatusLabel.Width := ShortcutPage.SurfaceWidth;
  ShortcutStatusLabel.Height := ScaleY(40);
  ShortcutStatusLabel.Caption := 'Click the button above to add a Socksicle icon to your Desktop. This step is optional — you can just click Next to skip it.';
  ShortcutStatusLabel.AutoSize := False;
  ShortcutStatusLabel.WordWrap := True;
end;


procedure InitializeWizard;
begin
  WizardForm.WelcomeLabel1.Caption :=
    'Welcome to Socksicle Setup';

  WizardForm.WelcomeLabel2.Caption :=
    'Socksicle is a multi-protocol proxy client for Windows and Linux.'#13#10#13#10 +
    'Click Next to continue.';

  EnginePage := CreateInputOptionPage(
    wpWelcome,
    'Choose Proxy Engine',
    'Select the proxy engine you want to use.',
    'Choose one of the available engines:',
    True,
    False
  );

  EnginePage.Add('Xray-core');
  EnginePage.Add('sing-box');
  EnginePage.Add('sslocal (shadowsocks-rust)');

  EnginePage.SelectedValueIndex := 0;

  CreatePythonPage;

  CreateVersionPage;

  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), nil);

  PipPage := CreateOutputProgressPage('Installing Dependencies', 'Please wait while pip installs Socksicle dependencies...');

  CreateShortcutPage;
end;


procedure CheckVersions;
begin
  WizardForm.NextButton.Enabled := False;

  EngineVersion := '';
  SocksicleVersion := '';

  case EnginePage.SelectedValueIndex of
    0:
      begin
        SelectedEngine := 'xray';
        EngineRepo := 'XTLS/Xray-core';
      end;
    1:
      begin
        SelectedEngine := 'sing-box';
        EngineRepo := 'SagerNet/sing-box';
      end;
    2:
      begin
        SelectedEngine := 'sslocal';
        EngineRepo := 'shadowsocks/shadowsocks-rust';
      end;
  end;

  StatusLabel.Caption := 'Checking ' + SelectedEngine + '...';
  EngineVersion := GetLatestVersion(EngineRepo);

  if EngineVersion <> '' then
    EngineVersionLabel.Caption := SelectedEngine + ': ' + EngineVersion
  else
    EngineVersionLabel.Caption := SelectedEngine + ': Unable to check version';

  StatusLabel.Caption := 'Checking Socksicle...';
  SocksicleVersion := GetLatestVersion('iwtsyddd/Socksicle');

  if SocksicleVersion <> '' then
    SocksicleVersionLabel.Caption := 'Socksicle: ' + SocksicleVersion
  else
    SocksicleVersionLabel.Caption := 'Socksicle: latest (branch: main)';

  if EngineVersion <> '' then
  begin
    BuildEngineDownloadUrl;
    BuildSocksicleDownloadUrl;
    StatusLabel.Caption := 'Connection successful.';
    WizardForm.NextButton.Enabled := True;
  end
  else
  begin
    StatusLabel.Caption := 'Unable to connect to GitHub.';
    WizardForm.NextButton.Enabled := False;
  end;
end;


procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = PythonPage.ID then
    CheckPythonStatus;

  if CurPageID = VersionPage.ID then
    CheckVersions;
end;


function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  if CurPageID = EnginePage.ID then
  begin
    case EnginePage.SelectedValueIndex of
      0: SelectedEngine := 'xray';
      1: SelectedEngine := 'sing-box';
      2: SelectedEngine := 'sslocal';
    end;
  end;

  if CurPageID = wpReady then
  begin
    DownloadPage.Clear;
    DownloadPage.Add(SocksicleDownloadUrl, 'socksicle.zip', '');
    DownloadPage.Add(EngineDownloadUrl, 'engine.zip', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
        Result := True;
      except
        if DownloadPage.AbortedByUser then
          Log('Download aborted by user.')
        else
          MsgBox(GetExceptionMessage, mbError, MB_OK);
        Result := False;
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;


procedure PipOutputLog(const S: String; const Error, FirstLine: Boolean);
begin
  if FirstLine then
    PipPage.SetText('Installing dependencies...', '');

  if Trim(S) <> '' then
    PipPage.SetText(S, '');
end;


function FindExtractedSocksicleDir: String;
var
  FindRec: TFindRec;
  BaseDir: String;
begin
  Result := '';
  BaseDir := ExpandConstant('{tmp}');
  if FindFirst(BaseDir + '\Socksicle-*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
        begin
          Result := BaseDir + '\' + FindRec.Name;
          Break;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;

  if Result = '' then
    Result := BaseDir + '\Socksicle-main'; 
end;


procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  TargetEngineDir: String;
  ExtractedDir: String;
  Cmd: String;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := 'Unpacking Socksicle...';
    Exec('tar.exe', ExpandConstant('-xf "{tmp}\socksicle.zip" -C "{tmp}"'), '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    ExtractedDir := FindExtractedSocksicleDir;

    Cmd := '/C xcopy /E /Y /Q "' + ExtractedDir + '\*" "' + ExpandConstant('{app}\') + '"';
    Exec(ExpandConstant('{cmd}'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    TargetEngineDir := ExpandConstant('{app}\bin\' + SelectedEngine);
    ForceDirectories(TargetEngineDir);

    WizardForm.StatusLabel.Caption := 'Unpacking proxy engine...';
    Exec('tar.exe', ExpandConstant('-xf "{tmp}\engine.zip" -C "' + TargetEngineDir + '"'), '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    WizardForm.StatusLabel.Caption := 'Installing Python dependencies...';
    PipPage.Show;
    try
      PipInstallDone := ExecAndLogOutput(
        ExpandConstant('{cmd}'),
        '/C "' + DetectedPythonExe + '" -m pip install --no-warn-script-location .',
        ExpandConstant('{app}'),
        SW_HIDE,
        ewWaitUntilTerminated,
        ResultCode,
        @PipOutputLog
      );
    finally
      PipPage.Hide;
    end;

    if (not PipInstallDone) or (ResultCode <> 0) then
      MsgBox('pip install finished with errors (exit code ' + IntToStr(ResultCode) + '). Check the log for details.', mbError, MB_OK);
  end;
end;
