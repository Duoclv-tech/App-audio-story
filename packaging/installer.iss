; Inno Setup script for TruyenFull Processor
; Build: iscc packaging\installer.iss   (run AFTER pyinstaller produces dist\TruyenFullProcessor)
; Produces: packaging\Output\TruyenFullProcessor-Setup.exe

#define AppName "TruyenFull Processor"
#define AppVersion "1.0.0"
#define AppPublisher "TruyenFull Processor"
#define AppExeName "TruyenFullProcessor.exe"

[Setup]
AppId={{8F3A2C10-4E6B-4C2A-9E7D-TRUYENFULL01}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\TruyenFullProcessor
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Install per-machine (needs admin) so Program Files is used; data lives in %LOCALAPPDATA%.
PrivilegesRequired=admin
OutputDir=Output
OutputBaseFilename=TruyenFullProcessor-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; The entire PyInstaller onedir output.
Source: "..\dist\TruyenFullProcessor\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
{ ---- WebView2 Runtime bootstrap ---------------------------------------- }
{ pywebview uses the Edge WebView2 runtime. Windows 11 ships it; older Win10 }
{ may not. Detect via the Evergreen registry key and install if missing.    }

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
    // Downloads into {tmp}\<FileName>; raises on failure.
    DownloadTemporaryFile('https://go.microsoft.com/fwlink/p/?LinkId=2124703',
      'MicrosoftEdgeWebview2Setup.exe', '', nil);
    if FileExists(TmpFile) then
      Exec(TmpFile, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  except
    // Best-effort: if the download/run fails, the app shows its own message.
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
        // Ignore — app shows its own message if the runtime is missing.
      end;
    end;
  end;
end;
