"""
상담(meetings) API.

- POST /api/meetings/new                            : 고객 + 상담종류 선택 후 meeting row 생성
- GET  /api/meetings?folder={folder_name}           : 고객 폴더로 과거 상담 목록 조회 (Phase 6C)
- GET  /api/meetings/{id}                           : 상담 메타 정보
- GET  /api/meetings/{id}/segments                  : 세그먼트 목록
- GET  /api/meetings/{id}/audio                     : MP3 스트리밍 (Phase 6C)
- POST /api/meetings/{id}/segments/{sid}/speaker    : 화자 라벨 변경
- POST /api/meetings/{id}/retranscribe              : Two-pass 재전사
"""
from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import config
from app.db import db_cursor
from app.services import (
    client_service,
    folder_rename,
    meeting_finalizer,
    retranscribe_service,
    settings_service,
    stage_service,
    tags_service,
)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _session_slug(started_at: datetime) -> str:
    return started_at.strftime("%Y%m%d_%H%M%S")


# ========================================
# POST /api/meetings/new
# ========================================
class NewMeetingRequest(BaseModel):
    folder_name: str = Field(..., min_length=1)
    meeting_type: str = Field(..., min_length=1)


@router.post("/new")
def new_meeting(req: NewMeetingRequest):
    # 상담 종류 검증
    if req.meeting_type not in config.MEETING_TYPES:
        raise HTTPException(
            400,
            f"알 수 없는 상담 종류: {req.meeting_type}. 허용: {config.MEETING_TYPES}",
        )

    # 폴더명 검증
    if "\\" in req.folder_name or "/" in req.folder_name:
        raise HTTPException(400, "유효하지 않은 폴더 이름입니다.")

    client_root = settings_service.get_client_root()
    folder_path = (client_root / req.folder_name).resolve()
    try:
        folder_path.relative_to(client_root.resolve())
    except ValueError:
        raise HTTPException(400, "고객 루트 바깥의 폴더입니다.")
    if not folder_path.exists():
        raise HTTPException(404, f"고객 폴더를 찾을 수 없습니다: {req.folder_name}")

    # 클라이언트 upsert
    try:
        client = client_service.upsert_client_by_folder(req.folder_name)
    except Exception as e:
        print(f"\n[new_meeting:upsert] {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
        raise HTTPException(500, f"고객 정보 저장 실패: {type(e).__name__}: {e}")

    # 임시 폴더 경로 (녹음 중에만 사용, 종료 시 이동)
    started_at = datetime.now()
    temp_folder = config.TEMP_RECORDING_DIR / f"session_{_session_slug(started_at)}"

    # meeting row
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO meetings
                    (client_id, meeting_type, started_at, temp_folder, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (
                    client["id"],
                    req.meeting_type,
                    started_at.isoformat(timespec="seconds"),
                    str(temp_folder),
                ),
            )
            meeting_id = cur.lastrowid
    except Exception as e:
        print(f"\n[new_meeting:db] {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
        raise HTTPException(500, f"상담 생성 실패: {type(e).__name__}: {e}")

    return {
        "meeting_id": meeting_id,
        "client_id": client["id"],
        "client_name": client["name"],
        "client_descriptor": client.get("descriptor"),
        "folder_name": req.folder_name,
        "folder_path": str(folder_path),
        "meeting_type": req.meeting_type,
        "started_at": started_at.isoformat(timespec="seconds"),
        "temp_folder": str(temp_folder),
        "status": "pending",
    }


# ========================================
# GET /api/meetings?folder={folder_name}
# 고객 폴더의 과거 상담 목록 (Phase 6C)
# ========================================
@router.get("")
def list_meetings_by_folder(folder: str):
    if not folder or "\\" in folder or "/" in folder:
        raise HTTPException(400, "유효하지 않은 폴더 이름입니다.")
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT m.id,
                   m.meeting_type,
                   m.started_at,
                   m.ended_at,
                   m.duration_sec,
                   m.status,
                   m.audio_file,
                   m.meeting_folder,
                   c.name AS client_name,
                   c.descriptor AS client_descriptor,
                   c.folder_name AS folder_name,
                   (SELECT COUNT(*) FROM transcript_segments WHERE meeting_id = m.id) AS segments_count,
                   (SELECT 1 FROM analyses WHERE meeting_id = m.id LIMIT 1) AS has_analysis
            FROM meetings m
            JOIN clients c ON c.id = m.client_id
            WHERE c.folder_name = ?
              AND m.meeting_folder IS NOT NULL
              AND m.status IN ('recorded', 'analyzing', 'done', 'failed')
            ORDER BY m.started_at DESC
            """,
            (folder,),
        ).fetchall()
    items = []
    for r in rows:
        d = {k: r[k] for k in r.keys()}
        d["has_analysis"] = bool(d.get("has_analysis"))
        # 디스크 상에 mp3 가 실제로 있는지 표시 (이전 폴더 이동 등 검증)
        af = d.get("audio_file")
        d["audio_exists"] = bool(af and Path(af).exists())
        items.append(d)
    return {
        "folder_name": folder,
        "count": len(items),
        "meetings": items,
    }


# ========================================
# GET /api/meetings/{id}
# ========================================
@router.get("/{meeting_id}")
def get_meeting(meeting_id: int):
    with db_cursor() as cur:
        row = cur.execute(
            """
            SELECT m.*, c.name AS client_name, c.descriptor AS client_descriptor,
                   c.folder_name AS folder_name, c.folder_path AS folder_path
            FROM meetings m
            JOIN clients c ON c.id = m.client_id
            WHERE m.id = ?
            """,
            (meeting_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, f"meeting {meeting_id} not found")
    return {k: row[k] for k in row.keys()}


# ========================================
# GET /api/meetings/{id}/segments
# ========================================
@router.get("/{meeting_id}/segments")
def list_segments(meeting_id: int):
    return {"segments": meeting_finalizer.load_segments_from_db(meeting_id)}


# ========================================
# GET /api/meetings/{id}/audio
# 상담 폴더의 녹음.mp3 를 그대로 스트리밍 (Phase 6C)
# FastAPI FileResponse 가 Range 요청을 자동 처리 → 브라우저 audio 엘리먼트 seek 가능
# ========================================
@router.get("/{meeting_id}/audio")
def get_audio(meeting_id: int):
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT audio_file, meeting_folder FROM meetings WHERE id = ?",
            (meeting_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, f"meeting {meeting_id} not found")

    audio_path: Optional[Path] = None
    if row["audio_file"]:
        candidate = Path(row["audio_file"])
        if candidate.exists():
            audio_path = candidate
    if audio_path is None and row["meeting_folder"]:
        candidate = Path(row["meeting_folder"]) / "녹음.mp3"
        if candidate.exists():
            audio_path = candidate
    if audio_path is None:
        raise HTTPException(404, "오디오 파일을 찾을 수 없습니다 (이동·삭제됐거나 경로 변경).")

    return FileResponse(
        str(audio_path),
        media_type="audio/mpeg",
        filename=audio_path.name,
    )


# ========================================
# POST /api/meetings/{id}/segments/{seg_id}/speaker
# ========================================
class SpeakerUpdateRequest(BaseModel):
    speaker: Optional[str] = None  # 'me' | 'client' | None


@router.post("/{meeting_id}/segments/{segment_id}/speaker")
def update_segment_speaker(
    meeting_id: int, segment_id: int, req: SpeakerUpdateRequest
):
    """
    녹음 완료 후 세그먼트의 화자 라벨 변경.
    DB 업데이트 + 대화전문.md 재생성.
    """
    if req.speaker not in (None, "me", "client"):
        raise HTTPException(400, f"invalid speaker: {req.speaker}")

    with db_cursor() as cur:
        row = cur.execute(
            "SELECT id FROM transcript_segments WHERE id = ? AND meeting_id = ?",
            (segment_id, meeting_id),
        ).fetchone()
        if row is None:
            raise HTTPException(
                404, f"segment {segment_id} not found in meeting {meeting_id}"
            )
        cur.execute(
            "UPDATE transcript_segments SET speaker = ? WHERE id = ?",
            (req.speaker, segment_id),
        )

    # 대화전문.md 재생성 (실패해도 DB 업데이트는 성공 상태)
    md_warning = None
    try:
        meeting_finalizer.regenerate_transcript_md(meeting_id)
    except Exception as e:
        import traceback as _tb
        md_warning = f"{type(e).__name__}: {e}"
        print(f"\n[regenerate_md] {md_warning}\n{_tb.format_exc()}", flush=True)

    return {
        "segment_id": segment_id,
        "speaker": req.speaker,
        "md_warning": md_warning,
    }


# ========================================
# v2.5.1 — 상담 자유 메모 (녹음 외 디자이너 직접 입력)
# ========================================
class MeetingNotesRequest(BaseModel):
    notes: str


# ========================================
# v2.5.1 H1 — AI 분석 결과 기반 고객 폴더명 수정 제안
# ========================================
class FolderRenameSuggestRequest(BaseModel):
    site_info: dict


@router.post("/{meeting_id}/suggest-folder-name")
def suggest_folder_name_for_meeting(meeting_id: int, req: FolderRenameSuggestRequest):
    """site_info dict → 권장 descriptor 반환 (rename 안 함, 단순 제안)."""
    desc = folder_rename.suggest_descriptor_from_site_info(req.site_info or {})
    if not desc:
        return {"ok": False, "reason": "권장할 만한 정보가 부족합니다 (단지명·평형 등이 분석 결과에 없음)."}
    # current folder for context
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT c.id AS client_id, c.name, c.descriptor, c.folder_name "
            "FROM meetings m JOIN clients c ON c.id = m.client_id WHERE m.id = ?",
            (meeting_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "meeting not found")
    return {
        "ok": True,
        "client_id": row["client_id"],
        "current_folder_name": row["folder_name"],
        "current_descriptor": row["descriptor"],
        "suggested_descriptor": desc,
        "suggested_folder_name": f"{row['name']} 고객님({desc})",
    }


class FolderRenameApplyRequest(BaseModel):
    client_id: int
    new_descriptor: str


@router.post("/folder-rename/apply")
def apply_folder_rename(req: FolderRenameApplyRequest):
    """디스크 폴더 + DB 일괄 rename. 사용자 명시적 수락 후 호출."""
    try:
        result = folder_rename.rename_client_folder(req.client_id, req.new_descriptor)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback as _tb
        print(f"[folder_rename] {type(e).__name__}: {e}\n{_tb.format_exc()}", flush=True)
        raise HTTPException(500, f"폴더 rename 실패: {type(e).__name__}: {str(e)[:300]}")


@router.patch("/{meeting_id}/notes")
def update_meeting_notes(meeting_id: int, req: MeetingNotesRequest):
    new_notes = req.notes or ""
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT id FROM meetings WHERE id = ?", (meeting_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"meeting {meeting_id} not found")
        cur.execute(
            "UPDATE meetings SET notes = ? WHERE id = ?",
            (new_notes, meeting_id),
        )
    return {"meeting_id": meeting_id, "notes_length": len(new_notes)}


# ========================================
# v3.2.0 Phase 4: 준비 노트 (상담 전 메모)
# 상담 시작 전에 디자이너가 미리 적는 메모 (이전 상담 확인사항, 질문 목록 등)
# ========================================
class PreNotesRequest(BaseModel):
    pre_notes: str


@router.get("/{meeting_id}/pre-notes")
def get_pre_notes(meeting_id: int):
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT pre_notes FROM meetings WHERE id = ?", (meeting_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, f"meeting {meeting_id} not found")
    return {"meeting_id": meeting_id, "pre_notes": row["pre_notes"] or ""}


@router.patch("/{meeting_id}/pre-notes")
def update_pre_notes(meeting_id: int, req: PreNotesRequest):
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT id FROM meetings WHERE id = ?", (meeting_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"meeting {meeting_id} not found")
        cur.execute(
            "UPDATE meetings SET pre_notes = ? WHERE id = ?",
            (req.pre_notes or "", meeting_id),
        )
    return {"meeting_id": meeting_id, "pre_notes_length": len(req.pre_notes or "")}


# ========================================
# Phase 8A — 녹음 종료 후 카드 텍스트 편집
# ========================================
class SegmentTextUpdateRequest(BaseModel):
    text: str


@router.patch("/{meeting_id}/segments/{segment_id}/text")
def update_segment_text(
    meeting_id: int, segment_id: int, req: SegmentTextUpdateRequest
):
    """
    저장된 세그먼트의 text 를 사용자 편집으로 교체.
    edited_at 갱신 → 이후 retranscribe 가 이 카드를 보존(시간 겹침 시 새 카드 폐기).
    DB + 대화전문.md 재생성.
    """
    new_text = (req.text or "").strip()
    if not new_text:
        raise HTTPException(400, "빈 텍스트로 교체할 수 없습니다.")

    with db_cursor() as cur:
        row = cur.execute(
            "SELECT id FROM transcript_segments WHERE id = ? AND meeting_id = ?",
            (segment_id, meeting_id),
        ).fetchone()
        if row is None:
            raise HTTPException(
                404, f"segment {segment_id} not found in meeting {meeting_id}"
            )
        cur.execute(
            "UPDATE transcript_segments "
            "SET text = ?, edited_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (new_text, segment_id),
        )

    # 대화전문.md 재생성 (실패해도 DB 업데이트는 성공)
    md_warning = None
    try:
        meeting_finalizer.regenerate_transcript_md(meeting_id)
    except Exception as e:
        import traceback as _tb
        md_warning = f"{type(e).__name__}: {e}"
        print(f"\n[regenerate_md_text_edit] {md_warning}\n{_tb.format_exc()}", flush=True)

    return {
        "segment_id": segment_id,
        "text": new_text,
        "md_warning": md_warning,
    }


# ========================================
# POST /api/meetings/{id}/retranscribe
# Two-pass 후처리 — 더 큰 모델로 재전사
# ========================================
class RetranscribeRequest(BaseModel):
    model_size: Optional[str] = "medium"  # tiny / base / small / medium / large-v3


# ========================================
# Phase 8B+: 재전사 되돌리기 (snapshot 복원)
# ========================================
@router.get("/{meeting_id}/snapshot")
def get_snapshot_info(meeting_id: int):
    """이 meeting 의 되돌리기용 스냅샷이 있는지 확인."""
    snap = meeting_finalizer.load_segments_snapshot(meeting_id)
    if snap is None:
        return {"available": False}
    return {
        "available": True,
        "label": snap["label"],
        "created_at": snap["created_at"],
        "segments_count": snap["segments_count"],
    }


@router.post("/{meeting_id}/retranscribe/undo")
def retranscribe_undo(meeting_id: int):
    """저장된 스냅샷으로 재전사 결과를 되돌림. 대화전문.md 도 재생성."""
    try:
        result = meeting_finalizer.restore_segments_from_snapshot(meeting_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        import traceback as _tb
        print(f"\n[retranscribe_undo] {type(e).__name__}: {e}\n{_tb.format_exc()}", flush=True)
        raise HTTPException(500, f"되돌리기 실패: {type(e).__name__}: {e}")
    return {"ok": True, **result}


@router.post("/{meeting_id}/retranscribe")
def retranscribe(meeting_id: int, req: RetranscribeRequest):
    """
    녹음 종료 후 더 정확한 모델로 전체 WAV 재전사.
    transcript_segments 교체 + 대화전문.md 재생성.
    화자 라벨은 시간 겹침으로 자동 이관.
    """
    size = (req.model_size or settings_service.get_last_post_model()).strip()
    valid_sizes = ["tiny", "base", "small", "medium", "large-v3"]
    if size not in valid_sizes:
        raise HTTPException(400, f"허용되지 않는 모델: {size}. 가능: {valid_sizes}")
    # v2.5.0: 사용자가 매번 medium 으로 리셋되는 게 싫다고 해서, 선택된 사이즈를 다음에도 기억
    try:
        settings_service.set_last_post_model(size)
    except Exception:
        pass
    try:
        result = retranscribe_service.retranscribe_meeting(
            meeting_id, model_size=size
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        # v2.4.5: print 가 실패해도 원본 예외 잃지 않게 try/except 로 감쌈
        # + 에러 메시지 ASCII 안전화 (em-dash → hyphen)
        try:
            import traceback as _tb
            print(
                f"\n[retranscribe] {type(e).__name__}: {e}\n{_tb.format_exc()}",
                flush=True,
            )
        except Exception:
            pass
        # 메시지에 em-dash 안 씀, ASCII 하이픈만 사용
        raise HTTPException(
            500, f"재전사 실패 - {type(e).__name__}: {str(e)[:400]}"
        )
    return result


# ========================================
# v2.6.0 K — 태그 시스템
# ========================================
class TagsUpdateRequest(BaseModel):
    tags: list[str] = Field(default_factory=list)


@router.get("/{meeting_id}/tags")
def get_tags(meeting_id: int):
    return {
        "meeting_id": meeting_id,
        "tags": tags_service.list_tags_for_meeting(meeting_id),
    }


@router.put("/{meeting_id}/tags")
def put_tags(meeting_id: int, req: TagsUpdateRequest):
    tags = tags_service.set_tags_for_meeting(meeting_id, req.tags)
    return {"meeting_id": meeting_id, "tags": tags}


@router.get("/tags/all")
def get_all_known_tags():
    """전체 DB 의 사용된 태그 + config 의 추천 시드 합집합 (자동완성용)."""
    used = tags_service.all_known_tags()
    seeds = list(config.DEFAULT_TAG_SUGGESTIONS)
    seen = set()
    out: list[str] = []
    for t in used + seeds:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return {"tags": out}


# ========================================
# v2.6.0 L — 계약 진행률 (clients.stage)
# ========================================
class StageUpdateRequest(BaseModel):
    stage: str


@router.get("/{meeting_id}/stage-suggestion")
def get_stage_suggestion(meeting_id: int):
    """이 상담의 meeting_type 기반으로 client.stage 다음 단계 추천."""
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT m.meeting_type, m.client_id, c.stage "
            "FROM meetings m JOIN clients c ON c.id = m.client_id "
            "WHERE m.id = ?",
            (meeting_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "meeting not found")
    suggested = stage_service.suggest_stage_from_meeting_type(
        row["stage"] or config.CLIENT_STAGE_DEFAULT, row["meeting_type"]
    )
    return {
        "client_id": row["client_id"],
        "current_stage": row["stage"] or config.CLIENT_STAGE_DEFAULT,
        "suggested_stage": suggested,
        "stages": config.CLIENT_STAGES,
    }


# ========================================
# v3.0.0 Phase 1 — 카톡 안내 문구 자동 생성
# ========================================
_KAKAO_TEMPLATES = {
    "초도상담": (
        "안녕하세요, {client_name} 고객님! 😊\n\n"
        "오늘 {store}에 방문해 주셔서 감사합니다.\n"
        "담당 디자이너 {designer_name}입니다.\n\n"
        "상담 중 말씀해 주신 내용들 꼼꼼히 정리해서\n"
        "빠르게 연락드리겠습니다 📋\n\n"
        "궁금한 점이나 추가로 말씀하실 것이 있으시면\n"
        "언제든지 편하게 연락 주세요! 😊"
    ),
    "디자인미팅": (
        "안녕하세요, {client_name} 고객님! 😊\n\n"
        "오늘 디자인 미팅 함께해 주셔서 감사합니다.\n"
        "담당 디자이너 {designer_name}입니다.\n\n"
        "오늘 보여드린 디자인 안 충분히 검토해 보신 후,\n"
        "수정 요청이나 추가 문의 사항이 있으시면\n"
        "편하게 연락 주세요! 🏠\n\n"
        "좋은 공간 만들어 드릴 수 있도록 최선을 다하겠습니다."
    ),
    "견적미팅": (
        "안녕하세요, {client_name} 고객님! 😊\n\n"
        "오늘 견적 미팅 함께해 주셔서 감사합니다.\n"
        "담당 디자이너 {designer_name}입니다.\n\n"
        "오늘 안내드린 견적서 천천히 검토해 보시고,\n"
        "조정이 필요한 부분이 있으시면 편하게 말씀해 주세요 💬\n\n"
        "항상 합리적인 방향으로 함께 고민하겠습니다!"
    ),
}


@router.get("/{meeting_id}/kakao-message")
def get_kakao_message(meeting_id: int, request: Request):
    """
    상담 종류 + 고객명 + 담당자 설정 기반으로 카톡 안내 문구 생성.
    편집 가능한 초안 텍스트를 반환. 전송은 사용자가 직접.
    """
    with db_cursor() as cur:
        row = cur.execute(
            """
            SELECT m.meeting_type, m.started_at,
                   c.name AS client_name, c.phone AS client_phone
            FROM meetings m
            JOIN clients c ON c.id = m.client_id
            WHERE m.id = ?
            """,
            (meeting_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "meeting not found")

    # v3.5.2: 로그인 사용자별 담당자 정보
    _u = (getattr(request.state, "user", None) or {}).get("sub")
    designer = settings_service.get_designer_info(username=_u)
    meeting_type = row["meeting_type"]
    template = _KAKAO_TEMPLATES.get(meeting_type, _KAKAO_TEMPLATES["초도상담"])

    # 서명 라인 (전화번호 있으면 추가)
    sign_lines = [f"📌 {designer['store']}" if designer.get("store") else "",
                  f"👤 {designer['name']}" if designer.get("name") else ""]
    if designer.get("phone"):
        sign_lines.append(f"📱 {designer['phone']}")
    sign = "\n".join(s for s in sign_lines if s)

    body = template.format(
        client_name=row["client_name"],
        designer_name=designer["name"],
        store=designer["store"] or "저희 매장",
    )
    if sign:
        body = body + "\n\n" + sign

    return {
        "meeting_id": meeting_id,
        "meeting_type": meeting_type,
        "client_name": row["client_name"],
        "client_phone": row["client_phone"],
        "message": body,
        "designer": designer,
    }

