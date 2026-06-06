"""
v2.6.0 EE — 고객 360 뷰 API.
v3.5.0 추가: 커스텀 필드(②), 소개 경로(③), 계약금액(⑮)

- GET    /api/clients/{client_id}/360           : 통합 대시보드
- POST   /api/clients/{client_id}/aggregate-summary : Ollama 누적 요약
- PATCH  /api/clients/{client_id}/custom-fields : 커스텀 필드 저장 ②
- PATCH  /api/clients/{client_id}/referral      : 소개 경로 저장 ③
- PATCH  /api/meetings/{meeting_id}/contract    : 계약금액 저장 ⑮
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from app import config
from app.db import db_cursor
from app.services import ollama_client, settings_service, tags_service

router = APIRouter(prefix="/api/clients", tags=["customer"])


@router.get("/{client_id}/360")
def get_customer_360(client_id: int):
    """고객 360 뷰 데이터.

    포함:
    - client 기본 정보 (id, name, descriptor, folder_name, stage, is_favorite, last_meeting_at)
    - 모든 상담 (시간순, 종류, 상태, 카드수, 분석 여부, 태그, OJT 동기화 여부)
    - 모든 태그 합집합 (빈도순)
    - 누적 분석 (cached, 별도 endpoint 로 갱신)
    """
    with db_cursor() as cur:
        c = cur.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        if c is None:
            raise HTTPException(404, "client not found")

        meetings = cur.execute(
            """
            SELECT m.id, m.meeting_type, m.started_at, m.ended_at, m.duration_sec,
                   m.status, m.notes, m.ojt_synced_at,
                   (SELECT COUNT(*) FROM transcript_segments WHERE meeting_id = m.id) AS segments_count,
                   (SELECT 1 FROM analyses WHERE meeting_id = m.id LIMIT 1) AS has_analysis
            FROM meetings m
            WHERE m.client_id = ?
            ORDER BY m.started_at DESC
            """,
            (client_id,),
        ).fetchall()

        # 각 미팅의 태그 + 분석 요약 첫줄
        meetings_out = []
        for m in meetings:
            tags = tags_service.list_tags_for_meeting(m["id"])
            summary_first = ""
            arow = cur.execute(
                "SELECT data_json FROM analyses WHERE meeting_id = ?", (m["id"],)
            ).fetchone()
            if arow:
                try:
                    a = json.loads(arow["data_json"])
                    s = (a.get("summary") or "").strip()
                    summary_first = s.split("\n")[0][:120] if s else ""
                except Exception:
                    pass
            meetings_out.append({
                "id": m["id"],
                "meeting_type": m["meeting_type"],
                "started_at": m["started_at"],
                "ended_at": m["ended_at"],
                "duration_sec": m["duration_sec"],
                "status": m["status"],
                "notes": m["notes"],
                "ojt_synced_at": m["ojt_synced_at"],
                "segments_count": m["segments_count"],
                "has_analysis": bool(m["has_analysis"]),
                "tags": tags,
                "summary_first_line": summary_first,
            })

        # 캐시된 누적 요약 (settings DB 의 client.{id}.aggregate_summary)
        cache_key = f"client.{client_id}.aggregate_summary"
        cache_at_key = f"client.{client_id}.aggregate_summary_at"
        cache_row = cur.execute(
            "SELECT value FROM settings WHERE key = ?", (cache_key,)
        ).fetchone()
        cache_at_row = cur.execute(
            "SELECT value FROM settings WHERE key = ?", (cache_at_key,)
        ).fetchone()

    # site_info 누적 (가장 최근 분석에서)
    site_info_latest: dict[str, Any] = {}
    for m in meetings_out:
        if m["has_analysis"]:
            with db_cursor() as cur:
                arow = cur.execute(
                    "SELECT data_json FROM analyses WHERE meeting_id = ?", (m["id"],)
                ).fetchone()
            if arow:
                try:
                    a = json.loads(arow["data_json"])
                    si = a.get("site_info") or {}
                    for k, v in si.items():
                        if v and k not in site_info_latest:
                            site_info_latest[k] = v
                except Exception:
                    pass

    # v3.5.0 ②③: 커스텀필드 + 소개경로 변수 준비
    custom_fields = {}
    try:
        custom_fields = json.loads(c["custom_fields"] or "{}")
    except Exception:
        pass
    referrer_name = None
    if c["referred_by_client_id"]:
        with db_cursor() as cur2:
            ref = cur2.execute(
                "SELECT name FROM clients WHERE id = ?", (c["referred_by_client_id"],)
            ).fetchone()
            referrer_name = ref["name"] if ref else None
    # referral_name: 자유 텍스트 소개자 (DB 고객 외)
    referral_name_free = c["referral_name"] if "referral_name" in c.keys() else None
    # 표시용: DB 고객 우선, 없으면 자유 텍스트
    display_referrer = referrer_name or referral_name_free or None

    return {
        "client": {
            "id": c["id"],
            "name": c["name"],
            "descriptor": c["descriptor"],
            "folder_name": c["folder_name"],
            "folder_path": c["folder_path"],
            "stage": c["stage"] or config.CLIENT_STAGE_DEFAULT,
            "is_favorite": bool(c["is_favorite"]),
            "first_met_at": c["first_met_at"],
            "last_meeting_at": c["last_meeting_at"],
            "stages": config.CLIENT_STAGES,
            # v3.0.0: 연락처
            "phone": c["phone"],
            "email": c["email"],
            "visit_source": c["visit_source"],
            # v3.5.0: 커스텀 필드 + 소개 경로 + 성향 프로파일
            "custom_fields": {k: v for k, v in custom_fields.items() if k != "personality"},
            "personality": custom_fields.get("personality"),
            "referred_by_client_id": c["referred_by_client_id"],
            "referrer_name": referrer_name,
            "referral_name_free": referral_name_free,  # 자유 텍스트 소개자
            "display_referrer": display_referrer,      # 표시용 (DB우선)
        },
        "meetings": meetings_out,
        "tags": tags_service.tags_for_client(client_id),
        "site_info": site_info_latest,
        "aggregate_summary": cache_row["value"] if cache_row else None,
        "aggregate_summary_at": cache_at_row["value"] if cache_at_row else None,
    }


@router.post("/{client_id}/aggregate-summary")
def regenerate_aggregate_summary(client_id: int, request: Request):
    """Ollama 로 모든 상담을 합쳐서 누적 요약 생성. 결과는 settings 캐시.

    실패 시 분석 요약들의 단순 concat 으로 fallback.
    """
    with db_cursor() as cur:
        c = cur.execute("SELECT name, descriptor FROM clients WHERE id = ?", (client_id,)).fetchone()
        if c is None:
            raise HTTPException(404, "client not found")
        # 모든 분석 결과 모음 (시간순)
        rows = cur.execute(
            """
            SELECT m.id, m.meeting_type, m.started_at, a.data_json, m.notes
            FROM meetings m
            LEFT JOIN analyses a ON a.meeting_id = m.id
            WHERE m.client_id = ?
            ORDER BY m.started_at
            """,
            (client_id,),
        ).fetchall()

    if not rows:
        raise HTTPException(400, "이 고객의 상담 기록이 없습니다.")

    # 각 상담의 요약 텍스트 합치기
    chunks: list[str] = []
    for r in rows:
        date = (r["started_at"] or "").split("T")[0]
        head = f"[{date} {r['meeting_type']}]"
        if r["data_json"]:
            try:
                a = json.loads(r["data_json"])
                summary = (a.get("summary") or "").strip()
                if summary:
                    chunks.append(f"{head}\n{summary}")
                # site_info 의 핵심
                si = a.get("site_info") or {}
                si_parts = [f"{k}={v}" for k, v in si.items() if v]
                if si_parts:
                    chunks.append(f"{head} 장소: {', '.join(si_parts)}")
            except Exception:
                pass
        if r["notes"]:
            chunks.append(f"{head} 메모: {r['notes'].strip()[:300]}")

    if not chunks:
        raise HTTPException(400, "분석 결과가 있는 상담이 없습니다 — 먼저 AI 분석을 실행해주세요.")

    combined = "\n\n".join(chunks)[:8000]  # Ollama context 제한

    # Ollama 호출 (실패 시 단순 합본)
    # v3.5.2: 사용자별 원격 Ollama 우선 + 자동 폴백
    aggregate_summary = ""
    try:
        username = (getattr(request.state, "user", None) or {}).get("sub")
        system_prompt = (
            "당신은 인테리어 상담을 분석하는 한국어 전문가입니다. "
            "한 고객의 여러 상담을 종합해서 영업 핵심을 추출합니다."
        )
        prompt = f"""[고객 정보] {c['name']} 고객님 ({c['descriptor'] or ''})

