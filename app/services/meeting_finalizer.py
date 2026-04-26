"""
녹음 종료 후처리 (Phase 3C).

1. meeting + client 정보 로드
2. 최종 폴더 경로 결정 ({client}/상담기록/{YYYY-MM-DD_상담종류}[_N])
3. WAV → MP3 인코딩
4. 대화전문.md 작성
5. 상담정보.json 작성
6. transcript_segments DB 저장
7. meeting row 업데이트 (audio_file, meeting_folder, status='recorded', ...)
8. 임시 폴더 삭제
"""
from __future__ import annotations

import json
import logging
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app import config
from app.db import db_cursor
from app.services import mp3_encoder

log = logging.getLogger("finalizer")


# ========================================
# 경로 결정
# ========================================
def _pick_meeting_folder(client_folder: Path, meeting_type: str, started_at: datetime) -> Path:
    """
    '{client}/상담기록/{YYYY-MM-DD_meeting_type}' — 이미 있으면 _2, _3 ... 로 증가.
    """
    records_root = client_folder / "상담기록"
    records_root.mkdir(parents=True, exist_ok=True)
    date_str = started_at.strftime("%Y-%m-%d")
    base_name = f"{date_str}_{meeting_type}"
    candidate = records_root / base_name
    n = 1
    while candidate.exists():
        n += 1
        candidate = records_root / f"{base_name}_{n}"
    return candidate


