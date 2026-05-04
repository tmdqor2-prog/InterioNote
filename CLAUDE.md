# InterioNote 프로젝트 — Claude Code 세션 인수인계

> **다음 세션의 Claude에게**: 이 파일은 이전 Claude가 사용자와 나눈 대화의 전체 맥락입니다.
> 사용자는 처음부터 다시 설명하지 않아도 되도록, 이 파일을 먼저 끝까지 읽고 작업을 이어가 주세요.
> 마지막 섹션 **"⏭ 다음 세션에서 바로 할 것"** 부터 확인하면 재개 지점이 명확합니다.

---

## 👤 사용자 프로파일

- **직업**: 인테리어 디자이너 1인 (Livart&문테리어 소속 / 개인 사업 병행)
- **기술 수준**: 비개발자. Windows cmd 복붙 가능 수준. 코드는 읽지 못함.
- **사용 PC (현재)**: 데스크탑 (tmdqo 계정). 이전 ASUS Vivobook Go 15 (b0463 계정) 에서 이동 완료.
  - OneDrive 동기화로 고객 데이터 이관됨
  - Python 3.12 재설치 필요 여부는 미확인 (venv 는 C:\InterioNote\ 안에 있음)
- **이메일**: tmdqor2@gmail.com
- **Ollama**: 설치 완료 + `qwen2.5:3b` 다운로드 완료 (1.9GB, Q4_K_M)
- **GitHub**: `tmdqor2-prog` 계정 + Public repo `tmdqor2-prog/InterioNote` 생성됨
  - v2.8.0 Release 배포됨 (인스톨러 + update zip 첨부)
- **Inno Setup 6**: 설치됨. ⚠️ 비표준 경로 — `C:\Program Files\InterioNote\ISCC.exe`
  - `make_installer.bat` 가 이 경로를 자동 탐지함

### 중요한 소통 규칙
1. **비개발자**이므로 모든 명령은 **cmd.exe 복붙 가능** 형태로 제공
2. **한 줄씩** 안내 (여러 줄 붙여넣기 하다 실수하는 경우가 있었음)
3. `%PROMPT%` 같은 쉘 프롬프트 표시를 복사하지 않도록 주의 안내
4. 에러 발생 시: **전체 cmd 로그 복사 + 스크린샷 요청**, 혼자 디버깅 가정 금지
5. **한글로 응답** (기본)
6. 큰 기능은 Phase 단위로 작업을 끊고 **사용자 검증** 후 다음으로
7. 긴 설명 필요할 때는 긴 답변 허용 (설치 안내/검증 체크리스트 등)
8. **솔직한 한계 인정** — 소프트웨어로 풀 수 없는 문제(예: 배경 음악)는 하드웨어 솔루션을 정직하게 안내
9. **CHANGELOG는 디자이너 관점**으로 작성 — 기술 용어 금지, 1줄 이모지 설명, 기술 수정은 "🔧 프로그램 안정성 개선" 하나로 묶기

---

## 🎯 프로젝트 개요

### 이름
**InterioNote** — 인테리어 상담 실시간 녹음·분석 프로그램 (완전 로컬, 1인 사용 전용)

### 목적
- 고객 상담 **녹음**
- 발화 단위로 **실시간 한국어 전사** (화자 구분은 자동 안 함, 녹음 중·후 수동 토글)
- 상담 종류별 **AI 분석 리포트** (요약·체크리스트·액션아이템) 생성
- 고객별 폴더에 **자동 파일 배치** (MP3, WAV 원본, 대화전문 MD, 분석 JSON, 요약 MD, 상담정보 JSON)
- 고객 360 뷰, OJT 자동 동기화, 견적서 초안 자동 작성, 통합 검색 (v2.6+)

### 상담 종류 (3종 고정)
1. **초도상담** — 매장에서 고객 처음 응대
2. **디자인미팅** — 실측 후 디자인 안 설명
3. **견적미팅** — 견적 제시/협의

### 절대 제약
1. **비용 0원** — 외부 API 절대 금지 (Whisper·Ollama·silero 전부 로컬)
2. **100% 로컬** — 모델 최초 다운로드 외 오프라인 동작
3. **CPU-only 원칙** (선택적 GPU 지원 v2.4.0~) — int8 양자화
4. **한국어 중심** — 인테리어 전문용어 처리 최우선

---

## 🏠 실제 운영 환경

### 고객 폴더 루트
- **settings DB 에서 관리** (Phase 6A): `/api/settings` 의 `paths.client_root`
- 기본 fallback: `C:\Users\{user}\Documents\Livart&문테리어\07_고객정보`
- PC 이동 후 settings DB 에 저장된 경로가 자동 사용됨 (config.py 수정 불필요)

