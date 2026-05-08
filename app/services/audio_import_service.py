"""
v3.5.5 — 외부 음성 파일에서 새 상담 만들기.

활용 시나리오:
- iPhone 음성메모로 매장에서 녹음
- AirDrop / 메일 / OneDrive 로 데스크톱에 전송
- InterioNote 에서 이 파일 임포트 → 자동으로 상담 폴더 생성 + DB 등록
- 그 후 재전사 버튼 누르면 GPU 로 전사 + AI 분석

지원 포맷: mp3, m4a, wav, ogg, opus, aac, flac
"""
from __future__ import annotations

import shutil
import wave
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from app import config
from app.db import db_cursor
from app.services import meeting_finalizer
from app.utils import folder_template

SUPPORTED_EXT = {".mp3", ".m4a", ".wav", ".ogg", ".opus", ".aac", ".flac", ".webm"}


def import_audio_file(
    audio_path: str,
    client_folder_name: str,
    meeting_type: str,
    started_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    외부 음성 파일을 새 상담으로 등록.

    Args:
        audio_path: 외부 음성 파일 절대경로
        client_folder_name: 기존 고객의 folder_name (예: "성기재 고객님(...)")
                            없으면 ValueError
        meeting_type: '초도상담' | '디자인미팅' | '견적미팅'
        started_at: ISO 형식 시작 시각. None 이면 파일 수정 시각 또는 현재.

    Returns:
        {meeting_id, meeting_folder, audio_file_path, ...}
    """
    src = Path(audio_path)
    if not src.exists():
        raise FileNotFoundError(f"파일이 존재하지 않습니다: {audio_path}")
    if src.suffix.lower() not in SUPPORTED_EXT:
        raise ValueError(f"지원하지 않는 형식 ({src.suffix}). 지원: {', '.join(sorted(SUPPORTED_EXT))}")
    if meeting_type not in ("초도상담", "디자인미팅", "견적미팅"):
        raise ValueError(f"meeting_type 잘못됨: {meeting_type}")

    # 1) 고객 row 조회
    with db_cursor() as cur:
        client_row = cur.execute(
            "SELECT id, folder_path FROM clients WHERE folder_name = ?",
            (client_folder_name,),
        ).fetchone()
        if client_row is None:
            raise ValueError(f"고객 '{client_folder_name}' 을 찾을 수 없습니다. 먼저 고객을 등록하세요.")
        client_id = client_row["id"]
        client_folder = Path(client_row["folder_path"])
        if not client_folder.exists():
            raise ValueError(f"고객 폴더가 디스크에 없습니다: {client_folder}")

    # 2) started_at 결정
    if started_at:
        try:
            started_dt = datetime.fromisoformat(started_at)
        except ValueError:
            started_dt = datetime.now()
    else:
        # 파일 수정 시각 or 현재
        try:
            started_dt = datetime.fromtimestamp(src.stat().st_mtime)
        except Exception:
            started_dt = datetime.now()

    # 3) 상담 폴더 생성 (날짜+종류, 중복이면 _2 _3)
    folder_template.ensure_client_template(client_folder)
    meeting_folder = meeting_finalizer._pick_meeting_folder(
        client_folder, meeting_type, started_dt
    )
    meeting_folder.mkdir(parents=True, exist_ok=True)

    # 4) 오디오 파일을 상담 폴더로 복사 (원본 보존)
    # 확장자에 맞춰 파일명 결정. mp3 인 경우 녹음.mp3, 그 외는 원본 확장자 유지
    if src.suffix.lower() == ".mp3":
        dest_name = "녹음.mp3"
    elif src.suffix.lower() == ".wav":
        dest_name = "녹음원본.wav"
    else:
        dest_name = f"녹음{src.suffix.lower()}"
    dest = meeting_folder / dest_name
    shutil.copy2(src, dest)

    # 5) 오디오 길이 추정 (WAV 면 정확히 계산, 그 외는 0 — 재전사 후 갱신)
    duration_sec = 0
    if src.suffix.lower() == ".wav":
        try:
            with wave.open(str(dest), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    duration_sec = int(frames / rate)
        except Exception:
            pass
    # mp3/m4a 등 다른 포맷은 mutagen 같은 라이브러리 없이는 정확히 못 잼.
    # 빈 값으로 두고 재전사 시 갱신.

    ended_dt = started_dt
    if duration_sec > 0:
        from datetime import timedelta
        ended_dt = started_dt + timedelta(seconds=duration_sec)

    # 6) meetings 테이블 INSERT
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO meetings(client_id, meeting_type, started_at, ended_at, "
            "                     duration_sec, meeting_folder, audio_file, status) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, 'recorded')",
            (
                client_id,
                meeting_type,
                started_dt.isoformat(timespec="seconds"),
                ended_dt.isoformat(timespec="seconds"),
                duration_sec,
                str(meeting_folder),
                str(dest),
            ),
        )
        meeting_id = cur.lastrowid

    # 7) 상담정보.json 만들기 (재전사·임포트 호환)
    info = {
        "meeting_id": meeting_id,
        "client": {
            "id": client_id,
            "folder_name": client_folder_name,
        },
        "meeting_type": meeting_type,
        "started_at": started_dt.isoformat(timespec="seconds"),
        "ended_at": ended_dt.isoformat(timespec="seconds"),
        "duration_sec": duration_sec,
        "audio_file": dest.name,
        "imported_from": str(src),
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "app_version": config.APP_VERSION,
    }
    import json as _json
    (meeting_folder / "상담정보.json").write_text(
        _json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "ok": True,
        "meeting_id": meeting_id,
        "meeting_folder": str(meeting_folder),
        "audio_file": str(dest),
        "duration_sec": duration_sec,
        "next_step": "재전사 버튼을 눌러 전사를 시작하세요.",
    }