# ========================================
# 대화전문.md
# ========================================
def _format_timestamp(ms: int) -> str:
    total = max(0, int(ms // 1000))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _speaker_label(speaker: Optional[str]) -> str:
    if speaker == "me":
        return "나"
    if speaker == "client":
        return "고객"
    return ""


def _render_transcript_md(
    *,
    client_name: str,
    client_descriptor: Optional[str],
    meeting_type: str,
    started_at: datetime,
    ended_at: datetime,
    duration_sec: float,
    segments: List[Dict[str, Any]],
    audio_filename: str,
) -> str:
    header_name = client_name
    if client_descriptor:
        header_name += f" ({client_descriptor})"

    def fmt_dur(sec: float) -> str:
        total = int(round(sec))
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        parts = []
        if h:
            parts.append(f"{h}시간")
        if m:
            parts.append(f"{m}분")
        parts.append(f"{s}초")
        return " ".join(parts)

    lines: List[str] = []
    lines.append(f"# {meeting_type} — {header_name}")
    lines.append("")
    lines.append(f"- 일시: {started_at.strftime('%Y-%m-%d %H:%M:%S')} ~ {ended_at.strftime('%H:%M:%S')} ({fmt_dur(duration_sec)})")
    lines.append(f"- 녹음 파일: `{audio_filename}`")
    lines.append(f"- 발화 카드 수: {len(segments)}건")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 전사")
    lines.append("")

    if not segments:
        lines.append("_(전사된 발화가 없습니다.)_")
    else:
        for seg in segments:
            ts = _format_timestamp(seg.get("start_ms", 0))
            sp = _speaker_label(seg.get("speaker"))
            sp_str = f" **{sp}:**" if sp else ""
            text = (seg.get("text") or "").strip()
            lines.append(f"**[{ts}]**{sp_str} {text}")
            lines.append("")

    return "\n".join(lines)


# ========================================
# DB 조회 / 업데이트
# ========================================
def _load_meeting_and_client(meeting_id: int) -> Optional[Dict[str, Any]]:
    with db_cursor() as cur:
        row = cur.execute(
            """
            SELECT m.*,
                   c.id AS client_id, c.name AS client_name,
                   c.descriptor AS client_descriptor,
                   c.folder_name, c.folder_path
            FROM meetings m
            JOIN clients c ON c.id = m.client_id
            WHERE m.id = ?
            """,
            (meeting_id,),
        ).fetchone()
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def _save_segments_to_db(meeting_id: int, segments: List[Dict[str, Any]]) -> None:
    if not segments:
        return
    with db_cursor() as cur:
        cur.executemany(
            """
            INSERT INTO transcript_segments
                (meeting_id, start_ms, end_ms, text, speaker, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    meeting_id,
                    int(s.get("start_ms", 0)),
                    int(s.get("end_ms", 0)),
                    s.get("text", "") or "",
                    s.get("speaker"),
                    s.get("confidence"),
                )
                for s in segments
            ],
        )


def load_segments_from_db(meeting_id: int) -> List[Dict[str, Any]]:
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT id, meeting_id, start_ms, end_ms, text, speaker, confidence
            FROM transcript_segments
            WHERE meeting_id = ?
            ORDER BY start_ms, id
            """,
            (meeting_id,),
        ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def _update_meeting_row(
    meeting_id: int,
    *,
    ended_at: datetime,
    duration_sec: float,
    meeting_folder: Path,
    audio_file: Path,
    status: str = "recorded",
) -> None:
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE meetings
               SET ended_at = ?,
                   duration_sec = ?,
                   meeting_folder = ?,
                   audio_file = ?,
                   status = ?
             WHERE id = ?
            """,
            (
                ended_at.isoformat(timespec="seconds"),
                int(round(duration_sec)),
                str(meeting_folder),
                str(audio_file),
                status,
                meeting_id,
            ),
        )


def _mark_meeting_failed(meeting_id: int, reason: str) -> None:
    """상담 처리 실패. 에러 사유는 로그에만 남기고 DB에는 status='failed' 만."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "UPDATE meetings SET status = 'failed', ended_at = ? WHERE id = ?",
                (datetime.now().isoformat(timespec="seconds"), meeting_id),
            )
    except Exception:
        pass
    log.error(f"meeting {meeting_id} finalize failed: {reason}")


# ========================================
# 메인 엔트리
# ========================================
def finalize_meeting(
    meeting_id: int,
    final_result: Dict[str, Any],
    *,
    app_version: str = "unknown",
) -> Dict[str, Any]:
    """
    LiveSession.final_result() 결과를 받아 최종 저장까지 수행.
    반환: 추가 정보(meeting_folder, mp3_path, markdown_path, json_path, ...)를 합친 dict.
    예외는 상위에서 처리하되, status='failed' 갱신 정도는 여기서 함.
    """
    meeting = _load_meeting_and_client(meeting_id)
    if meeting is None:
        raise ValueError(f"meeting {meeting_id} not found")

    wav_path = Path(final_result.get("wav_path", ""))
    if not wav_path.exists():
        _mark_meeting_failed(meeting_id, f"wav not found: {wav_path}")
        raise FileNotFoundError(f"녹음 파일을 찾을 수 없습니다: {wav_path}")

    started_at = datetime.fromisoformat(
        final_result.get("started_at") or meeting["started_at"]
    )
    ended_at_raw = final_result.get("ended_at")
    ended_at = datetime.fromisoformat(ended_at_raw) if ended_at_raw else datetime.now()
    duration_sec = float(final_result.get("duration_sec") or 0.0)

    client_folder = Path(meeting["folder_path"])
    if not client_folder.exists():
        _mark_meeting_failed(meeting_id, f"client folder missing: {client_folder}")
        raise FileNotFoundError(f"고객 폴더를 찾을 수 없습니다: {client_folder}")

    meeting_folder = _pick_meeting_folder(
        client_folder,
        meeting["meeting_type"],
        started_at,
    )
    meeting_folder.mkdir(parents=True, exist_ok=False)

    audio_filename = "녹음.mp3"
    mp3_path = meeting_folder / audio_filename
    md_path = meeting_folder / "대화전문.md"
    json_path = meeting_folder / "상담정보.json"
    wav_archive_path = meeting_folder / "녹음원본.wav"  # 재전사용 원본 보존

    # -----------------------------
    # 1) WAV → MP3
    # -----------------------------
    try:
        mp3_info = mp3_encoder.wav_to_mp3(wav_path, mp3_path, bitrate_kbps=128)
    except Exception as e:
        _mark_meeting_failed(meeting_id, f"mp3 encode: {type(e).__name__}: {e}")
        # 폴더 롤백
        try:
            shutil.rmtree(meeting_folder, ignore_errors=True)
        except Exception:
            pass
        raise

    # -----------------------------
    # 2) 대화전문.md
    # -----------------------------
    segments = final_result.get("segments") or []
    try:
        md_content = _render_transcript_md(
            client_name=meeting["client_name"],
            client_descriptor=meeting["client_descriptor"],
            meeting_type=meeting["meeting_type"],
            started_at=started_at,
            ended_at=ended_at,
            duration_sec=duration_sec,
            segments=segments,
            audio_filename=audio_filename,
        )
        md_path.write_text(md_content, encoding="utf-8")
    except Exception as e:
        log.error(f"transcript md write failed: {type(e).__name__}: {e}")
        # 치명적이지 않음 — 계속 진행

    # -----------------------------
    # 3) 상담정보.json
    # -----------------------------
    try:
        info_payload = {
            "meeting_id": meeting_id,
            "client": {
                "id": meeting["client_id"],
                "name": meeting["client_name"],
                "descriptor": meeting["client_descriptor"],
                "folder_name": meeting["folder_name"],
            },
            "meeting_type": meeting["meeting_type"],
            "started_at": started_at.isoformat(timespec="seconds"),
            "ended_at": ended_at.isoformat(timespec="seconds"),
            "duration_sec": int(round(duration_sec)),
            "segments_count": len(segments),
            "dropped_blocks": int(final_result.get("dropped_blocks") or 0),
            "audio_file": audio_filename,
            "audio_size_bytes": mp3_info.get("size_bytes"),
            "audio_bitrate_kbps": mp3_info.get("bitrate_kbps"),
            "wav_frames": mp3_info.get("input_frames"),
            "wav_sample_rate": mp3_info.get("input_sample_rate"),
            "app_version": app_version,
            "finalized_at": datetime.now().isoformat(timespec="seconds"),
        }
        json_path.write_text(
            json.dumps(info_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        log.error(f"info json write failed: {type(e).__name__}: {e}")

    # -----------------------------
    # 4) DB 저장
    # -----------------------------
    try:
        _save_segments_to_db(meeting_id, segments)
    except Exception as e:
        log.error(f"segments save failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")

    try:
        _update_meeting_row(
            meeting_id,
            ended_at=ended_at,
            duration_sec=duration_sec,
            meeting_folder=meeting_folder,
            audio_file=mp3_path,
            status="recorded",
        )
    except Exception as e:
        log.error(f"meeting row update failed: {type(e).__name__}: {e}")

    # DB 에서 세그먼트를 다시 읽어옴 — DB 에서 부여된 id 를 UI 가 사용할 수 있도록
    db_segments = load_segments_from_db(meeting_id)

    # -----------------------------
    # 5) WAV 원본을 상담 폴더에 보존 (재전사용)
    # -----------------------------
    try:
        shutil.copy2(str(wav_path), str(wav_archive_path))
    except Exception as e:
        log.warning(f"WAV archive failed: {type(e).__name__}: {e}")

    # -----------------------------
    # 6) 임시 폴더 삭제
    # -----------------------------
    temp_folder: Optional[Path] = None
    if meeting.get("temp_folder"):
        temp_folder = Path(meeting["temp_folder"])
    elif wav_path.parent and wav_path.parent.parent == config.TEMP_RECORDING_DIR:
        temp_folder = wav_path.parent

    if temp_folder is not None and temp_folder.exists():
        try:
            shutil.rmtree(temp_folder, ignore_errors=True)
        except Exception as e:
            log.warning(f"temp folder cleanup failed: {type(e).__name__}: {e}")

    return {
        "meeting_id": meeting_id,
        "meeting_folder": str(meeting_folder),
        "mp3_path": str(mp3_path),
        "mp3_size_bytes": mp3_info.get("size_bytes"),
        "markdown_path": str(md_path),
        "info_json_path": str(json_path),
        "wav_archive_path": str(wav_archive_path) if wav_archive_path.exists() else None,
        "status": "recorded",
        "segments_count": len(db_segments),
        "segments": db_segments,
    }


# ========================================
# Speaker 라벨 변경 후 MD 재생성 (Phase 3D)
# ========================================
def regenerate_transcript_md(meeting_id: int) -> str:
    """
    DB 의 최신 transcript_segments + meeting + client 정보로 대화전문.md 재작성.
    반환: 파일 경로.
    """
    meeting = _load_meeting_and_client(meeting_id)
    if meeting is None:
        raise ValueError(f"meeting {meeting_id} not found")

    meeting_folder_str = meeting.get("meeting_folder")
    if not meeting_folder_str:
        raise ValueError("아직 최종 폴더가 지정되지 않은 상담입니다.")
    meeting_folder = Path(meeting_folder_str)
    if not meeting_folder.exists():
        raise FileNotFoundError(f"상담 폴더를 찾을 수 없습니다: {meeting_folder}")

    audio_filename = (
        Path(meeting["audio_file"]).name if meeting.get("audio_file") else "녹음.mp3"
    )

    started_at = datetime.fromisoformat(meeting["started_at"])
    ended_at_str = meeting.get("ended_at") or datetime.now().isoformat(timespec="seconds")
    ended_at = datetime.fromisoformat(ended_at_str)
    duration_sec = float(meeting.get("duration_sec") or 0.0)

    segments = load_segments_from_db(meeting_id)
    md_content = _render_transcript_md(
        client_name=meeting["client_name"],
        client_descriptor=meeting["client_descriptor"],
        meeting_type=meeting["meeting_type"],
        started_at=started_at,
        ended_at=ended_at,
        duration_sec=duration_sec,
        segments=segments,
        audio_filename=audio_filename,
    )
    md_path = meeting_folder / "대화전문.md"
    md_path.write_text(md_content, encoding="utf-8")
    return str(md_path)