### 매장 환경 특성 (중요!)
- **백화점 매장에서 사용** → 천장 스피커에서 음악이 계속 흘러나옴
- **노트북 내장 마이크** 사용 (라발리에 마이크 도입 보류 중)
- 음악이 사람 목소리 주파수와 겹쳐 인식률에 영향. 소프트웨어로 부분 완화:
  - silero-denoise (제한적 효과)
  - VAD threshold 상향 (0.65 권장)
  - Whisper 반복 환각 필터
  - 녹음 시작 전 마이크 레벨 미터 (v2.7.0 신설)
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
├── 녹음원본.wav          ← 16kHz 모노 int16, 재전사용 보존
├── 대화전문.md           ← 타임스탬프 + 화자라벨 + 텍스트
├── 상담정보.json         ← 메타데이터
├── 분석결과.json         ← qwen 원본 응답 (AI 분석 후)
├── 요약.md               ← 사람이 읽기 좋게 정리된 분석 (AI 분석 후)
└── 견적초안_YYYYMMDD.xlsx  ← 견적서 초안 (v2.8.0, 선택)
```

같은 날짜·종류가 중복되면 `2026-04-25_초도상담_2`, `_3` 등으로 증가.

---

## 🏗 기술 스택 (현재 상태)

| 레이어 | 선택 | 비고 |
|---|---|---|
| 웹 서버 | FastAPI 0.115 + uvicorn | 내부 localhost 전용 |
| 네이티브 창 | **pywebview 5.3** (Edge WebView2) | 브라우저 X, 독립 앱 창 |
| DB | SQLite + WAL | `%APPDATA%\InterioNote\data\interionote.db` |
| 녹음 | sounddevice 0.5 + soundfile 0.12 | 16kHz mono int16, 100ms 블록 |
| VAD | **silero-vad 5.1 (ONNX)** | 발화 구간 분리, 사용자 threshold 조절 |
| **노이즈 억제** | **silero-denoise (small_slow)** | 500ms 버퍼링, 32→16kHz 다운샘플 |
| STT (실시간) | **faster-whisper small int8** | 한국어, beam=5 |
| STT (재처리) | **faster-whisper medium/large-v3 int8** (선택) | Two-pass 정확도 향상 |
| LLM | **Ollama + qwen2.5:3b** | format=json, 상담 종류별 프롬프트 |
| MP3 인코딩 | **lameenc 1.7.0** | 외부 ffmpeg 불필요 |
| HTTP 클라이언트 | httpx | Ollama + GitHub API 호출 |
| 엑셀 처리 | **openpyxl** | OJT 파싱·쓰기, 견적서 템플릿 채우기 |
| MD 처리 | **markdown** | PDF 인쇄용 HTML 변환 |
| 차트 | **Chart.js** CDN | 통계 도넛·라인 차트 |
| **배포** | **PyInstaller 6.11.1 (--onedir) + Inno Setup 6** | per-user install (`%LOCALAPPDATA%\Programs\InterioNote\`) |
| 자동 업데이트 | GitHub Releases API + httpx + in-app zip 업데이트 | 인앱 빠른 업데이트 (v2.4.0) + GitHub 확인 |
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
- **torchaudio 2.4.1**: `pip install torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cpu`
- **requests**: faster-whisper 의 huggingface_hub 가 요구. 별도 설치됨.

---

## 🔢 버전 관리 규칙 (⚠️ 3파일 동시 갱신 필수)

기능 추가 또는 패치 후 배포 시 **반드시 3개 파일을 동시에 수정**해야 함:

1. **`app/version.json`** — `"version": "X.Y.Z"` + changelog 배열 맨 위에 항목 추가
2. **`InterioNoteSetup.iss`** — `#define MyAppVersion "X.Y.Z"` 갱신
3. **`build_update_zip.py`** — `MIN_APP_VERSION = "X.Y.Z"` 갱신 (업데이트 zip 의 최소 요구 버전)

> 이전 세션에서 iss 파일만 수동으로 업데이트 안 해서 사용자가 불만을 표명한 사례가 있었음.
> Claude가 version.json 올릴 때 iss + build_update_zip.py 도 자동으로 같이 갱신해야 함.

CHANGELOG 작성 규칙:
- 디자이너 관점, 기술 용어 금지
- 각 항목은 이모지 + 한 줄 설명
- 내부 기술 수정은 `"🔧 프로그램 안정성 개선"` 하나로 묶기

---

## 📂 프로젝트 파일 구조 (`C:\InterioNote\`)

