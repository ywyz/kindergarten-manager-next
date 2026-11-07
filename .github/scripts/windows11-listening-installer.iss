; Unsigned per-user one-to-one-listening Windows 11 x64 test installer.
; This is not a signed production release and does not migrate, delete or
; replace any existing teacher data/deployment.

#ifndef MyPackageDir
  #define MyPackageDir "..\..\build\desktop-e14-win11-r01\package\KGNext-E14"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "."
#endif
#ifndef MyOutputBaseFilename
  #define MyOutputBaseFilename "KGNext-Listening-Win11-x64-Setup"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef MyBuildId
  #define MyBuildId "unknown"
#endif

[Setup]
AppId={{6F2B8E7A-5C4D-4A3E-9B1F-7D2C8A6E4F10}
AppName=Kindergarten Manager 一对一倾听测试版
AppVersion={#MyAppVersion}
AppVerName=Kindergarten Manager 一对一倾听测试版 {#MyAppVersion}
AppPublisher=Kindergarten Manager
AppComments=Unsigned test build {#MyBuildId}
DefaultDirName={localappdata}\Programs\KindergartenManagerListeningTest
DefaultGroupName=Kindergarten Manager 一对一倾听测试版
DisableDirPage=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=no
OutputDir={#MyOutputDir}
OutputBaseFilename={#MyOutputBaseFilename}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
MinVersion=10.0
RestartApplications=no
CloseApplications=no
UninstallDisplayIcon={app}\KGNext-E14.exe
UninstallDisplayName=Kindergarten Manager 一对一倾听测试版
SignedUninstaller=no

[Files]
Source: "{#MyPackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Kindergarten Manager 一对一倾听测试版\一对一倾听测试版"; Filename: "{app}\KGNext-E14.exe"; WorkingDir: "{app}"; Parameters: "--data ""{localappdata}\KindergartenManagerListeningTest\data"" --credential-root ""{localappdata}\KindergartenManagerListeningTest\credentials"""
