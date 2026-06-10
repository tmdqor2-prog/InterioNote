"""
상담 통계 대시보드.
GET /api/stats — 월별 상담 건수 / 평균 길이 / 종류 비중 / 계약 퍼널 등 집계.
v3.2.0: 계약 단계 퍼널 + 계약률 추가.
v3.5.7: 영업 대시보드 추가 — 매출 추이, 방문경로별 전환율, 객단가.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

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


# ─── v3.5.7: 영업 대시보드 ────────────────────────────────────────────────────

@router.get("/api/sales/dashboard")
def sales_dashboard() -> Dict[str, Any]:
    """매출·전환율·객단가·방문경로 등 영업 인사이트."""
    with db_cursor() as cur:
        # 모든 고객 + 단계 + 방문경로
        client_rows = cur.execute(
            "SELECT id, name, stage, visit_source, created_at, last_meeting_at FROM clients"
        ).fetchall()
        # 모든 상담 + 계약 정보
        meeting_rows = cur.execute(
            "SELECT id, client_id, meeting_type, started_at, "
            "       contract_amount, deposit_amount, contract_date "
            "FROM meetings WHERE started_at IS NOT NULL"
        ).fetchall()

    # 1) 월별 매출 (계약 금액 기준)
    monthly_revenue: Dict[str, float] = defaultdict(float)
    monthly_contracts: Dict[str, int] = defaultdict(int)
    for m in meeting_rows:
        if m["contract_amount"] and m["contract_date"]:
            month = (m["contract_date"] or "")[:7]
            if month:
                monthly_revenue[month] += float(m["contract_amount"])
                monthly_contracts[month] += 1
    monthly_revenue_sorted = sorted(monthly_revenue.items())
    monthly_revenue_list = [
        {"month": k, "revenue": v, "contracts": monthly_contracts[k]}
        for k, v in monthly_revenue_sorted
    ]

    # 2) 방문 경로별 분석
    by_source: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "total": 0, "contracted": 0, "revenue": 0.0
    })
    client_id_to_source: Dict[int, str] = {}
    for c in client_rows:
        src = (c["visit_source"] or "기타").strip() or "기타"
        client_id_to_source[c["id"]] = src
        by_source[src]["total"] += 1
        # 계약 단계 이상이면 contracted
        if c["stage"] in ("계약", "시공", "완료"):
            by_source[src]["contracted"] += 1

    # 매출도 client 매핑
    client_revenue: Dict[int, float] = defaultdict(float)
    for m in meeting_rows:
        if m["contract_amount"]:
            client_revenue[m["client_id"]] += float(m["contract_amount"])
    for cid, rev in client_revenue.items():
        src = client_id_to_source.get(cid, "기타")
        by_source[src]["revenue"] += rev

    # 전환율 계산
    by_source_list = []
    for src, d in by_source.items():
        rate = round(d["contracted"] / d["total"] * 100, 1) if d["total"] > 0 else 0
        avg_revenue = round(d["revenue"] / d["contracted"], 0) if d["contracted"] > 0 else 0
        by_source_list.append({
            "source": src,
            "total_clients": d["total"],
            "contracted": d["contracted"],
            "conversion_rate": rate,
            "total_revenue": round(d["revenue"], 0),
            "avg_revenue": avg_revenue,
        })
    by_source_list.sort(key=lambda x: x["total_revenue"], reverse=True)

    # 3) 평균 객단가 (전체)
    total_contracts = sum(by_source[s]["contracted"] for s in by_source)
    total_revenue = sum(by_source[s]["revenue"] for s in by_source)
    avg_deal_size = round(total_revenue / total_contracts, 0) if total_contracts > 0 else 0

    # 4) 단계별 분포
    stage_dist: Dict[str, int] = Counter()
    for c in client_rows:
        stage_dist[c["stage"] or "초도"] += 1

    # 5) 상위 고객 (매출 기준)
    client_name_map = {c["id"]: c["name"] for c in client_rows}
    top_revenue_clients = sorted(client_revenue.items(), key=lambda x: x[1], reverse=True)[:10]
    top_revenue_list = [
        {"client_id": cid, "name": client_name_map.get(cid, "?"), "revenue": round(rev, 0)}
        for cid, rev in top_revenue_clients
    ]

    # 6) 퍼널 (단계별 카운트)
    stage_order = ["초도", "디자인", "견적", "계약", "시공", "완료"]
    funnel = []
    cumulative = sum(stage_dist[s] for s in stage_order)
    for stage in stage_order:
        count = stage_dist.get(stage, 0)
        rate = round(count / cumulative * 100, 1) if cumulative > 0 else 0
        funnel.append({"stage": stage, "count": count, "rate": rate})

    return {
        "monthly_revenue": monthly_revenue_list,
        "by_source": by_source_list,
        "stage_distribution": [{"stage": k, "count": v} for k, v in stage_dist.items()],
        "funnel": funnel,
        "top_clients_by_revenue": top_revenue_list,
        "summary": {
            "total_clients": len(client_rows),
            "total_contracts": total_contracts,
            "total_revenue": round(total_revenue, 0),
            "avg_deal_size": avg_deal_size,
            "active_meetings": len(meeting_rows),
        },
    }
