# InterioNote 프로젝트 — Claude Code 세션 인수인계

> **다음 세션의 Claude에게**: 이 파일은 이전 Claude가 사용자와 나눈 대화의 전체 맥락입니다.
> 사용자는 처음부터 다시 설명하지 않아도 되도록, 이 파일을 먼저 끝까지 읽고 작업을 이어가 주세요.
> 마지막 섹션 **"⏭ 다음 세션에서 바로 할 것"** 부터 확인하면 재개 지점이 명확합니다.

---

## 👤 사용자 프로파일

- **직업**: 인테리어 디자이너 1인 (Livart&문테리어 소속 / 개인 사업 병행)
- **기술 수준**: 비개발자. Windows cmd 복붙 가능 수준. 코드는 읽지 못함.
- **사용 PC**: ASUS Vivobook Go 15 E1504F / AMD Ryzen 5 7520U (4코어/8스레드, Zen2) / RAM 15GB / SSD 512GB / GPU 없음 (내장 AMD Radeon) / Windows 11
- **Python 환경**: 3.12.8 설치됨. (`py -3.12` 고정 사용)
- **이메일**: tmdqor2@gmail.com
- **Ollama**: 설치 완료 + `qwen2.5:3b` 다운로드 완료 (1.9GB, Q4_K_M)
- **GitHub**: `tmdqor2-prog` 계정 + Public repo `tmdqor2-prog/InterioNote` 생성됨 (Phase 7B-3 자동 업데이트 확인용)
- **Inno Setup 6**: 설치됨. ⚠️ 비표준 경로 — `C:\Program Files\InterioNote\ISCC.exe` (사용자가 install path 를 InterioNote 로 직접 지정한 듯). `make_installer.bat` 가 이 경로를 자동 탐지함.

### 중요한 소통 규칙
1. **비개발자**이므로 모든 명령은 **cmd.exe 복붙 가능** 형태로 제공
2. **한 줄씩** 안내 (여러 줄 붙여넣기 하다 실수하는 경우가 있었음)
3. `%PROMPT%` 같은 쉘 프롬프트 표시를 복사하지 않도록 주의 안내
4. 에러 발생 시: **전체 cmd 로그 복사 + 스크린샷 요청**, 혼자 디버깅 가정 금지
5. **한글로 응답** (기본)
6. Phase 단위로 작업을 끊고 **사용자 검증** 후 다음으로
7. 긴 설명 필요할 때는 긴 답변 허용 (설치 안내/검증 체크리스트 등)
8. **솔직한 한계 인정** — 소프트웨어로 풀 수 없는 문제(예: 배경 음악)는 하드웨어 솔루션을 정직하게 안내

---

## 🎯 프로젝트 개요

### 이름
**InterioNote** — 인테리어 상담 실시간 녹음·분석 프로그램 (완전 로컬, 1인 사용 전용)

### 목적
- 고객 상담 **녹음**
- 발화 단위로 **실시간 한국어 전사** (화자 구분은 자동 안 함, 녹음 중·후 수동 토글)
- 상담 종류별 **AI 분석 리포트** (요약·체크리스트·액션아이템) 생성
- 고객별 폴더에 **자동 파일 배치** (MP3, WAV 원본, 대화전문 MD, 분석 JSON, 요약 MD, 상담정보 JSON)

### 상담 종류 (3종 고정)
1. **초도상담** — 매장에서 고객 처음 응대
2. **디자인미팅** — 실측 후 디자인 안 설명
3. **견적미팅** — 견적 제시/협의

### 절대 제약
1. **비용 0원** — 외부 API 절대 금지 (Whisper·Ollama·silero 전부 로컬)
2. **100% 로컬** — 모델 최초 다운로드 외 오프라인 동작
3. **CPU-only** — GPU 코드 금지, int8 양자화
4. **한국어 중심** — 인테리어 전문용어 처리 최우선

---

## 🏠 실제 운영 환경

### 고객 폴더 루트
- **현재 경로**: `C:\Users\b0463\Documents\Livart&문테리어\07_고객정보` (로컬 Documents)
- 이전 OneDrive 경로에서 이동 완료. `app/config.py` 의 `CLIENT_ROOT` 도 갱신됨.

### 매장 환경 특성 (중요!)
- **백화점 매장에서 사용** → 천장 스피커에서 음악이 계속 흘러나옴
- **노트북 내장 마이크** 사용 (사용자가 라발리에 마이크 도입 보류 중)
- 음악이 사람 목소리 주파수와 겹쳐 인식률에 영향. 소프트웨어로 부분 완화함:
  - silero-denoise (제한적 효과)
  - VAD threshold 상향 (0.65 권장)
  - Whisper 반복 환각 필터
- **현실적 인식률 천장**: 약 60~70% (현 환경 기준). 80%+ 원하면 라발리에 마이크 필요.

### 고객 폴더 네이밍 규칙
- 포맷: `{이름} 고객님({괄호 안 자유})`
- 일부 기업 고객은 `{회사명}건축(...)` 또는 `{회사명}공사(...)`
- **Folder scanner**가 `고객님` / `건축` / `공사` 키워드로 인식

### 고객 폴더 내부 표준 서브폴더 (6종)
```
{고객 폴더}\
├── ETC
├── 렌더이미지_요청      ← 언더스코어 포함
├── 제안서 관련         ← 공백 포함
├── 현장 이미지         ← 공백 포함
├── 휴지통
└── 상담기록             ← InterioNote 출력
```

- **기존 고객 클릭 시**: 누락 폴더 자동 생성 (`ensure_client_template`)
- **신규 고객 생성 시**: 위 6개 처음부터 자동 생성
- **선택 후**: 상담 종류 모달 → /live?m={meeting_id}