```
C:\InterioNote\
├── InterioNote.py              ← 진입점 (pywebview + FastAPI 스레드 + JsBridge)
│                                  JsBridge: pick_folder / open_in_explorer / open_external_url / get_data_paths
├── dev.bat                     ← 개발용 런처 (Python 3.12 검사 + venv + 서버 실행)
├── build.bat                   ← PyInstaller 빌드 더블클릭 런처
├── build-installer.bat         ← Inno Setup 컴파일 더블클릭 런처 (최신, ISCC 자동 탐지)
├── make_installer.bat          ← 구버전 인스톨러 런처 (build-installer.bat 와 동일 기능)
├── build_update_zip.py         ← in-app 업데이트 zip + manifest 생성 스크립트
│                                  ⚠️ MIN_APP_VERSION 버전 bump 시 반드시 갱신
├── InterioNote.spec            ← PyInstaller 스펙
├── InterioNoteSetup.iss        ← Inno Setup 스크립트 (per-user install, %LOCALAPPDATA%\Programs\)
│                                  ⚠️ MyAppVersion 버전 bump 시 반드시 갱신
├── Output\                     ← Inno Setup / update zip 산출물
│   ├── InterioNoteSetup-2.8.0.exe   ← 현재 배포 인스톨러 (약 200MB, lzma2/max)
│   ├── InterioNote-update-2.8.0.zip ← in-app 업데이트 zip
│   └── update-manifest-2.8.0.json  ← 업데이트 매니페스트
├── requirements.txt            ← 모든 의존성 (v2.8.0 기준)
├── CLAUDE.md                   ← ⬅ 이 파일. 세션 인수인계.
├── venv\                       ← Python 가상환경 (.gitignore 대상)
└── app\
    ├── __init__.py
    ├── version.json            ← APP_VERSION + CHANGELOG (단일 진실 소스)
    │                              ⚠️ 버전 bump 시 여기가 1번
    ├── config.py               ← 경로/상담종류/기본 설정값. APP_VERSION 은 version.json 에서 로드.
    ├── server.py               ← FastAPI create_app() 팩토리 (91 routes, v2.8.0)
    ├── db.py                   ← SQLite 스키마 + 커넥션 헬퍼 (v2.6.0 마이그레이션 포함)
    ├── api\
    │   ├── home.py             ← /api/clients, /api/meta, /clients/new, /preview-folder-name, /ensure-template
    │   ├── meetings.py         ← /api/meetings/new, /{id}, /{id}/segments, /{id}/audio, /{id}/retranscribe
    │   ├── recording.py        ← /api/recording/start|stop|state|warmup|segments
    │   ├── streaming.py        ← /ws/live WebSocket
    │   ├── analyses.py         ← /api/meetings/{id}/analyze, /analysis, /api/ollama/health
    │   ├── settings.py         ← /api/settings + /whisper /vocab /noise-suppression /vad
    │   ├── stats.py            ← /api/stats (월별 · 종류별 통계)
    │   ├── pdf.py              ← /api/meetings/{id}/print-summary, /print-transcript (window.print)
    │   ├── customer.py         ← /api/clients/{id}/360, /{id}/aggregate-summary
    │   ├── ojt.py              ← /api/ojt/* (설정·분석·미리보기·동기화)
    │   ├── quick_replies.py    ← /api/quick-replies CRUD
    │   ├── backup.py           ← /api/backup/create, /backup/path
    │   ├── quote.py            ← /api/quote/* (설정·분석·미리보기·생성)
    │   └── search.py           ← /api/search?q=, /api/search/reindex, /api/search/status
    ├── services\
    │   ├── audio_recorder.py           ← sounddevice 래퍼 (Recorder 클래스)
    │   ├── vad_service.py              ← StreamingVAD (silero, 512샘플)
    │   ├── whisper_service.py          ← live + post 모델 캐시, 환각 필터
    │   ├── live_session.py             ← 오케스트레이터 (3스레드 파이프라인 + BufferedDenoiser)
    │   ├── noise_suppression_service.py ← silero-denoise + BufferedDenoiser (500ms, 32→16kHz)
    │   ├── mp3_encoder.py              ← lameenc 래퍼
    │   ├── client_service.py           ← upsert_client_by_folder
    │   ├── meeting_finalizer.py        ← 녹음 종료 후처리 (MP3, MD, JSON, WAV 원본 보존)
    │   ├── retranscribe_service.py     ← Two-pass 재전사 + 화자 라벨 이관 + DB/MD 재생성
    │   ├── ollama_client.py            ← httpx 기반 Ollama 클라이언트
    │   ├── analysis_prompts.py         ← 상담 종류별 JSON 스키마 + 시스템 프롬프트
    │   ├── analysis_service.py         ← 분석 오케스트레이터 + render_summary_md
    │   ├── settings_service.py         ← 모든 사용자 설정 타입 안전 래퍼
    │   ├── system_specs.py             ← PC GPU/RAM 사양 감지 (추천 모델 계산용)
    │   ├── quick_update_service.py     ← in-app 빠른 업데이트 (zip 다운 + 교체 + 재시작)
    │   ├── text_polish.py              ← 한국어 문장 부호 자동 보정
    │   ├── folder_rename.py            ← AI 분석 후 고객 폴더명 수정 제안
    │   ├── tags_service.py             ← 태그 CRUD (meeting_tags 테이블)
    │   ├── stage_service.py            ← 계약 진행 단계 (clients.stage)
    │   ├── ojt_service.py              ← OJT 엑셀 동기화 (openpyxl 기반)
    │   ├── quick_replies_service.py    ← 빠른 답변 템플릿 CRUD
    │   ├── quote_service.py            ← 견적서 초안 생성 (템플릿 복사 + 셀 매핑)
    │   └── search_service.py          ← FTS5 통합 검색 (전사/메모/AI분석 인덱싱)
    ├── utils\
    │   ├── folder_scanner.py           ← 고객 폴더 자동 스캔
    │   └── folder_template.py          ← ensure_client_template
    └── static\
        ├── index.html          ← 홈 (고객 목록, 즐겨찾기, 최근 본 상담, 온보딩 튜토리얼, 검색 링크)
        ├── live.html           ← 실시간 녹음·전사·라벨링·재처리·AI분석·OJT·견적·PDF·마이크미터
        ├── settings.html       ← 설정 (7탭: 일반/사용자폴더/음성인식/키워드/OJT연동/견적서양식/답변템플릿)
        ├── stats.html          ← 상담 통계 (월별 라인 + 종류별 도넛 차트, Chart.js)
        ├── customer.html       ← 고객 360 뷰 (타임라인, 누적 AI 요약, 즐겨찾기, 단계 변경)
        ├── search.html         ← 통합 검색 (전사/메모/AI분석 FTS5, 카테고리별 결과)
        └── quick_note.html     ← 빠른 음성 메모 (고객 폴더 없이 짧게 녹음)
```

---

## 🗄 DB 스키마

### clients
`id, name, descriptor, folder_name UNIQUE, folder_path UNIQUE, first_met_at, created_at, notes`

**v2.6.0 추가 컬럼:**
- `stage TEXT DEFAULT '초도'` — 계약 진행 단계 (초도/디자인/견적/계약/시공/완료)
- `is_favorite INTEGER DEFAULT 0` — 즐겨찾기 (1=활성)
- `last_meeting_at DATETIME` — 마지막 상담 일시 (정렬용)

### meetings
`id, client_id FK, meeting_type, started_at, ended_at, duration_sec, meeting_folder, audio_file, temp_folder, status`
- `meeting_type`: 초도상담 | 디자인미팅 | 견적미팅
- `status`: pending | recording | recorded | analyzing | done | failed

