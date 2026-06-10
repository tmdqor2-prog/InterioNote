# InterioNote 프로젝트 — Codex 세션 인수인계

> **다음 세션의 Codex에게**: 이 파일은 이전 Codex가 사용자와 나눈 대화의 전체 맥락입니다.
> 사용자는 처음부터 다시 설명하지 않아도 되도록, 이 파일을 먼저 끝까지 읽고 작업을 이어가 주세요.
> 마지막 섹션 **"⏭ 다음 세션에서 바로 할 것"** 부터 확인하면 재개 지점이 명확합니다.

---

## 👤 사용자 프로파일

- **직업**: 인테리어 디자이너 1인 (Livart&문테리어 소속 / 개인 사업 병행)
- **기술 수준**: 비개발자. Windows cmd 복붙 가능 수준. 코드는 읽지 못함.
- **주 작업 PC**: 데스크탑 (사용자명 `tmdqo`) — 2026-04-26 부터 메인 기기로 전환. 기존 노트북(b0463, ASUS Vivobook Go 15 E1504F)에서 OneDrive로 데이터 동기화 완료.
- **Python 환경**: 3.12.8 설치됨. (`py -3.12` 고정 사용)
- **이메일**: tmdqor2@gmail.com
- **Ollama**: 설치 완료 + `qwen2.5:3b` 다운로드 완료 (1.9GB, Q4_K_M)
- **GitHub**: `tmdqor2-prog` 계정 + Public repo `tmdqor2-prog/InterioNote` 생성됨 (자동 업데이트 확인용)
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
9. **CHANGELOG 규칙**: 새 기능 추가 시 반드시 `version.json` 의 `changelog` 맨 위에 **디자이너 관점**으로 항목 추가. 기술적 내용은 한 줄로 묻기.

---

## 🎯 프로젝트 개요

### 이름
**InterioNote** — 인테리어 상담 실시간 녹음·분석 프로그램 (완전 로컬, 다중 노트북 배포 가능)

### 목적
- 고객 상담 **녹음** (10분~2시간)
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
3. **CPU-only** — GPU 코드는 선택적 지원, 기본은 int8 양자화 CPU
4. **한국어 중심** — 인테리어 전문용어 처리 최우선

---

## 🏠 실제 운영 환경

### 고객 폴더 루트
- **b0463 노트북**: `C:\Users\b0463\Documents\Livart&문테리어\07_고객정보`
- **tmdqo 데스크탑**: 경로는 settings DB (`paths.client_root`) 에 저장됨 — 앱 설정 탭에서 확인 가능
- OneDrive 로 데이터 동기화됨

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

### 상담기록 폴더 구조
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

## 🆕 v3.0.0 신규 기능 (2026-05-03)

### Phase 1 — 고객 연락처 + 카톡 문구 + 홈 필터 ✅

- **고객 연락처 등록**: 신규 고객 생성 시 전화번호·방문경로 입력. 고객 360뷰에서 편집 가능
- **카톡 안내 문구 자동 생성**: 상담 종료 후 한 클릭 → 고객·담당자 정보 + 상담 내용 기반 카톡 문구 자동 생성·클립보드 복사
- **홈 단계 필터 + 전화번호 검색**: 홈 화면에서 진행 단계별 필터링, 전화번호로 고객 검색
- **담당자 정보 설정**: 설정 → 일반 탭에서 담당자 이름·매장명·연락처 등록 → 카톡 문구 서명 자동 반영

### Phase 2 — 로그인 + 사용자 관리 ✅ (사용자 검증 완료: "정상작동 확인")

**목표**: 앱을 다중 사용자가 쓸 수 있도록 계정·권한 시스템 추가.

#### 인증 시스템
- **JWT (HS256)**: `PyJWT==2.10.1`. Secret은 settings DB 에 앱 최초 실행 시 자동 생성. 만료: 30일.
- **bcrypt 비밀번호 해싱**: `bcrypt` 라이브러리 직접 사용 (passlib 없이). passlib 1.7.4 + bcrypt 5.x 비호환 이슈 우회.
- **JWT secret 키**: `settings` DB 의 `auth.jwt_secret` 에 자동 저장.

