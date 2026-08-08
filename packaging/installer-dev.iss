; Inno Setup script — DEV build (nén nhanh, CHỈ để test luồng cài đặt).
; Khác installer.iss: Compression=none + SolidCompression=no => iscc chạy nhanh
; hơn nhiều, đổi lại Setup.exe to hơn. KHÔNG dùng để phát hành.
; Build: iscc packaging\installer-dev.iss   (sau khi pyinstaller xong)
; Produces: packaging\Output\AudioStory-Setup-dev.exe

#define AppName "AudioStory"
#define AppVersion "1.0.0"
#define AppPublisher "AudioStory"
#define AppExeName "AudioStory.exe"

[Setup]
AppId={{8F3A2C10-4E6B-4C2A-9E7D-TRUYENFULL01}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\AudioStory
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=Output
OutputBaseFilename=AudioStory-Setup-dev
; --- Khác biệt so với bản release: nén nhanh nhất ---
Compression=none
SolidCompression=no
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[InstallDelete]
; Remove the stale old-named exe on upgrade-in-place (rename TruyenFullProcessor -> AudioStory).
Type: files; Name: "{app}\TruyenFullProcessor.exe"

[Files]
Source: "..\dist\AudioStory\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
{ ---- WebView2 Runtime bootstrap (giống bản release) -------------------- }
function WebView2Installed(): Boolean;
var
  pv: string;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', pv) or
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', pv) or
    RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', pv);
end;

procedure InstallWebView2();
var
  TmpFile: string;
  ResultCode: Integer;
begin
  TmpFile := ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe');
  try
    DownloadTemporaryFile('https://go.microsoft.com/fwlink/p/?LinkId=2124703',
      'MicrosoftEdgeWebview2Setup.exe', '', nil);
    if FileExists(TmpFile) then
      Exec(TmpFile, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  except
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if not WebView2Installed() then
    begin
      try
        InstallWebView2();
      except
      end;
    end;
  end;
end;
