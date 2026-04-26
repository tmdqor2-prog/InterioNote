; ========================================
;  InterioNote — Inno Setup 6 인스톨러 스크립트
;  Build: make_installer.bat 더블클릭 → Output\InterioNoteSetup.exe
;  Phase 7B-2
; ========================================

#define MyAppName       "InterioNote"
#define MyAppVersion    "2.3.0"
#define MyAppPublisher  "InterioNote"
#define MyAppURL        "https://github.com/tmdqor2-prog/InterioNote"
#define MyAppExeName    "InterioNote.exe"

[Setup]
; AppId 는 한 번 정한 뒤 절대 바꾸지 마세요. 같은 ID 여야 다음 버전이 "업그레이드"로 인식됩니다.
AppId={{4F2A8B7C-9D31-4E5C-A6F8-1C0B7D9E4A52}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

OutputDir=Output
OutputBaseFilename=InterioNoteSetup-{#MyAppVersion}
; lzma2/max + 단일 스레드 — RAM 부족 회피 (~2GB dist 압축에 안전)
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=1
LZMAUseSeparateProcess=yes

WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

; 설치 도중 사용자가 [뒤로] / [다음] 으로 자유롭게 이동
DisableDirPage=no
DisableReadyPage=no
DisableFinishedPage=no
ShowLanguageDialog=auto

; 사용자 데이터(%APPDATA%\InterioNote, %LOCALAPPDATA%\InterioNote)는
; 인스톨러가 절대 건드리지 않음 — 업데이트/제거 시에도 보존됨

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
korean.AppDescription=InterioNote 는 인테리어 상담을 실시간으로 녹음·전사하고 AI 가 요약해 주는 완전 로컬 데스크톱 앱입니다.%n외부 서버 전송 없이 이 PC 에서만 처리됩니다.%n%n계속하려면 [다음]을 클릭하세요.
english.AppDescription=InterioNote records and transcribes interior design consultations on this PC, with AI summary, fully offline.%n%nClick [Next] to continue.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; PyInstaller 가 만든 dist\InterioNote 폴더 전체를 설치 폴더로 복사
Source: "dist\InterioNote\InterioNote.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\InterioNote\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; WorkingDir: "{app}"

[Run]
; 설치 마지막 페이지에 "지금 실행" 옵션 (체크박스, 기본 체크됨)
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure InitializeWizard();
begin
  // 환영 페이지 본문에 앱 설명 표시
  WizardForm.WelcomeLabel2.Caption :=
    'InterioNote 버전 ' + '{#MyAppVersion}' + ' 설치를 시작합니다.' + #13#10 + #13#10 +
    ExpandConstant('{cm:AppDescription}') + #13#10 + #13#10 +
    '⚠ 이미 설치된 버전이 있다면 자동으로 덮어씌워지며,' + #13#10 +
    '   사용자 데이터(고객 폴더, 녹음 파일, 설정)는 그대로 유지됩니다.';
end;
