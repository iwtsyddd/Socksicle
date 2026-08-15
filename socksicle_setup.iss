[Setup]
AppName=Socksicle
AppVersion=1.3
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
  StatusLabel: TNewStaticText;
  EngineVersionLabel: TNewStaticText;
  SocksicleVersionLabel: TNewStaticText;

  ShortcutStatusLabel: TNewStaticText;
  MakeShortcutButton: TNewButton;

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


function GetPythonVersion(var OutVersion: String): Boolean;
var
  TmpFile: String;
  Cmd: String;
  ResultCode: Integer;
  Lines: TArrayOfString;
  RawVer: String;
  P, Major, Minor: Integer;
begin
  Result := False;
  OutVersion := '';
  TmpFile := ExpandConstant('{tmp}\pyver.txt');

  Cmd := '/C python --version > "' + TmpFile + '" 2>&1';
  if Exec(ExpandConstant('{cmd}'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if LoadStringsFromFile(TmpFile, Lines) and (GetArrayLength(Lines) > 0) then
    begin
      RawVer := Trim(Lines[0]);
      if Pos('Python ', RawVer) = 1 then
      begin
        OutVersion := Trim(Copy(RawVer, 8, Length(RawVer)));
        P := Pos('.', OutVersion);
        if P > 0 then
        begin
          Major := StrToIntDef(Copy(OutVersion, 1, P - 1), 0);
          RawVer := Copy(OutVersion, P + 1, Length(OutVersion));
          P := Pos('.', RawVer);
          if P > 0 then
            Minor := StrToIntDef(Copy(RawVer, 1, P - 1), 0)
          else
            Minor := StrToIntDef(RawVer, 0);

          if (Major > 3) or ((Major = 3) and (Minor >= 10)) then
            Result := True;
        end;
      end;
    end;
  end;
  DeleteFile(TmpFile);
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

  if GetPythonVersion(PyVer) then
  begin
    PythonStatusLabel.Caption := 'Python ' + PyVer + ' detected (compatible).';
    WizardForm.NextButton.Enabled := True;
  end
  else
  begin
    if PyVer <> '' then
      PythonStatusLabel.Caption := 'Found Python ' + PyVer + ', but Python 3.10+ is required.'
    else
      PythonStatusLabel.Caption := 'Python is not installed or not found in system PATH.';
    WizardForm.NextButton.Enabled := False;
  end;
end;


procedure CreatePythonPage;
begin
  PythonPage := CreateCustomPage(
    EnginePage.ID,
    'Environment Check',
    'Checking for Python 3.10+...'
  );

  PythonStatusLabel := TNewStaticText.Create(PythonPage);
  PythonStatusLabel.Parent := PythonPage.Surface;
  PythonStatusLabel.Left := ScaleX(0);
  PythonStatusLabel.Top := ScaleY(20);
  PythonStatusLabel.Width := PythonPage.SurfaceWidth;
  PythonStatusLabel.Height := ScaleY(25);

  PythonStatusLabel.Caption := 'Checking Python installation...';
end;


procedure CreateVersionPage;
begin
  VersionPage := CreateCustomPage(
    PythonPage.ID,
    'Checking for Updates',
    'Checking the latest versions...'
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
begin
  ExePath := ExpandConstant('{app}\pythonw.exe');
  if not FileExists(ExePath) then
    ExePath := 'pythonw.exe';

  Params := '"' + ExpandConstant('{app}\main.py') + '"';
  WorkDir := ExpandConstant('{app}');
  IconPath := ExpandConstant('{app}\icon.png');

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
  Output: TExecOutput;
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
        '/C python -m pip install --no-warn-script-location .',
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