**v2.6.0 추가 컬럼:**
- `ojt_synced_at DATETIME` — OJT 마지막 동기화 일시

### transcript_segments
`id, meeting_id FK, start_ms, end_ms, text, speaker NULL, confidence`
- `speaker`: 'me' | 'client' | NULL

### analyses
`id, meeting_id UNIQUE FK, data_json, model_used, created_at`

### meeting_tags (v2.6.0 신설)
`id, meeting_id FK, tag TEXT`

### quick_replies (v2.7.0 신설)
`id, title TEXT, content TEXT, category TEXT, sort_order INTEGER`

### settings (Phase 5A + 6A 활용)
`key PRIMARY KEY, value`

저장되는 키들:
- `whisper.model_size` (default: small)
- `whisper.beam_size` (default: 5)
- `whisper.interior_vocab` (사용자 편집 가능)
- `noise.suppression_enabled` (default: false)
- `vad.threshold` (default: 0.5, 매장 환경 권장 0.65)
- `paths.client_root` — 고객 폴더 루트 (절대 경로)
- `paths.folder_template` — 서브폴더 템플릿 (JSON list)
- `ojt.config` — OJT 파일 경로 + 컬럼 매핑 (JSON)
- `quote.config` — 견적서 템플릿 경로 + 셀 매핑 (JSON)

### FTS5 가상 테이블 (search_service 초기화 시 생성)
- `transcript_search` — 전사 텍스트 인덱스
- `notes_search` — 메모 인덱스
- `analysis_search` — AI 분석 인덱스

브라우저 localStorage (서버 DB 가 아님):
- `interionote.dismissed_until_version` — 시작 팝업 dismiss 추적
- `interionote.retranscribe_model` — 마지막으로 선택한 재처리 모델
- `interionote.sort_order` — 홈 고객 목록 정렬 순서
- `interionote.recent_meetings` — 최근 본 상담 5건 (JSON list)
- `interionote.onboarding_done` — 온보딩 튜토리얼 완료 여부

---

## 📜 Phase 진행 이력

### v1 (실패, 전체 삭제됨)
- Phase 1~2 v1 동작했으나 Phase 3 v1 (ECAPA 화자 자동 판별) 실패 → 전면 재설계

### Phase 1~2 v2 — 뼈대 + 실시간 파이프라인 ✅
- FastAPI + pywebview + SQLite + 고객 자동 스캔
- 3스레드 큐 파이프라인 (audio_q → speech_q → segments)

### Phase 3 — 상담 통합 ✅
- 신규 고객 생성, 상담 시작 플로우, 녹음 종료 후처리, 화자 토글

### Phase 4 — Ollama AI 분석 ✅
- qwen2.5:3b 호출, 상담 종류별 JSON 스키마, 분석결과.json + 요약.md

### Phase 5A — 설정 페이지 인프라 ✅
- Whisper 모델 선택, 키워드 사전, VAD threshold, 노이즈 억제 토글

### Phase 5B — 노이즈 억제 ✅
- silero-denoise, BufferedDenoiser (500ms 버퍼링), 32→16kHz Resample

### Phase 5B-extra — Whisper 반복 환각 필터 ✅
- 음악 입력 시 `작품, 작품, ...` 같은 반복 출력 자동 폐기

### Phase 5C — Two-pass 재전사 ✅
- 실시간 small + 종료 후 medium 재처리, 화자 라벨 시간 겹침 자동 이관

### Phase 6 (v2.1.0~v2.2.0) ✅
- **6A**: 저장 위치/폴더 템플릿 사용자 설정 + 네이티브 폴더 선택 다이얼로그
- **6B**: APP_VERSION + CHANGELOG + 시작 환영 팝업 (localStorage dismiss + 버전 변경 재표시)
- **6C**: 작업 선택 모달 (신규/기존) + 과거 상담 목록 + view-mode + 오디오 재생