#### 미들웨어
- `_AuthMiddleware (BaseHTTPMiddleware)`: `/api/*` 경로 전체 JWT 검증
- 화이트리스트 (토큰 없이 접근 가능):
  - `/api/auth/login` — 로그인
  - `/api/health` — 헬스체크
  - `/api/app/info` — 버전 정보
  - `/api/app/check-update` — 업데이트 확인

#### 마스터 계정 자동 생성
- 앱 시작 시 `ensure_master_user()` 호출 → DB에 master 계정 없으면 자동 생성
- **초기 계정**: `admin` / `1234` (사용자가 변경 권장)

#### 역할 (role)
- `master`: 전체 권한 (사용자 관리 포함)
- `user`: 녹음·분석만 가능. 사용자 관리 탭 비활성화.

#### 프론트엔드 인증 처리 (모든 HTML 공통)
- Alpine.js defer 직전에 글로벌 auth 스크립트 주입 (IIFE)
- `window.fetch` 오버라이드 → `/api/` 요청에 `Authorization: Bearer {token}` 자동 주입
- 401 응답 → 토큰 삭제 + `/login` 리디렉트
- 즉시 IIFE: 페이지 로드 시 토큰 없으면 즉시 `/login` 리디렉트 (Alpine 실행 전)
- Base64URL 디코딩으로 만료 시각 클라이언트 측 확인

#### localStorage 키 (서버 DB 아님)
- `interionote.token` — JWT 토큰 (30일 유효)
- `interionote.user` — `{username, display_name, role}` JSON
- `interionote.dismissed_until_version` — 시작 팝업 dismiss 추적 (Phase 6B)

#### 설정 페이지 사용자 관리 탭
- `tabs` 배열에 `{key: 'users', masterOnly: true}` 추가
- `get filteredTabs()` computed → 마스터 아니면 users 탭 숨김
- 일반 탭 최상단: "👤 내 계정" 섹션 (로그인 사용자 표시 + 로그아웃 + 비밀번호 변경)
- users 탭: 계정 목록 + 새 계정 추가 + 편집 + 삭제

---

## 🆕 Phase 7 추가 사항 (2026-04-25, v2.3.0)

