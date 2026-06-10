"""
v3.5.4 — 외부 폴더에서 InterioNote 상담 데이터 자동 임포트.

활용 시나리오:
- 노트북에서 녹음한 상담 폴더를 외장 SSD 로 복사
- 데스크톱 InterioNote 가 SSD 경로를 가리키게 변경
- 이 임포트 기능으로 SSD 안의 모든 상담을 데스크톱 DB 에 등록
- 그 후 데스크톱에서 GPU 로 재전사·AI 분석 진행

폴더 구조 (인식 패턴):
    {root}/
        {이름} 고객님(...)/
            상담기록/
                {YYYY-MM-DD}_{초도상담|디자인미팅|견적미팅}[_N]/
                    상담정보.json    ← 메타데이터
                    대화전문.md       ← 전사 카드
                    분석결과.json     ← (있으면) AI 분석
                    녹음.mp3 / 녹음원본.wav

동작:
- preview() : 임포트 가능한 고객·상담·카드 카운트
- run()     : 실제 DB 삽입 (이미 있는 건 skip)
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.db import db_cursor

# 고객 폴더 인식 패턴
_CLIENT_KEYWORDS = ("고객님", "건축", "공사")
# 대화전문.md 의 카드 라인 패턴 — `**[MM:SS]** 텍스트` 또는 `**[HH:MM:SS]** (화자) 텍스트`
_CARD_LINE_RE = re.compile(
    r"^\*\*\[(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\]\*\*\s*(?:\((?P<sp>[^)]+)\)\s*)?(?P<text>.+?)\s*$"
)


def _parse_timestamp_ms(ts: str) -> int:
    """`MM:SS` 또는 `HH:MM:SS` → 밀리초."""
    parts = ts.split(":")
    if len(parts) == 2:
        h, m, s = 0, int(parts[0]), int(parts[1])
    elif len(parts) == 3:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
    else:
        return 0
    return (h * 3600 + m * 60 + s) * 1000


def _is_client_folder(name: str) -> bool:
    return any(k in name for k in _CLIENT_KEYWORDS)


def _scan_folder(root: Path) -> List[Tuple[Path, List[Path]]]:
    """root 안의 (고객 폴더, [상담 폴더 목록]) 쌍 리스트."""
    out: List[Tuple[Path, List[Path]]] = []
    if not root.exists() or not root.is_dir():
        return out
    for client_dir in sorted(root.iterdir()):
        if not client_dir.is_dir() or not _is_client_folder(client_dir.name):
            continue
        rec_dir = client_dir / "상담기록"
        if not rec_dir.exists():
            out.append((client_dir, []))
            continue
        meeting_dirs = []
        for d in sorted(rec_dir.iterdir()):
            if d.is_dir() and (d / "상담정보.json").exists():
                meeting_dirs.append(d)
        out.append((client_dir, meeting_dirs))
    return out


def _parse_transcript_md(md_path: Path) -> List[Dict[str, Any]]:
    """대화전문.md → transcript_segments 용 dict 리스트."""
    segs: List[Dict[str, Any]] = []
    if not md_path.exists():
        return segs
    text = md_path.read_text(encoding="utf-8", errors="replace")
    prev_start_ms: Optional[int] = None
    prev_seg: Optional[Dict[str, Any]] = None
    for line in text.splitlines():
        m = _CARD_LINE_RE.match(line)
        if not m:
            continue
        start_ms = _parse_timestamp_ms(m.group("ts"))
        sp = m.group("sp")
        speaker = None
        if sp:
            sp_lower = sp.strip().lower()
            if sp_lower in ("나", "me", "나(디자이너)"):
                speaker = "me"
            elif sp_lower in ("고객", "client", "고객님"):
                speaker = "client"
        # 이전 카드의 end_ms 를 현재 카드의 start_ms 로 (대략적)
        if prev_seg is not None and prev_seg.get("end_ms") is None:
            prev_seg["end_ms"] = start_ms
        seg = {
            "start_ms": start_ms,
            "end_ms": None,  # 다음 카드 또는 EOF 에서 채움
            "text": (m.group("text") or "").strip(),
            "speaker": speaker,
        }
        segs.append(seg)
        prev_seg = seg
        prev_start_ms = start_ms
    # 마지막 카드의 end_ms — 적당히 +5초
    if prev_seg is not None and prev_seg.get("end_ms") is None:
        prev_seg["end_ms"] = (prev_seg["start_ms"] or 0) + 5000
    return segs


def preview(root_path: str) -> Dict[str, Any]:
    """임포트 미리보기 — 실제 DB 변경 없이 카운트."""
    root = Path(root_path)
    if not root.exists():
        return {"ok": False, "error": f"폴더가 존재하지 않습니다: {root_path}"}
    if not root.is_dir():
        return {"ok": False, "error": f"폴더가 아닙니다: {root_path}"}

    pairs = _scan_folder(root)
    n_clients = len(pairs)
    n_meetings = sum(len(ms) for _, ms in pairs)
    # 이미 DB 에 있는 건 별도 카운트
    with db_cursor() as cur:
        existing_folders = {r["folder_name"] for r in cur.execute(
            "SELECT folder_name FROM clients").fetchall()}
        existing_meeting_folders = {r["meeting_folder"] for r in cur.execute(
            "SELECT meeting_folder FROM meetings WHERE meeting_folder IS NOT NULL").fetchall()}

    new_clients = sum(1 for c, _ in pairs if c.name not in existing_folders)
    new_meetings = 0
    samples = []
    for client_dir, meeting_dirs in pairs:
        for md in meeting_dirs:
            if str(md) not in existing_meeting_folders:
                new_meetings += 1
                if len(samples) < 8:
                    samples.append({
                        "client": client_dir.name,
                        "meeting": md.name,
                        "path": str(md),
                    })
    return {
        "ok": True,
        "root": str(root),
        "found_clients": n_clients,
        "found_meetings": n_meetings,
        "new_clients": new_clients,
        "new_meetings": new_meetings,
        "existing_clients": n_clients - new_clients,
        "existing_meetings": n_meetings - new_meetings,
        "samples": samples,
    }


def run(root_path: str) -> Dict[str, Any]:
    """실제 임포트 실행. 이미 있는 건 skip (덮어쓰기 안 함)."""
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"폴더 경로가 잘못됐습니다: {root_path}")

    pairs = _scan_folder(root)
    added_clients = 0
    added_meetings = 0
    added_segments = 0
    added_analyses = 0
    errors: List[str] = []

    with db_cursor() as cur:
        # 기존 매핑 미리 로드
        client_id_by_folder: Dict[str, int] = {}
        for r in cur.execute("SELECT id, folder_name FROM clients").fetchall():
            client_id_by_folder[r["folder_name"]] = r["id"]
        existing_meeting_folders: set = {
            r["meeting_folder"]
            for r in cur.execute("SELECT meeting_folder FROM meetings WHERE meeting_folder IS NOT NULL").fetchall()
        }

        for client_dir, meeting_dirs in pairs:
            try:
                folder_name = client_dir.name
                client_id = client_id_by_folder.get(folder_name)
                if client_id is None:
                    # client INSERT — name + descriptor 추출
                    # "{이름} 고객님(...)" 형식에서 이름과 descriptor 분리
                    name_part = folder_name
                    desc = ""
                    paren = folder_name.find("(")
                    if paren > 0:
                        name_part = folder_name[:paren]
                        desc = folder_name[paren + 1:].rstrip(")")
                    name_only = name_part.replace("고객님", "").replace("건축", "").replace("공사", "").strip()
                    if not name_only:
                        name_only = name_part.strip()
                    cur.execute(
                        "INSERT INTO clients(name, descriptor, folder_name, folder_path, created_at) "
                        "VALUES(?, ?, ?, ?, CURRENT_TIMESTAMP)",
                        (name_only, desc, folder_name, str(client_dir)),
                    )
                    client_id = cur.lastrowid
                    client_id_by_folder[folder_name] = client_id
                    added_clients += 1

                # 각 상담 임포트
                for meeting_dir in meeting_dirs:
                    meeting_folder_str = str(meeting_dir)
                    if meeting_folder_str in existing_meeting_folders:
                        continue
                    info_path = meeting_dir / "상담정보.json"
                    if not info_path.exists():
                        continue
                    try:
                        info = json.loads(info_path.read_text(encoding="utf-8"))
                    except Exception as e:
                        errors.append(f"{meeting_dir.name}: 상담정보.json 파싱 실패 - {e}")
                        continue
                    meeting_type = info.get("meeting_type") or "초도상담"
                    started_at = info.get("started_at") or datetime.now().isoformat(timespec="seconds")
                    ended_at = info.get("ended_at")
                    duration_sec = info.get("duration_sec") or 0
                    audio_file_rel = info.get("audio_file") or "녹음.mp3"
                    audio_path = meeting_dir / audio_file_rel

                    cur.execute(
                        "INSERT INTO meetings(client_id, meeting_type, started_at, ended_at, "
                        "                     duration_sec, meeting_folder, audio_file, status) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?, 'recorded')",
                        (
                            client_id, meeting_type, started_at, ended_at,
                            int(duration_sec), meeting_folder_str,
                            str(audio_path) if audio_path.exists() else None,
                        ),
                    )
                    new_meeting_id = cur.lastrowid
                    added_meetings += 1
                    existing_meeting_folders.add(meeting_folder_str)

                    # 대화전문.md → segments
                    md_path = meeting_dir / "대화전문.md"
                    segs = _parse_transcript_md(md_path)
                    for seg in segs:
                        cur.execute(
                            "INSERT INTO transcript_segments(meeting_id, start_ms, end_ms, "
                            "                                text, speaker) "
                            "VALUES(?, ?, ?, ?, ?)",
                            (
                                new_meeting_id,
                                int(seg["start_ms"] or 0),
                                int(seg["end_ms"] or 0),
                                seg["text"],
                                seg.get("speaker"),
                            ),
                        )
                        added_segments += 1

                    # 분석결과.json → analyses
                    analysis_path = meeting_dir / "분석결과.json"
                    if analysis_path.exists():
                        try:
                            ana = json.loads(analysis_path.read_text(encoding="utf-8"))
                            data_json = json.dumps(ana.get("data") or ana, ensure_ascii=False)
                            cur.execute(
                                "INSERT INTO analyses(meeting_id, data_json, model_used) "
                                "VALUES(?, ?, ?)",
                                (new_meeting_id, data_json, ana.get("model") or "imported"),
                            )
                            added_analyses += 1
                        except Exception as e:
                            errors.append(f"{meeting_dir.name}: 분석결과.json 파싱 실패 - {e}")
            except Exception as e:
                errors.append(f"{client_dir.name}: {type(e).__name__}: {e}")

    return {
        "ok": True,
        "added_clients": added_clients,
        "added_meetings": added_meetings,
        "added_segments": added_segments,
        "added_analyses": added_analyses,
        "errors": errors[:50],
        "error_count": len(errors),
    }