### Phase 7 (v2.3.0) ✅ — 데이터 분리 + 자동 업데이트 + 배포
- **7A**: 데이터 디렉터리 분리 (`%APPDATA%\InterioNote\`, `%LOCALAPPDATA%\InterioNote\`)
- **7B-3**: GitHub Releases API 자동 업데이트 확인 + 앱 제거 안내
- **7B-1**: PyInstaller --onedir 빌드
- **7B-2**: Inno Setup 인스톨러 (per-user install, `%LOCALAPPDATA%\Programs\InterioNote\`)
  - Defender 이슈로 Program Files 포기 → per-user 전환으로 해결

### v2.4.0 — GPU 지원 + 카드 직접 편집 + 인앱 빠른 업데이트 ✅
- NVIDIA GPU 자동 감지 + GPU/CPU 선택 인스톨러
- 전사 카드 클릭 직접 수정 (정확도 재처리 후에도 수동 편집 카드 보존 📝)
- AI 분석 결과 카드도 직접 편집 가능
- 정확도 재처리 결과 복원 버튼 (한 클릭 이전 상태 복원)
- 인앱 빠른 업데이트: 작은 변경은 인스톨러 없이 app zip 교체만으로 적용
- 카드 시간 클릭 → 오디오 해당 구간 점프 (v2.4.1)

### v2.4.3~2.4.6 — 안정화 패치 ✅
- CHANGELOG 비개발자 친화적 정리 규칙 확립
- 정확도 재처리 `Bad file descriptor` OSError 해결
- 진단 로그 기록 방식 안정화

### v2.5.0 — 다크 모드 + 카드 검색 + 설정창 탭 ✅
- 다크/라이트/시스템 테마 (설정 → 일반)
- 설정창 5탭 분리 (일반/사용자폴더/음성인식/키워드/단축키)
- 카드 텍스트 / 키 검색 (매치된 카드 노란 강조)
- AI 분석 결과 클립보드 복사 (섹션별 + 전체)
- 재전사 모델 선택 localStorage 기억
- 홈 고객 목록 정렬 (최근활동/이름/상담건수)

### v2.5.1 — 상담 메모 + AI 분석 강화 + 폴더명 제안 + 통계 ✅
- 상담 메모 영역 (DB 자동 저장)
- AI 분석에 인테리어 장소 정보 추가 (주소·아파트명·평형 등)
- 분석 후 고객 폴더명 수정 제안 (수락/거절/편집)
- 한국어 문장 부호 자동 보정 (text_polish.py)
- 상담 통계 페이지 `/stats` (월별 건수, 종류별 분포, TOP 5)
- 빠른 음성 메모 `/quick-note` (고객 폴더 없이 짧게 녹음)
- 단축키 도움말 F1 (기존 ? → F1, 한국어 키보드 호환)

### v2.5.2~2.5.4 — UX + 다크 모드 + 작업표시줄 ✅
- 녹음 종료 버튼 sticky 고정
- 녹음 중 빨간 펄스 테두리 + 새 카드 도착 애니메이션
- 작업표시줄 cmd 창 완전 제거 (pywebview console 분리)
- 다크 모드 시인성 대폭 개선

### v2.5.5 — 환영 화면 Wi-Fi/Ollama 안내 ✅
- 처음 사용 시 Wi-Fi 필요 안내 + Ollama 자동 감지
- `checkOllamaHealth()`: checking / ok / no_ollama / no_model 상태

### v2.5.6 — AI 분석 사전 체크 + 오디오 워크플로 개선 ✅
- AI 분석 시작 전 Ollama 상태 자동 사전 체크 모달
- 모든 화면 헤더에 Ollama 미니 배지 (🟢/🟡/🔴)
- 오디오 재생 ±5초 점프 버튼 + 속도 조절 (0.75x~2x)
- 완료 화면 '전체 대화 복사' 버튼
- 녹음 화면 도움말 버튼 (F1 대체)

### v2.6.0 — 고객 360 뷰 + OJT + 태그 + 진행률 + PDF ✅
- **고객 360 뷰** (`/customer?id=X`): 타임라인·누적 AI 요약·즐겨찾기·단계 변경
- **OJT 엑셀 자동 동기화**: 상담 후 한 클릭으로 디자이너 OJT 파일에 한 줄 추가
  - 컬럼 매핑 마법사 (설정 → OJT 연동 탭), 동기화 전 미리보기·수정
- **태그 시스템**: 상담별 자유 태그 (`#확장` `#화이트톤` 등), 360 뷰에 누적 표시
- **계약 진행률**: 초도→디자인→견적→계약→시공→완료, 홈 카드에 배지
- **즐겨찾기 고객**: 홈 상단 고정, 별표 한 클릭 토글
- **PDF 출력**: AI 요약/전체 대화 → `window.print()` (Microsoft Print to PDF)
- DB: `meeting_tags`, `quick_replies`, `clients.stage/is_favorite/last_meeting_at`, `meetings.ojt_synced_at`
- openpyxl, markdown 의존성 추가

### v2.6.1 — OJT 확장 + PDF 네비게이션 + 누적 요약 픽스 ✅
- OJT 동기화를 모든 상담 (기존 고객 디자인·견적)에서도 가능
- 이미 OJT 등록된 고객 감지 + 재등록 버튼
- PDF 인쇄 페이지 상단 툴바 [← 뒤로 / 🏠 홈 / 📄 PDF 저장] + ESC 키
- **누적 AI 요약 TypeError 픽스**: `ollama_client.generate(model=..., prompt=..., system=..., format_json=False)` 시그니처 + dict 응답에서 `response` 키 추출

### v2.7.0 — 마이크 미터 + 답변 템플릿 + 데이터 백업 + 최근 본 상담 + 온보딩 ✅
- **마이크 레벨 미터** (D): WebAudio API + dB 대수 스케일 + peak hold
- **빠른 답변 템플릿** (Q): 자주 쓰는 문구 등록 + 한 클릭 클립보드 복사
- **데이터 수동 백업** (U): DB+설정+OJT 매핑+진단 로그 → zip 저장 + 복원 안내 README
- **최근 본 상담 5건** (P-extra): 홈 상단 사이드바, localStorage
- **온보딩 튜토리얼** (V): 첫 실행 시 5단계 가이드 자동 노출
- OJT 기존 고객 이미 등록됨 표시 (v2.6.1 과 중복 주의: 최종 버전이 v2.7.0)
- 통계 페이지 Chart.js 도넛·라인 차트

### v2.7.1 — 온보딩 fix + 마이크 미터 스케일 + OJT 매핑 안정화 ✅
- **온보딩 첫 실행 자동 노출 픽스**: `_onboardingPending` 플래그 + `closeWelcome()` 350ms 후 트리거
- **마이크 미터 스케일 강화**: RMS 선형 → dB log 스케일 + peak hold 4% 하강
- **OJT 매핑 풀림 픽스**: `_letterToIndex()` 추가로 매핑된 컬럼이 select 에 항상 보임, 빈 매핑 저장 confirm 다이얼로그
- 백업 박스 ? 도움말 호버 툴팁 (4단계 복원 방법 안내)

### v2.8.1 — 통계 도넛 차트 확실히 수정 ✅ (현재 버전)
- 통계 도넛 차트 렌더링 방식을 `$nextTick + offsetWidth 폴링` → **`IntersectionObserver` 기반**으로 전면 교체
  - 이전 방식: canvas 부모 offsetWidth 를 100ms 간격으로 최대 8회 체크 → 브라우저 레이아웃 확정 전에 실행되어 불안정
  - 새 방식: canvas 가 실제로 화면에 보이는 순간(IntersectionObserver)에 렌더 → 100% 신뢰성
  - Chart.js CDN 늦게 로드되는 경우에도 최대 3초 재시도
  - 폴백: 3초 타임아웃 강제 렌더
- 핵심 패턴: `_scheduleChartRender()` 가 `_tryRenderCharts()` 를 대체

### v2.8.0 — 견적서 자동 작성 + 통합 검색 + 통계 차트 픽스 ✅
- **견적서 초안 자동 작성** (FF): 사용자 견적서 템플릿 xlsx 등록 + 셀 매핑 마법사 → AI 분석 결과 자동 채우기
  - `quote_service.py`: `analyze_template()`, `build_quote_data()`, `generate_quote_draft()`
  - 설정 → 견적서 양식 탭 신설
- **통합 검색** (GG/B): `/search` 페이지 + SQLite FTS5
  - `search_service.py`: FTS5 가상 테이블 3개, `init_search_tables()`, `reindex_all()`, `search()`
  - 카테고리별 결과 (📄 전사 / 📝 메모 / 🤖 AI 분석), 매칭 `<mark>` 강조
  - 헤더 🔎 검색 버튼, [🔄 재인덱싱] 버튼
- **통계 도넛 차트 픽스**: `_tryRenderCharts(attempt)` — canvas 부모 width=0 이면 100ms 후 재시도 최대 8회. **destroy 제거, `update('none')` 만 사용** (핵심: Chart.js destroy→new 패턴 금지)

---

## 🐛 알려진 이슈 & 해결 기록

### 1. Python 3.14 호환성 (해결됨)
`py -3.12` 강제 사용. dev.bat 에서 가드.

### 2. .bat 한글 깨짐 / 복사 사고 (해결됨)
영문 전용 .bat + `if not exist requirements.txt` 가드.

### 3. ECAPA 모델 로드 실패 (v1 → v2 로 해결)
SpeechBrain 자체 제거. 화자 수동 토글로 전환.

### 4. silero-vad 가 torchaudio 요구 (해결됨)
`pip install torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cpu`

### 5. silero-denoise 가 100ms 블록에 무음 출력 (해결됨)
원인: 모델은 ≥500ms 컨텍스트 필요. 해결: `BufferedDenoiser` 500ms 청크.

### 6. silero-denoise 출력이 32kHz (해결됨)
원인: 모델 출력은 32kHz. 해결: `torchaudio.transforms.Resample(32000, 16000)`.

### 7. medium 모델 실시간 처리 불가 (해결됨, Two-pass 로 우회)
Ryzen 5 7520U에서 Speech Q 폭주. 실시간은 small, 종료 후 medium 재처리.

### 8. Whisper 반복 환각 `작품, 작품, ...` (해결됨)
토큰 빈도 분석 필터로 자동 폐기 (`whisper_service._is_repetition_hallucination`).

### 9. Inno Setup OOM (해결됨)
`lzma2/ultra64` → OOM. `lzma2/max + LZMANumBlockThreads=1 + LZMAUseSeparateProcess=yes`로 해결.

### 10. ISCC.exe 비표준 경로 (해결됨)
사용자가 `C:\Program Files\InterioNote\ISCC.exe` 에 설치. `build-installer.bat` 자동 탐지.

### 11. 설치된 .exe 실행 안 됨 — Program Files (해결됨)
Windows Defender 가 unsigned exe 를 Program Files 에서 차단. per-user install (`%LOCALAPPDATA%\Programs\`) 로 전환 후 해결.

### 12. 누적 AI 요약 TypeError (해결됨, v2.6.1/v2.7.0)
`ollama_client.generate()` 시그니처 오류. 올바른 호출: `generate(model=..., prompt=..., system=..., format_json=False)` + dict 응답에서 `['response']` 키 추출.

### 13. OJT 매핑이 분석 후 풀림 (해결됨, v2.7.1)
`colHeaders` getter 가 분석된 max_col 기반이라 매핑된 컬럼이 없으면 select 에서 사라짐. `_letterToIndex()` 추가로 매핑된 letter 를 colHeaders 에 무조건 포함.

### 14. OJT 동기화 RuntimeError 원인별 메시지 (해결됨, v2.7.0)
PermissionError (엑셀 열림) / OneDrive lock / 매핑 없음 각각 친절한 메시지. `whitespace-pre-line` 에러 표시.

### 15. 통계 도넛 차트 안 보임 (v2.8.1 에서 완전 해결)
- v2.8.0 fix (destroy 제거 + `_tryRenderCharts` 폴링): 불안정, $nextTick 이 브라우저 레이아웃 확정 전에 실행
- **v2.8.1 fix**: `IntersectionObserver` 기반으로 교체. canvas 가 viewport 에 실제로 보이는 순간에만 렌더.
- 추가: Chart.js CDN 늦게 로드 시 최대 3초 재시도. `_scheduleChartRender()` 가 `_tryRenderCharts()` 대체.
- **Chart.js destroy 금지 규칙은 계속 유효**: `_chartType`, `_chartMonthly` 있으면 `update('none')` 만 호출.

### 16. 온보딩 첫 실행 자동 노출 안 됨 (해결됨, v2.7.1)
환영 팝업이 떠있는 시점에 트리거되어 무시됨. `_onboardingPending` 플래그 + `closeWelcome()` 350ms 후 자동 노출.

### 17. OJT view-mode 에서 박스 미노출 (해결됨, v2.6.1)
`x-show="meetingId && finalResult.meeting_folder && ojtPreview"` — 옛 상담은 `meeting_folder`가 NULL → `x-show="meetingId && ojtPreview"` 로 완화.

### 18. OJT 파일 BadZipFile (OneDrive on-demand)
OneDrive "필요 시 다운로드" 설정으로 xlsx 가 placeholder 상태. 사용자에게 "항상 이 장치에 보관" 안내. 코드 레벨 해결 불가.

### 19. ISS 버전 자동 갱신 미이행 (사용자 불만 해결, v2.8.0 이후)
`version.json` 올릴 때 iss + `build_update_zip.py MIN_APP_VERSION` 도 자동으로 함께 갱신. 이제 3파일 동시 갱신 규칙.

---

## 🔧 실행 방법

### 개발 모드
1. `C:\InterioNote\dev.bat` 더블클릭
2. 최초 1회 자동 pip install
3. pywebview 네이티브 창 자동 오픈
4. 홈 → 고객 선택 → 상담 종류 → 녹음 시작

### 빌드 (배포)
1. `C:\InterioNote\build.bat` — PyInstaller (5~10분, dist\InterioNote\ 생성)
2. `C:\InterioNote\build-installer.bat` — Inno Setup (3~5분, Output\InterioNoteSetup-X.Y.Z.exe 생성)
3. `py -3.12 build_update_zip.py` — in-app 업데이트 zip 생성 (Output\InterioNote-update-X.Y.Z.zip)

### 빠른 동작 체크리스트
- ✅ 홈에 고객 목록 표시 (즐겨찾기 상단 고정)
- ✅ /live 화면에서 warmup 후 카드 정상 생성
- ✅ 1/2/0 키로 화자 라벨링
- ✅ 종료 시 `녹음.mp3` + `녹음원본.wav` + `대화전문.md` + `상담정보.json` 4개 생성
- ✅ 정확도 재처리 (medium) → 새 카드로 교체
- ✅ AI 분석 → `요약.md` + `분석결과.json` 생성
- ✅ 통계 페이지 도넛 차트 정상 렌더링
- ✅ 통합 검색 /search 키워드 입력 → 결과 표시

---

## 📋 워크플로우 규칙 (계속 유효)

1. **Phase 단위 중단 원칙**: 큰 기능 완료 후 멈추고 사용자 검증 받기
2. **비개발자 친화 명령**: cmd 한 줄 복붙 또는 더블클릭 .bat
3. **에러 원인 노출**: HTTP 500 detail 에 예외 타입+메시지 400자, cmd 에 traceback 전체
4. **삭제는 확인 후**: 업무 폴더(`Livart&문테리어\`) 절대 삭제 금지
5. **솔직한 한계 인정**: 매장 음악처럼 소프트웨어로 한계 있는 부분은 하드웨어 솔루션 정직하게 안내
6. **CHANGELOG 디자이너 관점**: 기술 설명 금지, 이모지+한 줄, 기술 수정은 "🔧 프로그램 안정성 개선"으로 묶기
7. **버전 bump 시 3파일 동시**: `version.json` + `InterioNoteSetup.iss` + `build_update_zip.py MIN_APP_VERSION`
8. **Chart.js 도넛 패턴**: `destroy()` 금지, `update('none')` 만 사용. `_tryRenderCharts(attempt)` 재시도 패턴.

---

## ⏭ 다음 세션에서 바로 할 것

### ✅ 현재 상태 (v2.8.0 배포 완료)
- **막힌 작업 없음**. v2.8.0 이 GitHub Releases 에 배포됨.
- `Output\` 폴더의 오래된 파일들 정리 예정 (CLAUDE.md 갱신과 함께 진행).

### 첫 메시지 권장
**"CLAUDE.md 갱신됐습니다. 매장에서 사용해 보셨나요? 불편하거나 추가됐으면 하는 기능이 있으신가요?"**

### 흔한 피드백 시나리오 + 대응

| 피드백 | 대응 |
|---|---|
| "여전히 매장 음악 때문에 인식 50% 정도" | **하드웨어 마이크 강력 추천** (BOYA BY-M1 ₩25k~30k USB 라발리에). 소프트웨어 한계는 정직하게. |
| "AI 분석에 다른 항목 추가하고 싶다" | `analysis_prompts.py` 의 SCHEMAS 사용자 편집 (settings 페이지에 추가 가능) |
| "이전 상담 검색하고 싶다" | 이미 v2.8.0 `/search` 페이지에 구현됨. 안내 후 재인덱싱 안내. |
| "AI 요약을 인쇄/메일로 보내고 싶다" | v2.6.0 PDF 출력 이미 구현됨 (`window.print()`). 추가 요구 시 weasyprint 도입 검토. |
| "단축키 더 필요하다" | live.html 의 handleKeydown 확장 |
| "다중 PC 동기화" | CLIENT_ROOT 를 OneDrive/Dropbox 경로로 설정 (이미 가능). DB 는 별도 동기화 도구 필요. |
| "다른 디자이너에게 배포하고 싶다" | GitHub Releases 인스톨러 링크 공유. 각자 Ollama + qwen2.5:3b 설치 필요 (안내문 있음). |
| "OJT 매핑 또 풀렸다" | v2.7.1 에서 fix 됨. 재현 시 chrome 개발자 도구 console 로그 확인 후 `ojt.config` DB 키 직접 조회. |

### 새 기능 추가 시 워크플로우
1. 코드 변경 + 검증
2. `app/version.json` 버전 올림 + changelog 추가
3. `InterioNoteSetup.iss` MyAppVersion 동시 갱신
4. `build_update_zip.py` MIN_APP_VERSION 동시 갱신
5. `build.bat` → `build-installer.bat` → `py -3.12 build_update_zip.py`
6. GitHub Releases 에 3개 파일 (exe + zip + manifest) 업로드
7. 사용자 다음 실행 시 자동으로 시작 팝업 + 업데이트 알림

### 가능한 다음 작업들
- 매장 며칠 실사용 후 피드백 반영
- Whisper large-v3 재처리 품질 검증 (GPU PC 에서)
- 견적서 초안 사용성 개선 (셀 매핑 UX, 지원 서식 확장)
- 고객 검색 + 필터 (현재 이름 순/최근 순만 있음)
- 다중 디자이너 지원 (서버 모드 — 큰 작업)

---

## 🔗 경로 참조 요약

| 용도 | 경로 |
|---|---|
| 프로그램 본체 | `C:\InterioNote\` |
| 개발 런처 | `C:\InterioNote\dev.bat` |
| DB (런타임) | `%APPDATA%\InterioNote\data\interionote.db` |
| 모델 캐시 (런타임) | `%LOCALAPPDATA%\InterioNote\models_cache\` |
| 임시 녹음 (런타임) | `%LOCALAPPDATA%\InterioNote\temp_recording\` |
| 설치된 앱 | `%LOCALAPPDATA%\Programs\InterioNote\` |
| 고객 폴더 루트 | settings DB `paths.client_root` 에서 관리 (기본: Documents\Livart&문테리어\07_고객정보) |
| 인수인계 파일 | `C:\InterioNote\CLAUDE.md` |
| 배포 산출물 | `C:\InterioNote\Output\` |

---

## 📝 작업 이력 타임라인 (요약)

- **초반 기획** — 4종 상담 → 3종 축소, 화자 자동 판별 → 수동 토글
- **Phase 1~2 v1** — ECAPA 도전 → 실패 → 전면 삭제
- **v2 재설계** — 경량화(SpeechBrain 제거) + .exe 배포 목표
- **Phase 1~5C** — 뼈대 + STT 파이프라인 + 노이즈 억제 + Two-pass 재전사
- **Phase 6** — 저장 위치 설정 + 시작 팝업 + 과거 상담 보기 (v2.1~2.2)
- **Phase 7** — 데이터 분리 + GitHub 자동 업데이트 + PyInstaller + Inno Setup (v2.3)
- **v2.4.0** — GPU 지원, 카드 직접 편집, 인앱 빠른 업데이트
- **v2.4.3~2.4.6** — CHANGELOG 규칙 확립, Bad file descriptor 수정, 진단 로그
- **v2.5.0** — 다크 모드, 카드 검색, 설정창 5탭
- **v2.5.1** — 상담 메모, AI 분석 강화, 폴더명 제안, 통계 페이지, 빠른 메모
- **v2.5.2~2.5.4** — sticky 종료 버튼, 빨간 펄스, 작업표시줄 정리, 다크 모드 보정
- **v2.5.5** — 환영 팝업 Wi-Fi/Ollama 안내
- **v2.5.6** — Ollama 사전 체크 모달, 오디오 ±5초+속도, 전체 복사, 도움말 버튼
- **v2.6.0** — 고객 360 뷰, OJT 동기화, 태그, 진행률, PDF, openpyxl
- **v2.6.1** — OJT 전 미팅 허용, PDF 네비게이션, 누적 AI 요약 TypeError 수정
- **v2.7.0** — 마이크 미터, 빠른 답변 템플릿, 데이터 백업, 최근 본 상담, 온보딩
- **v2.7.1** — 온보딩 첫 노출 fix, 마이크 미터 dB 스케일, OJT 매핑 fix, 백업 툴팁
- **v2.8.0** — 견적서 초안 자동 작성, 통합 검색 (FTS5), 통계 도넛 차트 fix
- **CLAUDE.md 갱신** (v2.8.0 시점, 이 파일)

---

## 🚨 다음 Claude 에게 마지막 당부

1. **이 문서를 끝까지 읽은 후** 자연스럽게 시작 ("v2.8.0 배포 완료됐습니다. 실제로 매장에서 써보셨나요?").
2. **사용자가 명시적으로 요청하기 전까지 새 기능 코드 작성 금지**.
3. **비개발자**임을 잊지 마세요 — 한 줄씩 안내, 에러 시 창 안 닫히게, 전체 로그 공유 요청.
4. **솔직한 한계 인정**: 음악 환경 인식률, CPU 한계, 모델 다운로드 시간 등.
5. 코드 수정 시 기존 패턴 준수:
   - Tailwind CDN + Alpine.js (React 금지)
   - FastAPI 라우터 분리, 한국어 주석, 예외 타입명 노출
   - 새 설정은 `settings_service` + `/api/settings` + `settings.html` 3곳에 일관되게
   - 새 모델 사용 시 모델 캐시 위치 통일 (`config.MODELS_CACHE_DIR`)
   - **Chart.js 도넛**: destroy 금지, update('none') 패턴 + _tryRenderCharts 재시도
   - **버전 bump**: `version.json` + `InterioNoteSetup.iss` + `build_update_zip.py` 3파일 동시
6. OJT/견적서 기능은 openpyxl 기반. OneDrive on-demand placeholder 이슈 있으면 "항상 이 장치에 보관" 안내.

---

_이 문서는 v2.8.0 (통합 검색 + 견적서 초안 + 통계 차트 픽스) 배포 완료 후 갱신되었습니다._
_작업 상태: 배포 완료, 막힌 이슈 없음._
