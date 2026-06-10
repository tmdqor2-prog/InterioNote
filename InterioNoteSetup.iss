; ========================================
;  InterioNote — Inno Setup 6 인스톨러 스크립트
;  Phase 7B-2 v2 (2026-04-26)
;
;  변경사항 (이전 버전 대비):
;   - per-user install (Defender 우회) — %LOCALAPPDATA%\Programs\InterioNote
;   - CPU / GPU 설치 유형 선택 ([Types] + [Components])
;   - 자동 업그레이드 (같은 AppId 의 옛 버전 자동 제거 후 새 버전 설치)
;   - 언인스톨 시 사용자 데이터 삭제 옵션 (기본은 보존)
; ========================================

#define MyAppName       "InterioNote"
; v3.5.2: build-installer.bat 가 컴파일 직전에 version_for_iss.iss 를
; (e.g. `#define MyAppVersion "3.5.2"`) 자동 생성. version.json 만 올리면 됨.
#include "version_for_iss.iss"
#define MyAppPublisher  "InterioNote"
#define MyAppURL        "https://github.com/tmdqor2-prog/InterioNote"
#define MyAppExeName    "InterioNote.exe"

[Setup]
; AppId 는 절대 바꾸지 마세요. 같은 ID 여야 다음 버전이 "업그레이드" 로 인식됩니다.
AppId={{4F2A8B7C-9D31-4E5C-A6F8-1C0B7D9E4A52}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases

; ✨ Per-user install — Defender 우회 (이전 노트북에서의 막힘 해결)
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

OutputDir=Output
OutputBaseFilename=InterioNoteSetup-{#MyAppVersion}
; lzma2/max + 단일 스레드 — RAM 부족 회피 (큰 dist 압축에 안전)
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=1
LZMAUseSeparateProcess=yes

WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; ✨ 자동 업그레이드: 앱이 켜져 있어도 자동 종료시키고 새 버전 설치
CloseApplications=force
RestartApplications=no

UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

DisableDirPage=no
DisableReadyPage=no
DisableFinishedPage=no
ShowLanguageDialog=auto

; 사용자 데이터(%APPDATA%\InterioNote, %LOCALAPPDATA%\InterioNote)는
; 인스톨러가 절대 건드리지 않음 — 업데이트/제거 시 기본 보존
; (제거 시 사용자 명시 요청 시에만 함께 삭제 — [Code] 섹션 참조)

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
korean.AppDescription=InterioNote 는 인테리어 상담을 실시간으로 녹음·전사하고 AI 가 요약해 주는 완전 로컬 데스크톱 앱입니다.%n외부 서버 전송 없이 이 PC 에서만 처리됩니다.
english.AppDescription=InterioNote records and transcribes interior design consultations on this PC, with AI summary, fully offline.

; ========================================
; ✨ 설치 유형 — CPU 전용 vs GPU 사용
; 사용자가 [구성 요소 선택] 페이지에서 라디오 버튼으로 하나 선택
; ========================================
[Types]
Name: "cpu"; Description: "CPU 전용 (디스크 ~1.5GB) — 권장: NVIDIA GPU 가 없는 일반 노트북"
Name: "gpu"; Description: "GPU 사용 (디스크 ~5GB) — NVIDIA GeForce / RTX 등이 있는 PC, 더 빠른 처리"

[Components]
Name: "core"; Description: "InterioNote 본체"; Types: cpu gpu; Flags: fixed
Name: "cpu_runtime"; Description: "CPU 실행 라이브러리"; Types: cpu
Name: "gpu_runtime"; Description: "GPU 실행 라이브러리 (NVIDIA CUDA + cuDNN)"; Types: gpu

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; CPU 빌드 — dist-cpu 의 모든 파일 (cpu_runtime 선택 시만 추출)
Source: "dist-cpu\InterioNote\InterioNote.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: cpu_runtime
Source: "dist-cpu\InterioNote\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: cpu_runtime

; GPU 빌드 — dist-gpu 의 모든 파일 (gpu_runtime 선택 시만 추출)
Source: "dist-gpu\InterioNote\InterioNote.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: gpu_runtime
Source: "dist-gpu\InterioNote\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: gpu_runtime

[Icons]
; per-user 영역에 시작메뉴 / 바탕화면 단축키
Name: "{userprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userprograms}\{#MyAppName}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; WorkingDir: "{app}"

[Run]
; 설치 마지막 페이지 "지금 실행" (체크박스, 기본 체크)
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; ========================================
; [Code] — 환영 페이지 커스텀 + 언인스톨 시 사용자 데이터 옵션 삭제
; ========================================
[Code]
var
  DeleteUserData: Boolean;

procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'InterioNote 버전 ' + '{#MyAppVersion}' + ' 설치를 시작합니다.' + #13#10 + #13#10 +
    ExpandConstant('{cm:AppDescription}') + #13#10 + #13#10 +
    '✓ 이미 설치된 옛 버전이 있다면 자동으로 새 버전으로 갱신됩니다.' + #13#10 +
    '✓ 사용자 데이터(고객 폴더 · 녹음 · 요약 · DB · 설정) 는 그대로 보존됩니다.' + #13#10 + #13#10 +
    '다음 페이지에서 CPU 전용 / GPU 사용 중 하나를 선택할 수 있습니다.';
end;

function InitializeUninstall(): Boolean;
var
  Response: Integer;
begin
  Response := MsgBox(
    'InterioNote 를 제거합니다.' + #13#10 + #13#10 +
    '사용자 데이터도 함께 삭제할까요?' + #13#10 + #13#10 +
    '✓ 함께 삭제: DB · 모델 캐시 · 설정 · 임시 녹음' + #13#10 +
    '✓ 항상 보존: 고객 폴더 의 녹음·요약·이미지 (사업 자료라 자동 삭제 절대 안 함)' + #13#10 + #13#10 +
    '[예] 사용자 데이터까지 모두 삭제 (복구 불가)' + #13#10 +
    '[아니오] 사용자 데이터 보존 (앱만 제거 — 추후 재설치 시 그대로 이어서 사용 가능)',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2);
  DeleteUserData := (Response = IDYES);
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataPath, LocalAppDataPath: String;
begin
  if (CurUninstallStep = usPostUninstall) and DeleteUserData then begin
    AppDataPath := ExpandConstant('{userappdata}\InterioNote');
    LocalAppDataPath := ExpandConstant('{localappdata}\InterioNote');
    if DirExists(AppDataPath) then
      DelTree(AppDataPath, True, True, True);
    if DirExists(LocalAppDataPath) then
      DelTree(LocalAppDataPath, True, True, True);
    MsgBox(
      'InterioNote 사용자 데이터를 삭제했습니다.' + #13#10 + #13#10 +
      '✓ 삭제됨: DB · 모델 캐시 · 설정 · 임시 녹음' + #13#10 +
      '✗ 보존됨: 고객 폴더 (녹음·요약·이미지) — 직접 비즈니스 자료라 자동 삭제 안 함.' + #13#10 +
      '   고객 폴더는 본인이 수동으로 삭제하실 때만 사라집니다.',
      mbInformation, MB_OK);
  end;
end;
