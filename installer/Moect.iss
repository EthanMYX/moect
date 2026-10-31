; Build with installer/build.ps1 after python build.py.
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{7BD858AA-F92D-42B1-8460-78BE91A66316}
AppName=Moect
AppVersion={#AppVersion}
AppPublisher=Moect
AppPublisherURL=https://github.com/mofan6/Moect
AppSupportURL=https://github.com/mofan6/Moect/issues
AppUpdatesURL=https://github.com/mofan6/Moect/releases
DefaultDirName={localappdata}\Programs\Moect
DefaultGroupName=Moect
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputBaseFilename=Moect-{#AppVersion}-Setup-x64
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\Moect.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=no
DisableStartupPrompt=yes
ShowLanguageDialog=no
UsePreviousAppDir=yes
CloseApplications=yes
CloseApplicationsFilter=Moect.exe
RestartApplications=no
SetupMutex=MoectInstaller-7BD858AA-F92D-42B1-8460-78BE91A66316
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Moect
VersionInfoDescription=Moect 安装程序

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Messages]
ReadyLabel1=点击“安装”，即可在这台电脑上使用 Moect。
ReadyLabel2a=将为当前用户安装软件，并创建桌面和开始菜单入口。已有的配置、聊天快照和导出记录会保留。
FinishedLabel=Moect 已安装完成。

[Files]
Source: "..\dist\Moect\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\修复说明.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build-support\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{userdesktop}\Moect"; Filename: "{app}\Moect.exe"; WorkingDir: "{app}"
Name: "{userprograms}\Moect"; Filename: "{app}\Moect.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\Moect.exe"; Description: "启动 Moect"; Flags: nowait postinstall skipifsilent

[Code]
function RuntimeIn(Root: Integer): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(Root,
    'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
    'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

function HasWebView2: Boolean;
begin
  Result := RuntimeIn(HKCU) or RuntimeIn(HKLM32) or RuntimeIn(HKLM64);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
begin
  Result := '';
  if HasWebView2 then Exit;
  WizardForm.StatusLabel.Caption := '正在准备 Microsoft Edge WebView2 运行环境…';
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'),
      '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    Result := '无法启动 WebView2 安装程序。请安装 Microsoft Edge WebView2 Runtime 后重试。'
  else if not HasWebView2 then
    Result := 'WebView2 尚未安装成功。首次安装此运行环境需要联网，请检查网络后重试。';
end;