[모든 상담 내용]
{combined}

위 내용을 바탕으로 다음 5개 항목을 정리해서 한국어로 답해주세요:
1. 핵심 정보 (예산·평형·구조·확장 등)
2. 고객 취향과 선호
3. 주요 걱정거리·반대 의견
4. 결정자·의사결정 패턴
5. 다음 미팅 시 확인할 점

마크다운 형식으로, 항목별 3~5줄 이내로 간결하게."""
        resp = ollama_client.generate_with_fallback(
            username,
            model=config.OLLAMA_MODEL,
            prompt=prompt,
            system=system_prompt,
            format_json=False,
        )
        if isinstance(resp, dict):
            aggregate_summary = (resp.get("response") or "").strip()
        else:
            aggregate_summary = str(resp or "").strip()
        if not aggregate_summary:
            raise RuntimeError("Ollama 응답이 비어있습니다")
    except Exception as e:
        import traceback as _tb
        try:
            print(f"[aggregate_summary] {type(e).__name__}: {e}\n{_tb.format_exc()}", flush=True)
        except Exception:
            pass
        aggregate_summary = (
            f"⚠ AI 누적 요약 생성 실패 ({type(e).__name__}: {str(e)[:120]}). "
            "아래는 각 상담 요약의 단순 합본입니다.\n\n"
            + combined[:3000]
        )

    # 캐시 저장
    now_iso = json.dumps({"saved": True})  # placeholder
    from datetime import datetime as _dt
    now_str = _dt.now().isoformat(timespec="seconds")
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"client.{client_id}.aggregate_summary", aggregate_summary),
        )
        cur.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"client.{client_id}.aggregate_summary_at", now_str),
        )

    return {
        "client_id": client_id,
        "aggregate_summary": aggregate_summary,
        "aggregate_summary_at": now_str,
        "source_meeting_count": len(rows),
    }


# ========================================
# v3.5.0 ②: 고객 커스텀 필드 저장
# ========================================
class CustomFieldsRequest(BaseModel):
    fields: dict  # {"평수": "33평", "시공예정일": "2026-06-01", ...}


@router.patch("/{client_id}/custom-fields")
def update_custom_fields(client_id: int, req: CustomFieldsRequest):
    """고객 커스텀 필드(JSON) 업데이트."""
    with db_cursor() as cur:
        c = cur.execute("SELECT id FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not c:
            raise HTTPException(404, "고객을 찾을 수 없습니다.")
        cur.execute(
            "UPDATE clients SET custom_fields = ? WHERE id = ?",
            (json.dumps(req.fields, ensure_ascii=False), client_id),
        )
    return {"ok": True, "fields": req.fields}


# ========================================
# v3.5.0 ③: 소개 경로 (다른 고객 연결) 저장
# ========================================
class ReferralRequest(BaseModel):
    referred_by_client_id: Optional[int] = None  # DB 고객 연결
    referral_name: Optional[str] = None           # 자유 텍스트 소개자 (DB 고객 외)


@router.patch("/{client_id}/referral")
def update_referral(client_id: int, req: ReferralRequest):
    """소개 고객 연결 (DB 고객 또는 자유 텍스트)."""
    with db_cursor() as cur:
        c = cur.execute("SELECT id FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not c:
            raise HTTPException(404, "고객을 찾을 수 없습니다.")
        if req.referred_by_client_id and req.referred_by_client_id == client_id:
            raise HTTPException(400, "자기 자신을 소개자로 설정할 수 없습니다.")
        # DB 고객 연결 업데이트
        cur.execute(
            "UPDATE clients SET referred_by_client_id = ? WHERE id = ?",
            (req.referred_by_client_id, client_id),
        )
        # 자유 텍스트 소개자 업데이트
        referral_name_val = (req.referral_name or "").strip() or None
        # DB 고객이 설정되면 자유 텍스트 클리어, 아니면 저장
        if req.referred_by_client_id:
            referral_name_val = None
        cur.execute(
            "UPDATE clients SET referral_name = ? WHERE id = ?",
            (referral_name_val, client_id),
        )
        # 소개자 이름 조회
        referrer_name = None
        if req.referred_by_client_id:
            ref = cur.execute(
                "SELECT name FROM clients WHERE id = ?", (req.referred_by_client_id,)
            ).fetchone()
            referrer_name = ref["name"] if ref else None
    display_referrer = referrer_name or referral_name_val or None
    return {
        "ok": True,
        "referred_by_client_id": req.referred_by_client_id,
        "referrer_name": referrer_name,
        "referral_name_free": referral_name_val,
        "display_referrer": display_referrer,
    }


# ========================================
# v3.5.0 ⑮: 상담별 계약 금액 저장
# ========================================
class ContractRequest(BaseModel):
    contract_amount: Optional[float] = None   # 총 계약금액 (원)
    deposit_amount: Optional[float] = None    # 계약금 입금액
    contract_date: Optional[str] = None       # "YYYY-MM-DD"


@router.patch("/meetings/{meeting_id}/contract")
def update_contract(meeting_id: int, req: ContractRequest):
    """상담 계약 금액 정보 저장."""
    with db_cursor() as cur:
        m = cur.execute("SELECT id FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        if not m:
            raise HTTPException(404, "상담을 찾을 수 없습니다.")
        if req.contract_amount is not None:
            cur.execute("UPDATE meetings SET contract_amount = ? WHERE id = ?", (req.contract_amount, meeting_id))
        if req.deposit_amount is not None:
            cur.execute("UPDATE meetings SET deposit_amount = ? WHERE id = ?", (req.deposit_amount, meeting_id))
        if req.contract_date is not None:
            cur.execute("UPDATE meetings SET contract_date = ? WHERE id = ?", (req.contract_date, meeting_id))
    return {"ok": True}


# ========================================
# v3.5.0 ⑧: 성향 프로파일 수기 편집 저장
# ========================================
class PersonalityManualRequest(BaseModel):
    profile: dict


# ─── v3.5.7: 다음 미팅 자동 준비 ──────────────────────────────────────────────

@router.post("/{client_id}/next-meeting-prep")
def next_meeting_prep(client_id: int, request: Request):
    """고객의 모든 분석 결과 종합 → 다음 미팅 의제·준비물·추천 질문."""
    from app.services import next_meeting_prep_service
    user = getattr(request.state, "user", None)
    username = user.get("sub") if user else None
    try:
        return next_meeting_prep_service.prepare_next_meeting(client_id, username=username)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}")


@router.patch("/{client_id}/personality-manual")
def update_personality_manual(client_id: int, req: PersonalityManualRequest):
    """성향 프로파일 수기 편집 저장 (personality 키만 갱신, 나머지 custom_fields 보존)."""
    with db_cursor() as cur:
        c = cur.execute(
            "SELECT id, custom_fields FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        if not c:
            raise HTTPException(404, "고객을 찾을 수 없습니다.")
        cf = {}
        try:
            cf = json.loads(c["custom_fields"] or "{}")
        except Exception:
            pass
        cf["personality"] = req.profile
        cur.execute(
            "UPDATE clients SET custom_fields = ? WHERE id = ?",
            (json.dumps(cf, ensure_ascii=False), client_id),
        )
    return {"ok": True, "profile": req.profile}