### Phase 7A — 데이터 디렉터리 분리 ✅
새 경로:
| 데이터 | 위치 |
|---|---|
| DB | `%APPDATA%\InterioNote\data\interionote.db` |
| 모델 캐시 (Whisper, silero) | `%LOCALAPPDATA%\InterioNote\models_cache\` |
| 임시 녹음 | `%LOCALAPPDATA%\InterioNote\temp_recording\` |

마이그레이션 이미 실행됨 (한 번만):
- 구 `C:\InterioNote\data\interionote.db` → `%APPDATA%\InterioNote\data\` (복사, 구 파일 보존)
- 구 `C:\InterioNote\models_cache\` → `%LOCALAPPDATA%\InterioNote\models_cache\` (이동)

### Phase 7B-3 — 자동 업데이트 확인 ✅
- `GET /api/app/check-update`: GitHub Releases API 호출, semver 비교
- 설정 페이지 📦 업데이트 섹션 + 시작 팝업 새 버전 배너
- JS 브리지 (`InterioNote.py`): `open_in_explorer`, `open_external_url`, `get_data_paths`

### Phase 7B-1 — PyInstaller 빌드 ✅
- `dist\InterioNote\InterioNote.exe` (40MB 런처 + `_internal\` ~2GB)
- `build.bat` 더블클릭 → 자동 빌드 (5~10분)

### Phase 7B-2 — Inno Setup 인스톨러 🔶 (per-user install 전환 보류)
- 컴파일 성공: `Output\InterioNoteSetup-X.X.X.exe`
- `InterioNoteSetup.iss`: AppId GUID 고정 `{4F2A8B7C-9D31-4E5C-A6F8-1C0B7D9E4A52}`
- ⚠ Program Files 설치 시 Defender 차단 이슈 있었음 → per-user install 로 전환 권장
  - `DefaultDirName={localappdata}\Programs\{#MyAppName}`
  - `PrivilegesRequired=lowest`
- 빌드 후 GitHub Releases 에 자산 업로드 필요

---

## 🆕 Phase 6 추가 사항 (v2.2.0)

### Phase 6A — 저장 위치·폴더 구조 사용자화 ✅
- 고객 폴더 루트 경로 설정 (`paths.client_root`)
- 폴더 템플릿 사용자 편집 (`paths.folder_template`)
- JS 브리지 `pick_folder(initial_dir)` — 네이티브 폴더 선택 다이얼로그

### Phase 6B — 시작 팝업 + 버전 관리 ✅
- `version.json` 의 `version` + `changelog` (디자이너 관점)
- `GET /api/app/info` → 버전 + changelog
- localStorage `dismissed_until_version` 로 dismiss 추적

### Phase 6C — 신규/기존 상담 분기 + 과거 상담 보기 ✅
- 작업 선택 모달 (신규 / 과거 상담 보기)
- `live.html` view-mode: 기존 상담 열기 + 오디오 재생 + 라벨 편집

---

## 🏗 기술 스택 (현재 상태)

| 레이어 | 선택 | 비고 |
|---|---|---|
| 웹 서버 | FastAPI 0.115 + uvicorn | 내부 localhost 전용 |
| 네이티브 창 | **pywebview 5.3** (Edge WebView2) | 브라우저 X, 독립 앱 창 |
| DB | SQLite + WAL | `%APPDATA%\InterioNote\data\interionote.db` |
| **인증** | **JWT (PyJWT 2.10.1) + bcrypt** | 30일 토큰, HS256, bcrypt 직접 사용 |
| 녹음 | sounddevice 0.5 + soundfile 0.12 | 16kHz mono int16, 100ms 블록 |
| VAD | **silero-vad 5.1 (ONNX)** | 발화 구간 분리, 사용자 threshold 조절 |
| 노이즈 억제 | **silero-denoise (small_slow)** | 500ms 버퍼링, 32→16kHz 다운샘플 |
| STT (실시간) | **faster-whisper small int8** | 한국어, beam=5 |
| STT (재처리) | **faster-whisper medium int8** (선택) | Two-pass 정확도 향상 |
| LLM | **Ollama + qwen2.5:3b** | format=json, 상담 종류별 프롬프트 |
| MP3 인코딩 | **lameenc 1.7.0** | 외부 ffmpeg 불필요 |
| HTTP 클라이언트 | httpx | Ollama + GitHub API 호출 |
| 배포 | **PyInstaller 6.11.1 (--onedir) + Inno Setup 6** | per-user install 전환 권장 |
| 자동 업데이트 확인 | GitHub Releases API + httpx | Phase 7B-3 완료 |
| 프론트 | Tailwind CDN + Alpine.js 3.14 | React 금지 |

### ❌ 시도했으나 채택 안 한 것
- **PyTorch + SpeechBrain (ECAPA)**: v1에서 화자 자동 판별 시도 → 실패, 전면 제거
- **DeepFilterNet**: Rust 컴파일러 필요 → silero-denoise 로 대체
- **noisereduce**: 음악 환경에 효과 미약, 미사용
- **passlib[bcrypt]**: passlib 1.7.4 + bcrypt 5.x 비호환 → bcrypt 직접 사용

### 🔶 Transitive 의존성
- silero-vad → **torch (CPU, ~200MB)** / torchaudio 2.4.1 필요
- silero-denoise → omegaconf 2.3.0 + torchaudio
- faster-whisper → requests (huggingface_hub)

---

## 📂 프로젝트 파일 구조 (`C:\InterioNote\`)

```
C:\InterioNote\
├── InterioNote.py              ← 진입점 (pywebview + FastAPI + JsBridge)
├── dev.bat                     ← 개발용 런처 (Python 3.12 검사 + venv)
├── build.bat                   ← PyInstaller 빌드 더블클릭 런처
├── make_installer.bat          ← Inno Setup 컴파일 더블클릭 런처
├── InterioNote.spec            ← PyInstaller 스펙
├── InterioNoteSetup.iss        ← Inno Setup 스크립트
├── Output\                     ← Inno Setup 산출물
├── dist\InterioNote\           ← PyInstaller 산출물 (~2GB)
├── requirements.txt            ← 모든 의존성 (PyJWT 추가, passlib 제거)
├── version.json                ← APP_VERSION + CHANGELOG (디자이너 관점)
└── app\
    ├── __init__.py
    ├── config.py               ← 경로/상담종류/기본 설정값
    ├── server.py               ← FastAPI create_app() + _AuthMiddleware
    ├── db.py                   ← SQLite 스키마 + 커넥션 헬퍼
    ├── api\
    │   ├── auth.py             ← /api/auth/login, /me, /change-password (v3.0.0)
    │   ├── users.py            ← /api/users CRUD (마스터 전용) (v3.0.0)
    │   ├── home.py             ← /api/clients, /api/meta, /clients/new 등
    │   ├── meetings.py         ← /api/meetings/* (+ 카톡 문구 v3.0.0)
    │   ├── recording.py        ← /api/recording/*
    │   ├── streaming.py        ← /ws/live WebSocket
    │   ├── analyses.py         ← /api/meetings/{id}/analyze, /api/ollama/health
    │   ├── settings.py         ← /api/settings/*
    │   ├── stats.py            ← /api/stats
    │   ├── ojt.py              ← OJT 동기화 (v2.6.0)
    │   ├── pdf.py              ← PDF 출력 (v2.6.0)
    │   ├── customer.py         ← 고객 360뷰 (v2.6.0)
    │   ├── quick_replies.py    ← 빠른 답변 템플릿 (v2.7.0)
    │   ├── backup.py           ← 데이터 백업 (v2.7.0)
    │   ├── quote.py            ← 견적서 자동 작성 (v2.8.0)
    │   └── search.py           ← 통합 검색 (v2.8.0)
    ├── services\
    │   ├── auth_service.py             ← JWT+bcrypt, ensure_master_user, 사용자 CRUD (v3.0.0)
    │   ├── audio_recorder.py           ← sounddevice 래퍼
    │   ├── vad_service.py              ← StreamingVAD (silero)
    │   ├── whisper_service.py          ← live + post 모델 캐시, 환각 필터
    │   ├── live_session.py             ← 3스레드 파이프라인 + BufferedDenoiser
    │   ├── noise_suppression_service.py ← silero-denoise (500ms 청크, 32→16kHz)
    │   ├── mp3_encoder.py              ← lameenc 래퍼
    │   ├── client_service.py           ← upsert_client_by_folder
    │   ├── meeting_finalizer.py        ← 녹음 종료 후처리
    │   ├── retranscribe_service.py     ← Two-pass 재전사
    │   ├── ollama_client.py            ← httpx 기반 Ollama 클라이언트
    │   ├── analysis_prompts.py         ← 상담 종류별 JSON 스키마 + 프롬프트
    │   ├── analysis_service.py         ← 분석 오케스트레이터 + render_summary_md
    │   └── settings_service.py         ← 모든 사용자 설정 타입 안전 래퍼
    ├── utils\
    │   ├── folder_scanner.py           ← 07_고객정보 자동 스캔
    │   └── folder_template.py          ← ensure_client_template
    └── static\
        ├── login.html          ← 로그인 페이지 (v3.0.0, 인증 불필요 접근)
        ├── index.html          ← 홈 (고객 목록, 필터, 검색, 연락처)
        ├── live.html           ← 실시간 녹음·전사·라벨링·재처리·AI분석·카톡문구
        ├── settings.html       ← 설정 (탭: 일반/사용자폴더/음성인식/키워드/단축키/사용자관리)
        ├── customer.html       ← 고객 360뷰
        ├── stats.html          ← 상담 통계
        ├── search.html         ← 통합 검색
        └── quick_note.html     ← 빠른 음성 메모
```

---

## 🗄 DB 스키마

### clients
`id, name, descriptor, folder_name UNIQUE, folder_path UNIQUE, first_met_at, created_at, notes`
- v3.0.0: `phone TEXT` (전화번호), `visit_source TEXT` (방문경로) 추가

### meetings
`id, client_id FK, meeting_type, started_at, ended_at, duration_sec, meeting_folder, audio_file, temp_folder, status`
- `meeting_type`: 초도상담 | 디자인미팅 | 견적미팅
- `status`: pending | recording | recorded | analyzing | done | failed

### transcript_segments
`id, meeting_id FK, start_ms, end_ms, text, speaker NULL, confidence`
- `speaker`: 'me' | 'client' | NULL

### analyses
`id, meeting_id UNIQUE FK, data_json, model_used, created_at`

### **users** (v3.0.0 신규)
```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,       -- bcrypt 해시
    role TEXT NOT NULL DEFAULT 'user', -- 'master' | 'user'
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### settings
`key PRIMARY KEY, value`

저장되는 키들:
- `whisper.model_size`, `whisper.beam_size`, `whisper.interior_vocab`
- `noise.suppression_enabled`
- `vad.threshold` (매장 환경 권장: 0.65)
- `paths.client_root`, `paths.folder_template`
- **`auth.jwt_secret`** (v3.0.0, 자동 생성 64자 hex)

브라우저 localStorage (서버 DB 아님):
- `interionote.token` — JWT 토큰 (v3.0.0)
- `interionote.user` — `{username, display_name, role}` JSON (v3.0.0)
- `interionote.dismissed_until_version` — 시작 팝업 dismiss 추적

---

## 📜 Phase 진행 이력 (현재까지)

### v1 (실패, 전체 삭제됨)
- ECAPA 화자 자동 판별 시도 → 실패 → 전면 재설계

### Phase 1~2 v2 — 뼈대 + 실시간 파이프라인 ✅
### Phase 3 (3A~3D) — 상담 통합 ✅
### Phase 4 — Ollama AI 분석 ✅
### Phase 5A — 설정 페이지 ✅
### Phase 5B — 노이즈 억제 (silero-denoise) ✅
### Phase 5B-extra — Whisper 반복 환각 필터 ✅
### Phase 5C — Two-pass 재전사 ✅
### Phase 6 (6A~6C) — 사용자화·팝업·과거 상담 보기 ✅ (v2.2.0)
### Phase 7A — 데이터 디렉터리 분리 ✅ (v2.3.0)
### Phase 7B-1 — PyInstaller 빌드 ✅ (v2.4.0 계열)
### Phase 7B-2 — Inno Setup 인스톨러 🔶 (per-user install 전환 보류)
### Phase 7B-3 — 자동 업데이트 확인 ✅

### v2.5.x~v2.8.1 — 대규모 기능 추가 ✅
- 다크 모드, 카드 검색, AI 배지, 오디오 점프, 전체 대화 복사 (v2.5.x)
- 통계, 빠른 메모, AI 분석 사전 체크 (v2.5.1+)
- 고객 360뷰, OJT 동기화, 태그, 진행률, PDF (v2.6.0)
- 마이크 점검, 빠른 답변 템플릿, 데이터 백업, 최근 본 상담, 시작 가이드 (v2.7.0)
- 견적서 자동 작성, 통합 검색, 통계 차트 (v2.8.0)
- 통계 도넛 차트 픽스 (v2.8.1)

### **v3.0.0 Phase 1** — 고객 연락처 + 카톡 문구 + 홈 필터 ✅ (2026-05-03)
- clients 테이블에 `phone`, `visit_source` 컬럼 추가
- 신규 고객 모달에 전화번호·방문경로 입력 필드
- 상담 종료 후 카톡 안내 문구 자동 생성·복사
- 홈 단계 필터 (초도/디자인/견적/계약/시공/완료) + 전화번호 검색
- 설정 → 일반 탭에 담당자 정보 섹션 (이름·매장명·연락처)

### **v3.0.0 Phase 2** — 로그인 + 사용자 관리 ✅ (2026-05-03)
- users DB 테이블 신규
- JWT 인증 미들웨어 (`_AuthMiddleware`)
- 로그인 페이지 (`login.html`, `/login`)
- `auth_service.py`, `auth.py`, `users.py` 신규
- 모든 HTML 파일에 fetch 오버라이드 + 즉시 토큰 확인 스크립트 주입
- 설정 → 사용자 관리 탭 (마스터 전용)
- **사용자 검증**: "정상작동 확인"

---

## 🔧 실행 방법

### 개발 모드
1. `C:\InterioNote\dev.bat` 더블클릭
2. 최초 1회 자동 pip install
3. pywebview 네이티브 창 오픈 → **로그인 화면** 자동 표시
4. `admin` / `1234` 로 로그인
5. 홈 → 고객 선택 → 상담 종류 → 녹음

### 빠른 동작 체크리스트 (v3.0.0)
- ✅ 로그인 화면이 가장 먼저 뜸
- ✅ admin / 1234 로 로그인 → 홈 이동
- ✅ 설정 → 사용자 관리 탭 (마스터에게만 보임)
- ✅ 일반 탭에 "👤 내 계정" 섹션 (로그아웃 + 비밀번호 변경)
- ✅ 고객 카드에 전화번호 표시 + 전화번호 검색 동작
- ✅ 상담 종료 후 카톡 문구 버튼 표시·복사
- ✅ 홈 단계 필터 동작

---

## 🐛 알려진 이슈 & 해결 기록

### 1~13. (기존 이슈 — 모두 해결됨 또는 문서화됨)
요약: Python 3.14 호환성, .bat 한글, ECAPA 실패, OneDrive 충돌, silero 의존성, DeepFilterNet Rust, BufferedDenoiser, 32kHz 출력, medium 실시간 불가, Whisper 환각, view-mode 매핑.

### 14. (Phase 7B-2) Inno Setup OOM
`lzma2/ultra64` → `lzma2/max + LZMANumBlockThreads=1 + LZMAUseSeparateProcess=yes` 로 해결.

### 15. (Phase 7B-2) ISCC.exe 비표준 경로
`C:\Program Files\InterioNote\ISCC.exe` (사용자가 Inno Setup 설치 경로를 InterioNote 로 지정). `make_installer.bat` 가 자동 탐지.

### 16. (Phase 7B-2) 설치된 exe 실행 안 됨
Program Files 위치에서 Defender 차단 추정. per-user install 전환 권장 (`{localappdata}\Programs\`).

### 17. (v3.0.0 Phase 2) passlib + bcrypt 5.x 비호환 (해결됨)
- **증상**: `passlib 1.7.4` 가 `bcrypt 5.x` 내부 API 변경으로 로드 실패 → "password cannot be longer than 72 bytes" (4글자 비밀번호인데도)
- **원인**: bcrypt 5.0.0이 `__about__.__version__` 제거 → passlib 폴백 모드에서 오동작
- **해결**: `passlib.context.CryptContext` 제거, `import bcrypt as _bcrypt` 직접 사용
  ```python
  _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")
  _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
  ```
- `requirements.txt`: `passlib[bcrypt]==1.7.4` 제거, `PyJWT==2.10.1` 추가

---

## 📋 워크플로우 규칙 (계속 유효)

1. **Phase 단위 중단 원칙**: 각 Phase 완료 후 멈추고 사용자 검증 받기
2. **비개발자 친화 명령**: cmd 한 줄 복붙 또는 더블클릭 .bat
3. **에러 원인 노출**: HTTP 500 detail 에 예외 타입+메시지 400자, cmd 에 traceback 전체
4. **프리뷰 패널 알림**: HTML 편집 시 hook 알림 → 응답에 "프리뷰 패널에 표시되어 있습니다" 명시
5. **삭제는 확인 후**: 업무 폴더(`Livart&문테리어\`) 절대 삭제 금지
6. **솔직한 한계 인정**: 매장 음악처럼 소프트웨어로 한계 있는 부분은 하드웨어 솔루션 정직하게 안내
7. **CHANGELOG 규칙**: `version.json` changelog 는 반드시 디자이너 관점으로 작성. 기술적 세부사항은 한 줄 "🔧 안정성 개선" 으로 묶기.

---

## ⏭ 다음 세션에서 바로 할 것

### ✅ v3.0.0 Phase 1+2 완료 상태
- Phase 1 (연락처, 카톡, 필터): ✅ 완료 + 검증
- Phase 2 (로그인, 사용자 관리): ✅ 완료 + 검증 ("정상작동 확인")

### 🔶 남아있는 즉시 할 항목

1. **`build_update_zip.py` MIN_APP_VERSION 갱신**
   - 현재: `"2.8.1"` → 변경 후: `"3.0.0"`
   - 이유: Phase 2 로그인 시스템이 추가되어 이전 버전 클라이언트는 호환 불가
   - 파일 경로: `C:\InterioNote\build_update_zip.py` (또는 유사한 파일명 확인)

2. **Inno Setup per-user install 전환** (Phase 7B-2 마무리)
   - `.iss` 변경: `DefaultDirName={localappdata}\Programs\{#MyAppName}`, `PrivilegesRequired=lowest`
   - `make_installer.bat` 재실행 → 새 `InterioNoteSetup-3.0.0.exe` 생성

3. **GitHub Releases v3.0.0 생성**
   - 기존 v2.3.0 release 에는 자산 미첨부 상태
   - 새 v3.0.0 release 만들고 인스톨러 자산 업로드

### 📌 그 다음 가능한 작업 (사용자 피드백 기반)
- **v3.0.0 Phase 3**: 미정 (사용자 요청 대기)
- 매장 실사용 피드백 기반 버그픽스
- PDF 생성 (weasyprint, 한글 폰트) — 오래 보류 중
- 인식률 개선 (하드웨어 마이크 도입이 가장 효과적)

### 첫 메시지 권장
**"v3.0.0 정상 확인됐어요! build_update_zip.py 버전 올리고, 인스톨러 새로 만들어서 GitHub 에 올리면 v3.0.0 배포 완료됩니다. 진행할까요?"**

### 흔한 피드백 시나리오 + 대응

| 피드백 | 대응 |
|---|---|
| "매장 음악 때문에 인식 50% 정도" | **하드웨어 마이크 강력 추천** (BOYA BY-M1 ₩25k~30k USB 라발리에). 소프트웨어 한계 정직하게. |
| "AI 분석에 다른 항목 추가" | `analysis_prompts.py` 의 SCHEMAS 편집 |
| "이전 상담 검색" | `/search` 페이지 이미 있음 (v2.8.0) |
| "직원 추가하고 싶다" | v3.0.0 Phase 2 사용자 관리 탭 사용 |
| "다중 PC 동기화" | OneDrive 폴더로 CLIENT_ROOT 설정 권장 (이미 가능) |

### 새 기능 추가 시 워크플로우
1. 코드 변경 + 검증
2. `version.json` 의 `version` 올림 (Patch/Minor/Major)
3. `version.json` 의 `changelog` 맨 위에 `{version, date, title, items}` 추가 (디자이너 관점)
4. 사용자 다음 실행 시 자동으로 시작 팝업으로 안내됨

---

## 🔗 경로 참조 요약

| 용도 | 경로 |
|---|---|
| 프로그램 본체 | `C:\InterioNote\` |
| 실행 런처 | `C:\InterioNote\dev.bat` |
| DB | `%APPDATA%\InterioNote\data\interionote.db` |
| 버전·변경이력 | `C:\InterioNote\version.json` |
| Whisper 캐시 | `%LOCALAPPDATA%\InterioNote\models_cache\whisper\` |
| Silero 캐시 (vad+denoise) | `%LOCALAPPDATA%\InterioNote\models_cache\torch_hub\` |
| 임시 녹음 | `%LOCALAPPDATA%\InterioNote\temp_recording\` |
| 고객 폴더 루트 | settings DB `paths.client_root` 참조 |

---

## 📝 작업 이력 타임라인 (요약)

- **초반 기획** — 4종 → 3종 + 화자 자동 판별 → 수동 토글
- **Phase 1~2 v1** — ECAPA 도전 → 실패 → 전면 삭제
- **v2 재설계** — 경량화 + .exe 배포 목표
- **Phase 1~3** — 뼈대, 파이프라인, 상담 통합, 화자 토글
- **Phase 4** — Ollama qwen2.5:3b 분석
- **Phase 5A~5C** — 설정, 노이즈 억제, 환각 필터, Two-pass 재처리
- **Phase 6** — 사용자화, 팝업, 과거 상담 보기 (v2.2.0)
- **Phase 7** — 데이터 분리, PyInstaller, Inno Setup, 자동 업데이트 확인 (v2.3.0~)
- **v2.5.x~v2.8.1** — 대규모 기능 추가 (다크모드, OJT, 견적서, 검색 등)
- **PC 마이그레이션** (2026-04-26) — b0463 노트북 → tmdqo 데스크탑, OneDrive 동기화
- **v3.0.0 Phase 1** (2026-05-03) — 연락처, 카톡 문구, 홈 필터, 담당자 설정
- **v3.0.0 Phase 2** (2026-05-03) — JWT 로그인, 사용자 관리, bcrypt, 인증 미들웨어
- **이 AGENTS.md 갱신** (Phase 2 완료 시점)

---

## 🚨 다음 Codex 에게 마지막 당부

1. **이 문서를 끝까지 읽은 후** 자연스럽게 이어가기 ("v3.0.0 잘 동작하고 계세요?" 등).
2. **사용자가 명시적으로 요청하기 전까지 새 Phase 코드 작성 금지**.
3. **비개발자**임을 잊지 마세요 — 한 줄씩 안내, 에러 시 창 자동 안 닫히게, 전체 로그 공유 요청.
4. **솔직한 한계 인정**: 음악 환경 인식률, CPU 한계, 모델 다운로드 시간 등.
5. 코드 수정 시 기존 패턴 준수:
   - Tailwind CDN + Alpine.js (React 금지)
   - FastAPI 라우터 분리, 한국어 주석, 예외 타입명 노출
   - 새 설정은 `settings_service` + `/api/settings` + `settings.html` 3 곳에 일관되게
   - 새 모델은 `config.MODELS_CACHE_DIR`
   - v3.0.0: 모든 `/api/` 엔드포인트는 `request.state.user` 로 인증 사용자 접근 가능
6. **인증 관련 주의**: `/api/app/quick-update/run` 같은 유지보수 endpoint 는 이제 인증 필요. 화이트리스트에 추가하려면 `server.py` 의 `_AUTH_WHITELIST` 수정.

---

_이 문서는 v3.0.0 Phase 2 (로그인 + 사용자 관리) 완료 후 갱신되었습니다. (2026-05-03)_
_사용자 검증: "정상작동 확인"_
_핵심 미해결: Inno Setup per-user install 전환 + GitHub v3.0.0 release + build_update_zip.py MIN_APP_VERSION 갱신_
