"""
v2.6.0 L — 계약 진행률 (clients.stage 컬럼).

단계: 초도 → 디자인 → 견적 → 계약 → 시공 → 완료.

AI 분석 후 자동 추천:
  meeting_type 이 견적미팅 + 분석 결과의 site_info 충실 → '견적' 단계 추천
  meeting_type 이 디자인미팅 → '디자인' 추천
  meeting_type 이 초도상담 → '초도' (기본값, 변화 없음)

UI 가 사용자에게 "[견적] 단계로 변경할까요?" 물음. 자동 적용 안 함 (계약 단계는 영업 판단이라 사용자만이 결정).
"""
from __future__ import annotations

from app.config import CLIENT_STAGES, CLIENT_STAGE_DEFAULT
from app.db import db_cursor


def get_stage(client_id: int) -> str:
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT stage FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        if not row:
            return CLIENT_STAGE_DEFAULT
        return row["stage"] or CLIENT_STAGE_DEFAULT


def set_stage(client_id: int, stage: str) -> str:
    if stage not in CLIENT_STAGES:
        raise ValueError(f"invalid stage: {stage} (가능: {CLIENT_STAGES})")
    with db_cursor() as cur:
        cur.execute("UPDATE clients SET stage = ? WHERE id = ?", (stage, client_id))
    return stage


def stage_index(stage: str) -> int:
    """0-based index. 모르는 값이면 0."""
    try:
        return CLIENT_STAGES.index(stage or CLIENT_STAGE_DEFAULT)
    except ValueError:
        return 0


def suggest_stage_from_meeting_type(current_stage: str, meeting_type: str) -> str | None:
    """meeting_type 기반 다음 단계 추천. 이미 그 단계 이상이면 None.

    - 초도상담 → '초도'
    - 디자인미팅 → '디자인'
    - 견적미팅 → '견적'
    """
    mapping = {
        "초도상담": "초도",
        "디자인미팅": "디자인",
        "견적미팅": "견적",
    }
    target = mapping.get(meeting_type)
    if not target:
        return None
    if stage_index(current_stage) >= stage_index(target):
        return None  # 이미 동등하거나 더 진행됨 — 추천 안 함
    return target


# v2.6.0 P: 즐겨찾기 toggle (clients.is_favorite)
def toggle_favorite(client_id: int) -> bool:
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT COALESCE(is_favorite, 0) AS f FROM clients WHERE id = ?",
            (client_id,),
        ).fetchone()
        new = 0 if (row and row["f"]) else 1
        cur.execute("UPDATE clients SET is_favorite = ? WHERE id = ?", (new, client_id))
    return bool(new)


def update_last_meeting_at(client_id: int, ts: str | None) -> None:
    """meeting 종료 시점에 호출 — 정렬 캐시."""
    with db_cursor() as cur:
        cur.execute(
            "UPDATE clients SET last_meeting_at = ? WHERE id = ?",
            (ts, client_id),
        )
