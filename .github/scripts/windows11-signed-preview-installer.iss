; Signed per-user Windows 11 x64 preview installer.
; AppSource/UpdaterSource/OutputDir/AppVersion/NumericVersion/BuildId are
; injected with /D... by build-windows11-signed-preview-installer.ps1.
; Signed build: pass /Scertum="<SignTool command containing $f>"; the signed
; branch declares SignTool=certum before SignedUninstaller=yes. Inno 6.7.3
; otherwise enters manual uninstaller signing and exits non-zero.
; Syntax-only build: pass /DUnsignedSyntaxCheck=1 with private placeholders.
; This script has no [Run] entry and never starts the application.

#ifndef AppSource
  #error AppSource is required (pass /DAppSource=<verified app directory>)
#endif
#ifndef UpdaterSource
  #error UpdaterSource is required (pass /DUpdaterSource=<verified updater directory>)
#endif
#ifndef OutputDir
  #error OutputDir is required (pass /DOutputDir=<absolute output directory>)
#endif
#ifndef AppVersion
  #error AppVersion is required (pass /DAppVersion=<explicit display version>)
#endif
#ifndef NumericVersion
  #error NumericVersion is required (pass /DNumericVersion=<major.minor.patch.build>)
#endif
#ifndef BuildId
  #error BuildId is required (pass /DBuildId=<opaque build id>)
#endif

#define AppExeName "KindergartenManager.exe"

[Setup]
AppId={{FD74C3C8-0EEB-4C88-9E7D-3F3042CFF823}
AppName=幼儿园信息管理系统（签名预览）
AppVersion={#AppVersion}
AppVerName=幼儿园信息管理系统（签名预览） {#AppVersion} ({#BuildId})
AppPublisher=Kindergarten Manager
AppComments=Windows 11 x64 signed preview; build {#BuildId}
DefaultDirName={localappdata}\Programs\KindergartenManagerSignedPreview
DefaultGroupName=幼儿园信息管理系统
DisableDirPage=no
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
DirExistsWarning=auto
OutputDir={#OutputDir}
OutputBaseFilename=KGNext-Win11-x64-Preview-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
RestartApplications=no
CloseApplications=no
UninstallDisplayIcon={app}\app\{#AppExeName}
UninstallDisplayName=幼儿园信息管理系统（签名预览）
Uninstallable=yes
CreateUninstallRegKey=yes
VersionInfoVersion={#NumericVersion}
VersionInfoProductVersion={#NumericVersion}
VersionInfoTextVersion={#AppVersion} ({#BuildId})
VersionInfoProductName=幼儿园信息管理系统（签名预览）
VersionInfoDescription=幼儿园信息管理系统签名预览 {#BuildId}
VersionInfoOriginalFileName=KGNext-Win11-x64-Preview-Setup.exe
VersionInfoCompany=Kindergarten Manager
; The signed branch must declare SignTool before SignedUninstaller.
#ifdef UnsignedSyntaxCheck
SignedUninstaller=no
#else
SignTool=certum
SignedUninstaller=yes
#endif

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
; Two explicitly verified inputs: application payload and updater payload
; (including the release-prepared trust JSON). No private key is accepted.
Source: "{#AppSource}\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#UpdaterSource}\*"; DestDir: "{app}\updater"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; New shortcuts point at the canonical payload and preserve signed-preview
; business and credential roots.
Name: "{userprograms}\幼儿园信息管理系统\幼儿园信息管理系统"; Filename: "{app}\app\{#AppExeName}"; WorkingDir: "{app}\app"; Parameters: "--data ""{localappdata}\KindergartenManagerSignedPreview\data"" --credential-root ""{localappdata}\KindergartenManagerSignedPreview\credentials"""
Name: "{userdesktop}\幼儿园信息管理系统"; Filename: "{app}\app\{#AppExeName}"; WorkingDir: "{app}\app"; Parameters: "--data ""{localappdata}\KindergartenManagerSignedPreview\data"" --credential-root ""{localappdata}\KindergartenManagerSignedPreview\credentials"""; Tasks: desktopicon

[InstallDelete]
; Remove only the previously verified Start Menu shortcut. Never delete the
; old KGNext-E14.exe, app/, updater/, or any business/credential data.
Type: files; Name: "{userprograms}\KindergartenManager Signed Preview\KindergartenManager Signed Preview.lnk"

[Code]
function WithTrailingSlash(Value: String): String;
begin
  Result := Lowercase(Value);
  if Copy(Result, Length(Result), 1) <> '\' then
    Result := Result + '\';
end;

function SameOrNested(Left, Right: String): Boolean;
var
  LeftPath, RightPath: String;
begin
  LeftPath := WithTrailingSlash(Left);
  RightPath := WithTrailingSlash(Right);
  Result := (LeftPath = RightPath)
    or (Pos(LeftPath, RightPath) = 1)
    or (Pos(RightPath, LeftPath) = 1);
end;

function AppRootConflicts(AppDir: String): Boolean;
var
  DataDir, CredentialDir: String;
begin
  DataDir := ExpandConstant('{localappdata}\KindergartenManagerSignedPreview\data');
  CredentialDir := ExpandConstant('{localappdata}\KindergartenManagerSignedPreview\credentials');
  Result := SameOrNested(AppDir, DataDir) or SameOrNested(AppDir, CredentialDir);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    if AppRootConflicts(WizardDirValue) then
    begin
      MsgBox('程序安装目录不能与业务数据或凭据目录相同或相互包含。请选择其他安装位置；本安装器不会移动或覆盖现有业务数据。', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  NeedsRestart := False;
  Result := '';
  if AppRootConflicts(ExpandConstant('{app}')) then
    Result := '程序安装目录不能与业务数据或凭据目录相同或相互包含。请返回安装位置页面重新选择。';
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  { Never silently close a running old or new application. The teacher must
    save and exit first; no business or credential data is touched here. }
  if (FindWindowByWindowName('幼儿园信息管理系统') <> 0)
    or (FindWindowByWindowName('KindergartenManager Signed Preview') <> 0)
    or (FindWindowByWindowName('KindergartenManager') <> 0) then
  begin
    MsgBox('检测到幼儿园信息管理系统正在运行。请先保存并退出程序，再重新运行安装器；安装器不会自动关闭程序，也不会删除业务数据或凭据。', mbError, MB_OK);
    Result := False;
  end;
end;
