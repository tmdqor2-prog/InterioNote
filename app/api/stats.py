"""
상담 통계 대시보드.
GET /api/stats — 월별 상담 건수 / 평균 길이 / 종류 비중 / 계약 퍼널 등 집계.
v3.2.0: 계약 단계 퍼널 + 계약률 추가.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from fastapi import APIRouter

from app import config
from app.db import db_cursor

router = APIRouter(tags=["stats"])


@router.get("/api/stats")
def get_stats() -> Dict[str, Any]:
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT m.id, m.meeting_type, m.started_at, m.duration_sec, m.status,
                   c.id AS client_id, c.name AS client_name
            FROM meetings m
            JOIN clients c ON c.id = m.client_id
            WHERE m.started_at IS NOT NULL
            ORDER BY m.started_at DESC
            """
        ).fetchall()
        client_count = cur.execute("SELECT COUNT(*) AS n FROM clients").fetchone()["n"]

        # v3.2.0: 계약 단계별 고객 수 (퍼널용)
        stage_rows = cur.execute(
            "SELECT COALESCE(stage, '초도') AS stage, COUNT(*) AS cnt "
            "FROM clients GROUP BY COALESCE(stage, '초도')"
        ).fetchall()

    meetings = [{k: r[k] for k in r.keys()} for r in rows]

    # 전체 합계
    total_meetings = len(meetings)
    completed = [m for m in meetings if m.get("status") in ("recorded", "analyzing", "done")]
    total_duration_sec = sum(int(m.get("duration_sec") or 0) for m in completed)
    avg_duration_sec = (total_duration_sec / len(completed)) if completed else 0

    # 종류별 비중
    by_type = Counter(m.get("meeting_type") or "기타" for m in meetings)

    # 월별 건수 (최근 6개월)
    monthly: Dict[str, int] = defaultdict(int)
    for m in meetings:
        ts = m.get("started_at") or ""
        if len(ts) >= 7:
            ym = ts[:7]  # YYYY-MM
            monthly[ym] += 1
    monthly_sorted = sorted(monthly.items())[-6:]

    # 고객별 상담 건수 top 5
    by_client: Dict[int, Dict[str, Any]] = {}
    for m in meetings:
        cid = m.get("client_id")
        if cid is None:
            continue
        if cid not in by_client:
            by_client[cid] = {"client_name": m.get("client_name"), "count": 0}
        by_client[cid]["count"] += 1
    top_clients = sorted(by_client.values(), key=lambda x: x["count"], reverse=True)[:5]

    # v3.2.0: 계약 단계 퍼널
    # stages 순서: 초도 → 디자인 → 견적 → 계약 → 시공 → 완료
    stages = config.CLIENT_STAGES  # ["초도","디자인","견적","계약","시공","완료"]
    stage_cnt: Dict[str, int] = {s: 0 for s in stages}
    for r in stage_rows:
        if r["stage"] in stage_cnt:
            stage_cnt[r["stage"]] = r["cnt"]
    # 누적(계약 이상) 고객 수 = 계약+시공+완료
    contract_stages = {"계약", "시공", "완료"}
    contracted = sum(stage_cnt.get(s, 0) for s in contract_stages)
    contract_rate = round(contracted / client_count * 100, 1) if client_count > 0 else 0.0

    funnel = [
        {"stage": s, "count": stage_cnt.get(s, 0)}
        for s in stages
    ]

    # ⑯ v3.5.0: 재방문 고객 — 2회 이상 상담한 고객 (방문 충성도 분석)
    returning_clients = [
        {"client_name": v["client_name"], "count": v["count"]}
        for v in by_client.values()
        if v["count"] >= 2
    ]
    returning_clients.sort(key=lambda x: x["count"], reverse=True)

    return {
        "client_count": client_count,
        "total_meetings": total_meetings,
        "completed_meetings": len(completed),
        "total_duration_sec": total_duration_sec,
        "total_duration_hours": round(total_duration_sec / 3600, 1),
        "avg_duration_sec": round(avg_duration_sec, 0),
        "avg_duration_min": round(avg_duration_sec / 60, 1),
        "by_meeting_type": dict(by_type),
        "monthly": [{"month": k, "count": v} for k, v in monthly_sorted],
        "top_clients": top_clients,
        # v3.2.0
        "funnel": funnel,
        "contracted": contracted,
        "contract_rate": contract_rate,
        # v3.5.0 ⑯
        "returning_clients": returning_clients,
        "returning_count": len(returning_clients),
    }