### 상담기록 폴더 구조 (Phase 3C/5C 완성)
```
{고객 폴더}\상담기록\2026-04-25_초도상담\
├── 녹음.mp3              ← 128kbps 모노 (lameenc)
├── 녹음원본.wav          ← 16kHz 모노 int16, 재전사용 보존 (Phase 5C)
├── 대화전문.md           ← 타임스탬프 + 화자라벨 + 텍스트
├── 상담정보.json         ← 메타데이터
├── 분석결과.json         ← qwen 원본 응답 (Phase 4 실행 후)
└── 요약.md               ← 사람이 읽기 좋게 정리된 분석 (Phase 4 실행 후)
```

같은 날짜·종류가 중복되면 `2026-04-25_초도상담_2`, `_3` 등으로 증가.

---

## 🆕 Phase 7 추가 사항 (2026-04-25, v2.3.0)

### Phase 7A — 데이터 디렉터리 분리 ✅ (테스트 통과)
**목표**: `.exe` 배포 대비. 사용자 데이터를 앱 코드와 완전 분리해서 업데이트로부터 보호.

새 경로 (Phase 7A):
| 데이터 | 새 위치 |
|---|---|
| DB | `%APPDATA%\InterioNote\data\interionote.db` |
| 모델 캐시 (Whisper, silero) | `%LOCALAPPDATA%\InterioNote\models_cache\` |
| 임시 녹음 | `%LOCALAPPDATA%\InterioNote\temp_recording\` |

`config.py` 추가 함수:
- `_default_user_data_dir()` / `_default_user_cache_dir()` — APPDATA / LOCALAPPDATA 결정
- `migrate_legacy_data()` — 한 번 실행. DB 는 복사(보존), 모델은 이동
- `persist_client_root_default()` — 사용자가 Phase 6A 설정 안 했어도 현재 CLIENT_ROOT 를 settings DB 에 저장
- 환경변수 `INTERIONOTE_DATA_DIR` / `INTERIONOTE_CACHE_DIR` 로 오버라이드 가능 (테스트용)

마이그레이션 실제로 한 번 실행됨 (검증 시점):
- `C:\InterioNote\data\interionote.db` → `%APPDATA%\InterioNote\data\interionote.db` (복사. 옛 파일은 백업으로 남김)
- `C:\InterioNote\models_cache\` → `%LOCALAPPDATA%\InterioNote\models_cache\` (이동, 동일 드라이브 → 원자적 rename)
- 마커 파일: `%APPDATA%\InterioNote\MIGRATED_FROM_LEGACY.txt`

### Phase 7B-3 — 자동 업데이트 확인 + 앱 제거 안내 ✅ (테스트 통과)
**목표**: 새 버전 출시 시 사용자 자동 알림.

`config.py`:
- `GITHUB_OWNER = "tmdqor2-prog"`, `GITHUB_REPO = "InterioNote"`
- 빈 문자열로 두면 비활성화

새 endpoint:
- **`GET /api/app/check-update`**: GitHub Releases API 호출, semver 비교 (lstrip v 처리)
- 응답: `{ok, has_release, current_version, latest_version, is_latest, newer_available, release_url, release_name, release_body, published_at, download_url}`

UI:
- 설정 페이지 최상단 **📦 앱 업데이트** 섹션: 현재 버전 + 업데이트 확인 버튼 + 결과 박스
- **🗑 앱 제거** 섹션: 제어판/언인스톨러 안내 + 사용자 데이터 폴더 열기 버튼 (탐색기로)
- 시작 환영 팝업: 새 버전 발견 시 자동으로 노란 배너 + 다운로드 버튼

JS 브리지 (`InterioNote.py`):
- `pick_folder(initial_dir)` — 네이티브 폴더 선택 (Phase 6A)
- **`open_in_explorer(path)`** — 탐색기로 폴더/파일 열기
- **`open_external_url(url)`** — 기본 브라우저로 URL 열기
- **`get_data_paths()`** — 사용자 데이터 경로 dict 반환

첫 GitHub Release 생성됨: `v2.3.0` (사용자가 직접). 자산은 아직 없음. **다음 단계에서 InterioNoteSetup-2.3.0.exe 를 자산으로 업로드해야 함.**

### Phase 7B-1 — PyInstaller 빌드 ✅ (사용자 테스트 통과)
**목표**: Python 설치 없는 PC 에서도 실행되는 `.exe`.

산출물:
- `dist\InterioNote\InterioNote.exe` (40MB)
- `dist\InterioNote\_internal\` (~2GB, torch + whisper + 의존성 전부 동봉)

핵심 파일:
- **`InterioNote.spec`** — collect_all 로 까다로운 패키지 (torch, torchaudio, ctranslate2, faster_whisper, silero_vad, lameenc, soundfile, sounddevice, onnxruntime, omegaconf, av 등) 통째 포함. Uvicorn 의 동적 protocol import 들 hidden_imports 에 명시. excludes 로 matplotlib/tkinter/PIL 등 안 쓰는 거 제외.
- **`build.bat`** — 사용자 더블클릭 빌드. 실행 중 .exe 자동 종료(taskkill) → build/dist 정리 → PyInstaller 실행. 5~10분 소요.

빌드 모드:
- **현재**: `console=False` (cmd 창 안 뜸, 프로덕션용)
- 디버깅 시: spec 의 `console=True` 로 변경 후 재빌드

### Phase 7B-2 — Inno Setup 인스톨러 🔶 (컴파일 성공, 설치 후 실행 실패)
**목표**: 사용자 친화 설치 마법사 + 제어판 등록 + 언인스톨러.

산출물:
- **`Output\InterioNoteSetup-2.3.0.exe`** (194MB, lzma2/max 압축)

핵심 파일:
- **`InterioNoteSetup.iss`** — Inno Setup 스크립트
  - AppId GUID 고정: `{4F2A8B7C-9D31-4E5C-A6F8-1C0B7D9E4A52}` (이 ID 가 같아야 다음 버전이 "업그레이드" 인식됨)
  - 한국어/English 마법사 (Korean.isl)
  - 설치 경로 사용자 변경 가능 (기본 `{autopf}\InterioNote` = Program Files)
  - 환영 페이지 customizing (`InitializeWizard()` 에서 WelcomeLabel2 override → 앱 설명 + 사용자 데이터 보존 안내)
  - 압축: `lzma2/max + LZMANumBlockThreads=1 + LZMAUseSeparateProcess=yes` (lzma2/ultra64 는 RAM 부족으로 실패함, max 가 안전)
  - SolidCompression=yes
- **`make_installer.bat`** — 더블클릭 컴파일. ISCC.exe 위치 자동 탐지 (표준 경로 + `Program Files\InterioNote\` 비표준 경로 + `INNO_SETUP_DIR` 환경변수)

⚠ **현재 막힌 지점**: 인스톨러 컴파일은 성공해서 InterioNoteSetup-2.3.0.exe 가 만들어졌고, 설치도 외관상 성공함. 그러나 **설치 후 실행 시 작업관리자에 프로세스조차 안 뜨고 아무 동작도 없음**. 가장 유력한 원인은 **Windows Defender 가 unsigned exe 를 Program Files 에서 차단/격리**.

### Phase 7B-2 → 다음 시도: 사용자 영역 설치로 전환 (Discord/Spotify 패턴)
변경 예정 (`.iss`):
- `DefaultDirName={autopf}\{#MyAppName}` → `DefaultDirName={localappdata}\Programs\{#MyAppName}`
- `PrivilegesRequired=admin` → `PrivilegesRequired=lowest`
- `{autodesktop}` / `{group}` → `{userdesktop}` / `{userprograms}\InterioNote`

이렇게 하면 Defender 가 덜 엄격하고 UAC 도 안 뜸. 결과: `%LOCALAPPDATA%\Programs\InterioNote\InterioNote.exe`. 사용자 데이터는 그대로 `%APPDATA%\InterioNote\` (이미 분리됨).

---

## 🆕 Phase 6 추가 사항 (2026-04-25, v2.2.0)

### Phase 6A — 저장 위치·폴더 구조 사용자화 ✅
- **고객 폴더 루트 경로**가 설정 가능 (DB `settings.paths.client_root`)
  - 기본값은 `config.CLIENT_ROOT` (현 사용자 기준 Documents 경로)
  - 변경 즉시 홈 화면 고객 목록 갱신
  - **"📂 찾아보기" 버튼**: pywebview js_api 로 윈도우 네이티브 폴더 다이얼로그 호출
  - "저장 시 폴더 자동 생성" 체크박스: 없는 경로 입력해도 OK
- **폴더 템플릿** 사용자 편집 (DB `settings.paths.folder_template`, JSON list)
  - +/− 버튼으로 행 추가·삭제, 텍스트 직접 편집
  - **`상담기록`** 은 시스템 필수 (자동 유지, UI 에서 readonly+삭제 비활성)
  - 금지문자(`<>:"/\|?*`) 자동 제거, 중복 자동 제거
  - "기본값 복원" 버튼 — `config.FOLDER_TEMPLATE` 로 되돌림
- **JS 브리지** (`InterioNote.py`):
  - `class JsBridge` — `pick_folder(initial_dir)` → `webview.create_file_dialog(FOLDER_DIALOG)`
  - 프론트에서 `window.pywebview.api.pick_folder(...)` 로 호출
  - 브라우저로 열린 경우 안내 메시지로 폴백

### Phase 6B — 시작 팝업 + 버전 관리 ✅
- `config.APP_VERSION` + `config.CHANGELOG` (리스트, 최신 우선)
- **`GET /api/app/info`** → 버전 + changelog 반환
- 홈 화면 init 시 `localStorage["interionote.dismissed_until_version"]` 와 현재 버전 비교
  - 일치하면 팝업 안 띄움
  - 불일치 (또는 처음) → 팝업 표시
- 팝업 동작:
  - **X / ESC / 시작하기 / 바깥 클릭**: 그냥 닫기 → 다음 실행 시 다시 표시
  - **"이번 버전부터 다시 열지 않기"**: localStorage 에 현재 버전 저장 → 같은 버전 동안 안 표시
  - 새 버전이 배포되면 (즉, `APP_VERSION` 이 바뀌면) 자동으로 다시 표시
- **헤더 우측 상단 녹색 배지** (`v2.2.0`) 클릭 시 팝업 수동 호출
- 팝업 내용: 빠른 사용법 5단계 + 최신 패치 노트 + ▶ 이전 버전 변경 이력 (접기)

### Phase 6C — 신규/기존 상담 분기 + 과거 상담 보기 ✅
- 홈에서 고객 클릭 → **🗂 작업 선택 모달**:
  - ✨ 신규 녹음 시작 → 기존 상담 종류 모달
  - 📂 기존 상담 내용 보기 → 과거 상담 목록 모달
- **`GET /api/meetings?folder={folder_name}`** — 해당 고객의 과거 상담 리스트
  - 상태 필터: `recorded / analyzing / done / failed` (즉, finalize 통과한 것)
  - 각 항목에 segments_count, has_analysis, audio_exists 플래그
- 과거 상담 목록 모달: 일시·종류·소요·카드수·AI ✓ / 파일 없음 배지
- 클릭 → `/live?m=X` 이동
- **`live.html` view-mode**:
  - meeting status 가 recorded 이상이면 자동 finished mode 진입 (warmup 스킵)
  - DB 에서 segments 로드, finalResult 객체에 매핑
  - 헤더 박스 색상이 파란색(보기 전용)
  - 화자 라벨 / 재전사 / AI 분석 버튼 모두 그대로 동작
- **🎧 오디오 플레이어** — HTML5 `<audio>` + `/api/meetings/{id}/audio` 스트리밍
  - **`GET /api/meetings/{id}/audio`** → FastAPI `FileResponse` (Range 자동 처리, seek 가능)
  - audio_file 또는 meeting_folder/녹음.mp3 fallback 검색

---

## 🏗 기술 스택 (현재 상태)

| 레이어 | 선택 | 비고 |
|---|---|---|
| 웹 서버 | FastAPI 0.115 + uvicorn | 내부 localhost 전용 |
| 네이티브 창 | **pywebview 5.3** (Edge WebView2) | 브라우저 X, 독립 앱 창 |
| DB | SQLite + WAL | `data/interionote.db` |
| 녹음 | sounddevice 0.5 + soundfile 0.12 | 16kHz mono int16, 100ms 블록 |
| VAD | **silero-vad 5.1 (ONNX)** | 발화 구간 분리, 사용자 threshold 조절 |
| **노이즈 억제** | **silero-denoise (small_slow)** | 500ms 버퍼링, 32→16kHz 다운샘플 |
| STT (실시간) | **faster-whisper small int8** | 한국어, beam=5 |
| STT (재처리) | **faster-whisper medium int8** (선택) | Two-pass 정확도 향상 |
| LLM | **Ollama + qwen2.5:3b** | format=json, 상담 종류별 프롬프트 |
| MP3 인코딩 | **lameenc 1.7.0** | 외부 ffmpeg 불필요 |
| HTTP 클라이언트 | httpx | Ollama 호출 |
| PDF | (Phase 5 원래 계획 — 미구현) | weasyprint 도입 예정 |
| **배포** | **PyInstaller 6.11.1 (--onedir) + Inno Setup 6** | Phase 7B 작업 중 (Defender 이슈로 per-user install 전환 예정) |
| 자동 업데이트 확인 | GitHub Releases API + httpx | Phase 7B-3 완료 |
| 프론트 | Tailwind CDN + Alpine.js 3.14 | React 금지 |

### ❌ 시도했으나 채택 안 한 것
- **PyTorch + SpeechBrain (ECAPA)**: v1에서 화자 자동 판별 시도 → 실패, 전면 제거
- **DeepFilterNet**: Phase 5B 후보 1순위였으나 Windows 에서 Rust 컴파일러 필요 → silero-denoise 로 대체
- **noisereduce**: 음악 환경에 효과 미약, 미사용

### 🔶 Transitive 의존성
- silero-vad 가 **torch (CPU wheel, ~200MB)** 요구 → 그대로 둠
- silero-denoise 도 torch 사용 → 추가 부담 없음
- silero-denoise 가 `omegaconf` 요구 → 별도 설치됨 (`omegaconf==2.3.0`)
- silero-denoise 모델 호출 시 `torchaudio.transforms.Resample` 사용 → torchaudio 필요
- **torchaudio 2.4.1**: 초기에 없어서 silero-vad import 가 실패. `pip install torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cpu` 로 해결.
- **requests**: faster-whisper 의 huggingface_hub 가 요구. 별도 설치됨.

---

## 📂 프로젝트 파일 구조 (`C:\InterioNote\`)

```
C:\InterioNote\
├── InterioNote.py              ← 진입점 (pywebview + FastAPI 스레드 + JsBridge: pick_folder/open_in_explorer/open_external_url/get_data_paths)
├── dev.bat                     ← 개발용 런처 (Python 3.12 검사 + venv + 서버 실행)
├── build.bat                   ← Phase 7B-1: PyInstaller 빌드 더블클릭 런처
├── make_installer.bat          ← Phase 7B-2: Inno Setup 컴파일 더블클릭 런처
├── InterioNote.spec            ← PyInstaller 스펙
├── InterioNoteSetup.iss        ← Inno Setup 스크립트
├── Output\                     ← Inno Setup 산출물
│   └── InterioNoteSetup-2.3.0.exe  ← 배포용 인스톨러 (194MB)
├── dist\InterioNote\           ← PyInstaller 산출물 (~2GB, build.bat 결과)
├── build\                      ← PyInstaller 임시 (자동 정리)
├── requirements.txt            ← 모든 의존성 (Phase 7까지 반영, pyinstaller 포함)
├── data\
│   └── interionote.db          ← SQLite (clients/meetings/transcript_segments/analyses/settings)
├── models_cache\
│   ├── whisper\                ← faster-whisper (small ~460MB, medium ~1.5GB 캐시됨)
│   └── torch_hub\              ← silero (vad + denoise 모델)
│       └── snakers4_silero-models_master\src\silero\model\
│           ├── sns_latest.jit  ← silero-denoise small_slow (~55MB, 다운로드 완료)
│           └── snf_latest.jit  ← silero-denoise small_fast (~46MB)
├── venv\                       ← Python 가상환경 (.gitignore 대상)
└── app\
    ├── __init__.py
    ├── config.py               ← 경로/상담종류/기본 설정값
    ├── server.py               ← FastAPI create_app() 팩토리
    ├── db.py                   ← SQLite 스키마 + 커넥션 헬퍼
    ├── api\
    │   ├── home.py             ← /api/clients, /api/meta, /clients/new, /preview-folder-name, /ensure-template
    │   ├── meetings.py         ← /api/meetings/new, /{id}, /{id}/segments, /{id}/segments/{sid}/speaker, /{id}/retranscribe
    │   ├── recording.py        ← /api/recording/start|stop|state|warmup|segments + /segments/{sid}/speaker
    │   ├── streaming.py        ← /ws/live WebSocket
    │   ├── analyses.py         ← /api/meetings/{id}/analyze, /analysis, /api/ollama/health
    │   └── settings.py         ← /api/settings + /whisper /vocab /noise-suppression /vad
    ├── services\
    │   ├── audio_recorder.py           ← sounddevice 래퍼 (Recorder 클래스)
    │   ├── vad_service.py              ← StreamingVAD (silero, 512샘플)
    │   ├── whisper_service.py          ← live + post 모델 캐시, 환각 필터 (is_repetition_hallucination 공개)
    │   ├── live_session.py             ← 오케스트레이터 (3스레드 파이프라인 + BufferedDenoiser 통합)
    │   ├── noise_suppression_service.py ← silero-denoise + BufferedDenoiser (500ms 청크, 32→16kHz)
    │   ├── mp3_encoder.py              ← lameenc 래퍼
    │   ├── client_service.py           ← upsert_client_by_folder
    │   ├── meeting_finalizer.py        ← 녹음 종료 후처리 (MP3, MD, JSON, WAV 원본 보존)
    │   ├── retranscribe_service.py     ← Two-pass 재전사 + 화자 라벨 이관 + DB/MD 재생성
    │   ├── ollama_client.py            ← httpx 기반 Ollama 클라이언트
    │   ├── analysis_prompts.py         ← 상담 종류별 JSON 스키마 + 시스템 프롬프트
    │   ├── analysis_service.py         ← 분석 오케스트레이터 + render_summary_md
    │   └── settings_service.py         ← 모든 사용자 설정 타입 안전 래퍼
    ├── utils\
    │   ├── folder_scanner.py           ← 07_고객정보 자동 스캔
    │   └── folder_template.py          ← ensure_client_template
    └── static\
        ├── index.html          ← 홈 (고객 목록, 새 고객 모달, 상담 종류 모달, ⚙️설정 링크)
        ├── live.html           ← 실시간 녹음·전사·라벨링·재처리·AI분석 (Phase 2~5C 통합)
        └── settings.html       ← 모델·키워드·VAD·노이즈 토글 (Phase 5A)
```

---

## 🗄 DB 스키마

### clients
`id, name, descriptor, folder_name UNIQUE, folder_path UNIQUE, first_met_at, created_at, notes`

### meetings
`id, client_id FK, meeting_type, started_at, ended_at, duration_sec, meeting_folder, audio_file, temp_folder, status`
- `meeting_type`: 초도상담 | 디자인미팅 | 견적미팅
- `status`: pending | recording | recorded | analyzing | done | failed

### transcript_segments
`id, meeting_id FK, start_ms, end_ms, text, speaker NULL, confidence`
- `speaker`: 'me' | 'client' | NULL

### analyses
`id, meeting_id UNIQUE FK, data_json, model_used, created_at`

### settings (Phase 5A + 6A 활용)
`key PRIMARY KEY, value`

저장되는 키들:
- `whisper.model_size` (default: small)
- `whisper.beam_size` (default: 5)
- `whisper.interior_vocab` (사용자 편집 가능)
- `noise.suppression_enabled` (default: false)
- `vad.threshold` (default: 0.5, 매장 환경 권장 0.65)
- **`paths.client_root`** (Phase 6A, 절대 경로 문자열)
- **`paths.folder_template`** (Phase 6A, JSON list of strings, '상담기록' 자동 보존)

브라우저 localStorage (서버 DB 가 아님):
- **`interionote.dismissed_until_version`** (Phase 6B, 시작 팝업 dismiss 추적)

---

## 📜 Phase 진행 이력 (현재까지)

### v1 (실패, 전체 삭제됨)
- Phase 1~2 v1 동작했으나 Phase 3 v1 (ECAPA 화자 자동 판별) 실패 → 전면 재설계

### Phase 1 v2 — 뼈대 ✅
- FastAPI + pywebview + SQLite + 14명 자동 스캔, 누락 폴더 자동 생성

### Phase 2 v2 — 실시간 녹음·전사 파이프라인 ✅
- 3스레드 큐 파이프라인 (audio_q → speech_q → segments)
- Whisper base → 사용자 검증에서 인식률 50% → small + beam=5 로 업그레이드 → 70~80% 체감

### Phase 3 — 상담 통합 ✅ (전체 완료, 사용자 검증 통과)
- **3A**: 신규 고객 생성 모달 (이름·괄호내용 입력 + 폴더+서브폴더 자동 생성 + DB)
- **3B**: 고객·상담종류 선택 → meeting row → /live?m=X
- **3C**: 녹음 종료 후처리 — WAV→MP3 (lameenc), 임시→최종 폴더, 대화전문.md, 상담정보.json
- **3D**: 화자 토글 (1/2/0 키 + 카드 버튼, 녹음 중·후 모두 가능)

### Phase 4 — Ollama AI 분석 ✅
- qwen2.5:3b 호출 (format=json)
- 상담 종류별 JSON 스키마 정의 (analysis_prompts.py)
- 분석결과.json + 요약.md 자동 생성
- live 페이지에 분석 섹션 + 결과 카드 렌더링

### Phase 5A — 설정 페이지 인프라 ✅
- /settings 페이지 + ⚙️ 진입 링크 (홈 헤더)
- Whisper 모델 선택 (tiny/base/small/medium/large-v3) + 모델 변경 시 자동 재로딩
- 키워드 사전 편집 (textarea, 기본값 복원, DB 저장)
- VAD threshold 슬라이더 (0.30~0.85)
- 노이즈 억제 토글 (5B 에서 활성화)

### Phase 5B — 노이즈 억제 ✅ (실 환경 검증 완료)
**여정**:
1. DeepFilterNet 시도 → Rust 컴파일러 필요로 Windows 설치 불가 → 포기
2. silero-denoise 로 전환 (`omegaconf` 자동 설치)
3. **첫 시도 실패**: 100ms 짜리 짧은 블록을 모델에 직접 전달 → 거의 무음 출력 → 사용자 "마이크가 음성을 인식 못 함" 보고
4. **수정**: BufferedDenoiser 클래스 추가로 500ms 버퍼링
5. **두 번째 발견**: silero-denoise 출력이 32kHz (입력 16kHz의 ~2배 길이) → torchaudio Resample 로 32→16kHz 다운샘플
6. **검증 완료**: 출력 RMS 비율 1.117 (입력 대비, 정상 신호)

**한계 정직하게 기록**:
- silero-denoise 는 **음성과 주파수 영역이 겹치는 음악(매장 환경)에는 효과 제한적**
- 일반 잡음(HVAC, 트래픽, 키보드)에는 효과적
- 매장 음악 환경에서 80%+ 인식률은 결국 **방향성 마이크(라발리에/헤드셋)** 가 결정적

### Phase 5B-extra — Whisper 반복 환각 필터 ✅
- 매장 음악이 입력되면 Whisper 가 `작품, 작품, 작품, ...` 같은 의미 없는 반복을 출력하는 알려진 실패 모드
- `whisper_service._is_repetition_hallucination` 추가 + `is_repetition_hallucination` 공개 alias
- 한 토큰이 60% 이상 차지 또는 짧은 텍스트가 모두 같은 단어 → 빈 문자열 반환 → 카드 자체 생성 안 됨
- 사용자 환경에서 즉시 효과 확인됨

### Phase 5C — Two-pass 재전사 ✅
**배경**: 사용자가 "small 인식률 부족" 보고. 이 CPU 에서 medium 실시간은 불가 (Speech Q 26개 쌓임 → 환각 폭발). 두 가지 다 잡는 방법으로 Two-pass 도입.

**구조**:
- `whisper_service` 가 multi-model 캐시: `_live_model` + `_post_models[size]`
- `meeting_finalizer` 가 `녹음원본.wav` 를 상담 폴더에 보존 (재전사용)
- `retranscribe_service.retranscribe_meeting(meeting_id, model_size)`:
  - 녹음원본.wav 로 medium (또는 선택) 재전사 (faster-whisper 내장 VAD 사용)
  - 환각 필터 적용
  - 화자 라벨 시간 겹침으로 자동 이관 (`_transfer_speaker_labels`)
  - DB transcript_segments 교체 + 대화전문.md 재생성
- UI: 녹음 완료 화면에 🎯 정확도 재처리 박스 (모델 선택 드롭다운 + 진행 상태 + 결과)

**한계**:
- 이 변경 이전에 녹음한 상담은 `녹음원본.wav` 가 없어서 재처리 불가 (안내 메시지 출력)
- medium 첫 다운로드 ~1.5GB

### Phase 6 — 사용자화·시작 팝업·과거 상담 보기 ✅ (v2.2.0)
- **6A**: 저장 위치/폴더 템플릿 사용자 설정 + 네이티브 폴더 선택 다이얼로그
- **6B**: APP_VERSION + CHANGELOG + 시작 환영 팝업 (localStorage dismiss + 버전 변경 시 재표시)
- **6C**: 작업 선택 모달 (신규/기존) + 과거 상담 목록 + view-mode + 오디오 재생

### ❌ 아직 안 한 것
- **PDF 생성** (원래 Phase 5 계획): Markdown → 요약.pdf (weasyprint, 한글 폰트). 추가 가치 낮아 보류.
- **PyInstaller `.exe` 단일 배포**: 다른 PC 에 옮길 때 Python·venv 설치 없이 실행 가능. 빌드 디버깅 까다로움.

---

## 🔧 실행 방법

### 개발 모드 (현재)
1. `C:\InterioNote\dev.bat` 더블클릭
2. 최초 1회 자동 pip install
3. 설치 끝나면 pywebview 네이티브 창 자동 오픈
4. 홈 → 고객 선택 (또는 새 고객) → 상담 종류 → 녹음 시작
5. 종료 후 화면에서 **🎯 정확도 재처리** 또는 **✨ AI 분석** 실행

### 빠른 동작 체크리스트
- ✅ 홈에 고객 14명 + 새로 만든 고객들 표시
- ✅ /live 화면에서 warmup 후 카드 정상 생성
- ✅ 1/2/0 키로 화자 라벨링
- ✅ 종료 시 `녹음.mp3` + `녹음원본.wav` + `대화전문.md` + `상담정보.json` 4개 파일 생성
- ✅ 정확도 재처리 (medium) 클릭 → 새 카드로 자동 교체
- ✅ AI 분석 → `요약.md` + `분석결과.json` 추가 생성

---

## 🐛 알려진 이슈 & 해결 기록

### 1. Python 3.14 호환성 (해결됨)
`py -3.12` 강제 사용으로 해결. dev.bat 에서 가드.

### 2. .bat 한글 깨짐 / 복사 사고 (해결됨)
영문 전용 .bat + `if not exist requirements.txt` 가드 + 바탕화면 복사 방지 안내.

### 3. cmd 창이 에러 시 자동 닫힘 (해결됨)
`pause >nul` + `call :main` 패턴.

### 4. ECAPA 모델 로드 실패 (v1 → v2 로 해결)
SpeechBrain 자체 제거. 화자 수동 토글로 전환.

### 5. OneDrive 동기화 충돌 (예방됨)
임시 녹음은 `C:\InterioNote_temp\` 로컬 고정. 종료 시 최종 폴더로 이동.

### 6. 경로 대이동 OneDrive → Documents (완료)
`CLIENT_ROOT` 갱신.

### 7. silero-vad 가 torchaudio 요구 (해결됨)
`pip install torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cpu`

### 8. faster-whisper 가 requests 요구 (해결됨)
`pip install requests`

### 9. DeepFilterNet 설치 실패 (Windows Rust 필요) → silero-denoise 로 우회 (해결됨)
deepfilterlib 가 Rust 빌드 도구 요구 → silero-denoise 채택.

### 10. silero-denoise 가 100ms 블록에 무음 출력 (해결됨, Phase 5B 핵심 디버깅)
- 원인: 모델은 ≥500ms 컨텍스트 필요
- 해결: `BufferedDenoiser` 클래스로 500ms 청크 누적

### 11. silero-denoise 출력이 32kHz (해결됨, Phase 5B 핵심 디버깅)
- 원인: 모델 출력은 32kHz @ 입력 길이의 ~2배
- 해결: `torchaudio.transforms.Resample(32000, 16000)` 추가

### 12. medium 모델 실시간 처리 불가 (해결됨, Phase 5C 로 우회)
- Ryzen 5 7520U 에서 medium 은 ~2x 실시간 = Speech Q 폭주 + 환각
- 해결: 실시간은 small, 종료 후 medium 재처리 (Two-pass)

### 13. Whisper 반복 환각 (`작품, 작품, ...`) (해결됨)
음악·노이즈에 대한 알려진 실패 모드. 토큰 빈도 분석 필터로 해당 카드 자동 폐기.

### 14. (Phase 6C) view-mode 진입 시 finalResult 매핑
이전 상담을 `/live?m=X` 로 다시 열 때, DB 의 segments 와 meeting row 를 finalResult 객체로 변환하는 단계가 필요. enterViewMode() 가 이 매핑을 담당. markdown_path / info_json_path 는 meeting_folder 기반 파생.

### 15. (Phase 7B-2) Inno Setup OOM
`Compression=lzma2/ultra64` 는 dist 폴더(~2GB) 압축 시 메모리 부족으로 실패. 해결: `lzma2/max + LZMANumBlockThreads=1 + LZMAUseSeparateProcess=yes`. 압축률 살짝 떨어지지만 안정적.

### 16. (Phase 7B-2) ISCC.exe 비표준 경로
사용자가 Inno Setup 설치 시 install path 를 InterioNote 로 직접 지정해서 `C:\Program Files\InterioNote\ISCC.exe` 에 깔림 (보통은 `C:\Program Files (x86)\Inno Setup 6\`). `make_installer.bat` 가 표준 경로 + 이 비표준 경로 + `INNO_SETUP_DIR` 환경변수 모두 자동 탐지.

### 17. (Phase 7B-2 진행 중) 설치된 .exe 가 실행 안 됨 (현재 막힘)
- `Output\InterioNoteSetup-2.3.0.exe` 로 설치 후, `C:\Program Files\InterioNote\InterioNote.exe` 더블클릭 시 작업관리자에 프로세스도 안 뜸
- dev 모드 (`dist\InterioNote\InterioNote.exe`) 는 정상 동작 — 같은 바이너리인데 install location 만 다름
- 가장 유력한 원인: **Windows Defender 가 unsigned exe 를 Program Files 에서 차단/격리**
- 다음 시도: **per-user install** 로 전환 (Discord/Spotify 패턴) → `%LOCALAPPDATA%\Programs\InterioNote\` 에 설치, UAC 없음, Defender 가 덜 엄격
- 사용자 응답 대기 중: Defender 보호 기록에 InterioNote 격리 이력 있는지 확인

---

## 📋 워크플로우 규칙 (계속 유효)

1. **Phase 단위 중단 원칙**: 각 Phase 완료 후 멈추고 사용자 검증 받기
2. **비개발자 친화 명령**: cmd 한 줄 복붙 또는 더블클릭 .bat
3. **에러 원인 노출**: HTTP 500 detail 에 예외 타입+메시지 400자, cmd 에 traceback 전체
4. **프리뷰 패널 알림**: HTML 편집 시 hook 알림 → 응답에 "프리뷰 패널에 표시되어 있습니다" 명시
5. **삭제는 확인 후**: 업무 폴더(`Livart&문테리어\`) 절대 삭제 금지
6. **솔직한 한계 인정**: 매장 음악처럼 소프트웨어로 한계 있는 부분은 하드웨어 솔루션 정직하게 안내

---

## ⏭ 다음 세션에서 바로 할 것

### 🔴 현재 막힌 지점 (Phase 7B-2 마무리)
**InterioNoteSetup-2.3.0.exe 로 설치 후 InterioNote.exe 가 실행 안 됨.** 작업관리자에 프로세스도 안 뜸. dev 모드는 정상.

**즉시 시도할 작업** (사용자 응답 받자마자 진행):
1. Defender 격리 기록 확인 — 사용자에게 물음
2. 답변 무관하게 `.iss` 를 per-user install 로 수정:
   - `DefaultDirName={localappdata}\Programs\{#MyAppName}`
   - `PrivilegesRequired=lowest`
   - `{autodesktop}` → `{userdesktop}`, `{group}` 자동 사용자 영역
3. `make_installer.bat` 재실행 → 새 InterioNoteSetup-2.3.0.exe 생성
4. 사용자가 기존 설치 (Program Files) 제거 후 새 인스톨러 실행
5. `%LOCALAPPDATA%\Programs\InterioNote\` 에 설치되고 정상 실행되는지 검증

### Phase 7B-2 마무리 후 — 7B 전체 완료 단계
1. GitHub Releases v2.3.0 에 InterioNoteSetup-2.3.0.exe 자산 업로드
2. 앱에서 ⚙️ 설정 → 📦 업데이트 확인 → 가장 최신 버전 확인 (자산 파일 인식)
3. (선택) 다른 PC 에서 인스톨러 다운로드 → 설치 → 실행 검증

### 그 다음 가능한 작업
- 매장 며칠 실사용 후 피드백 (PyInstaller 와 무관하게)
- 신기능 / 정확도 튜닝 / PDF 생성 / 단축키 확장 등

### 첫 메시지 권장 (현재 막힌 지점이 있으니)
**"Defender 격리 기록에서 InterioNote 가 차단된 흔적 확인하셨어요? 어쨌든 per-user install 로 바꾸는 작업 진행할게요."**

### 흔한 피드백 시나리오 + 대응

| 피드백 | 대응 |
|---|---|
| "여전히 매장 음악 때문에 인식 50% 정도" | **하드웨어 마이크 강력 추천** (BOYA BY-M1 ₩25k~30k USB 라발리에). 소프트웨어 한계는 정직하게. |
| "AI 분석에 다른 항목 추가하고 싶다" | `analysis_prompts.py` 의 SCHEMAS 사용자 편집 가능하게 (settings 페이지에 추가) |
| "이전 상담 검색하고 싶다" | 새 `/meetings` 페이지 또는 홈에 검색바 추가, 전사 텍스트 FTS 검색 |
| "AI 요약을 인쇄/메일로 보내고 싶다" | weasyprint 로 PDF (보류 중인 Phase 5) |
| "다른 직원도 쓸 수 있게 .exe 로 배포" | Phase 6.5 PyInstaller 빌드 — 모델 캐시 동봉, 디버깅 까다로움 |
| "단축키 더 필요하다 (예: 다음 카드로 포커스)" | live.html 의 handleKeydown 확장 |
| "다중 PC 동기화" | 외부 클라우드 동기화 권장 (Dropbox/OneDrive 폴더로 CLIENT_ROOT 설정 — 이미 가능) |

### 새 기능 추가 시 워크플로우
1. 코드 변경 + 검증
2. `config.py` 의 `APP_VERSION` 올림 (Patch/Minor/Major 구분)
3. `CHANGELOG` 맨 위에 `{version, date, title, items}` 추가
4. 사용자 다음 실행 시 자동으로 시작 팝업으로 안내됨 (Phase 6B)

---

## 🔗 경로 참조 요약

| 용도 | 경로 |
|---|---|
| 프로그램 본체 | `C:\InterioNote\` |
| 실행 런처 | `C:\InterioNote\dev.bat` |
| DB | `C:\InterioNote\data\interionote.db` |
| Whisper 캐시 | `C:\InterioNote\models_cache\whisper\` |
| Silero 캐시 (vad+denoise) | `C:\InterioNote\models_cache\torch_hub\` |
| 임시 녹음 | `C:\InterioNote_temp\session_*\` |
| 고객 폴더 루트 | `C:\Users\b0463\Documents\Livart&문테리어\07_고객정보\` |
| 이 인수인계 파일 | `{위 루트}\CLAUDE.md` |

---

## 📝 작업 이력 타임라인 (요약)

- **초반 기획** — 4종 상담 → 3종 축소 + 화자 자동 판별 → 수동 토글
- **Phase 1~2 v1** — ECAPA 도전 → 실패 → 전면 삭제
- **v2 재설계** — 경량화(SpeechBrain 제거) + .exe 배포 목표
- **Phase 1~2 v2** — 뼈대 + 실시간 파이프라인 (테스트 통과)
- **경로 이동** — OneDrive → Documents
- **Phase 3 (3A→3D)** — 신규 고객, 상담 시작 플로우, 녹음 종료 후처리, 화자 토글
- **Phase 4** — Ollama qwen2.5:3b 분석
- **Phase 5A** — 설정 페이지 (모델/키워드/VAD/노이즈 토글)
- **Phase 5B 시도 1: DeepFilterNet** — Rust 필요 → 포기
- **Phase 5B 시도 2: silero-denoise** — 100ms 블록 무음 버그 + 32kHz 출력 두 번 디버깅 → BufferedDenoiser + Resample 로 안정화
- **Phase 5B-extra: Whisper 환각 필터** — 매장 음악 대응
- **Phase 5C: Two-pass 재처리** — small 실시간 + medium 후처리, 화자 라벨 시간 겹침 자동 이관
- **Phase 6A** — 저장 위치/폴더 템플릿 사용자 설정 + 네이티브 폴더 다이얼로그
- **Phase 6B** — APP_VERSION + CHANGELOG + 시작 환영·패치 팝업 (localStorage dismiss + 버전 변경 자동 재표시)
- **Phase 6C** — 작업 선택 모달, 과거 상담 목록, /live view-mode (오디오 재생 + 라벨 편집 가능)
- **버전 v2.2.0** 으로 마무리, 사용자 "테스트 완료. 정상작동" 확인
- **Phase 7A** — 데이터 디렉터리 분리 (`%APPDATA%` / `%LOCALAPPDATA%`) + 자동 마이그레이션 1회 실행됨
- **Phase 7B-3** — GitHub repo `tmdqor2-prog/InterioNote` Public 생성 + 첫 release v2.3.0 발행 (자산 미첨부) + 인앱 업데이트 확인 동작
- **Phase 7B-1** — PyInstaller --onedir 빌드 성공 (console=False), dev 위치에서 정상 실행 확인
- **Phase 7B-2** — Inno Setup 인스톨러 컴파일 성공 (`InterioNoteSetup-2.3.0.exe` 194MB)
- **Phase 7B-2 막힘** — 설치된 exe 가 Program Files 위치에서 실행 안 됨, 작업관리자에 프로세스 안 뜸. Defender 차단 추정. **per-user install 전환 필요.**
- **이 CLAUDE.md 갱신** (Phase 7B-2 막힌 시점)

---

## 🚨 다음 Claude 에게 마지막 당부

1. **이 문서를 끝까지 읽은 후** "인수인계 파일을 읽었습니다. 매장에서 며칠 사용해 보셨나요?" 같은 자연스러운 시작.
2. **사용자가 명시적으로 요청하기 전까지 새 Phase 코드 작성 금지**.
3. **비개발자**임을 잊지 마세요 — 한 줄씩 안내, 에러 시 창 자동 안 닫히게, 전체 로그 공유 요청.
4. **솔직한 한계 인정**: 음악 환경 인식률, CPU 한계, 모델 다운로드 시간 등.
5. 코드 수정 시 기존 패턴 준수:
   - Tailwind CDN + Alpine.js (React 금지)
   - FastAPI 라우터 분리, 한국어 주석, 예외 타입명 노출
   - 새 설정은 `settings_service` + `/api/settings` + `settings.html` 3 곳에 일관되게 추가
   - 새 모델 사용 시 모델 캐시 위치 통일 (`config.MODELS_CACHE_DIR`)
6. **반복 디버깅 패턴 인식**: 사용자가 보고하는 문제는 보통 환경 특수성(매장 음악, CPU 한계)에서 옴 → 모델/하드웨어 트레이드오프를 명확하게 설명하고 함께 결정.

---

_이 문서는 Phase 6C (v2.2.0 — 과거 상담 보기 + 오디오 재생) 까지 완료 후 갱신되었습니다._
_사용자의 다음 행동: 매장 며칠 실사용 → 피드백 → 다음 작업 결정._
_핵심 미해결 (남아 있는 옵션): PDF 출력 / PyInstaller .exe 배포 / 매장 음악용 하드웨어 마이크 도입._
