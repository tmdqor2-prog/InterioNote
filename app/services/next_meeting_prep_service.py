"""
v3.5.7 — 다음 미팅 자동 준비.

활용:
- 고객 360뷰에서 "🤖 다음 미팅 준비" 버튼
- 그 고객의 모든 과거 상담 분석 + 미결정·액션 아이템 + 우려사항 종합
- AI 가 다음 미팅 의제·준비물·추천 질문·예상 시간 생성
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.db import db_cursor
from app.services import ollama_client, settings_service

log = logging.getLogger("next_meeting_prep")


SYSTEM_PROMPT = (
    "[CRITICAL OUTPUT LANGUAGE RULE]\n"
    "You MUST respond entirely in KOREAN (한국어) ONLY.\n"
    "DO NOT use Chinese, Japanese, or English in output values.\n\n"
    "당신은 대한민국의 인테리어 디자이너 비서입니다.\n"
    "고객의 이전 상담들을 분석해서 다음 미팅을 효율적으로 준비할 수 있게 돕습니다.\n"
    "규칙:\n"
    "1) 출력은 JSON 만. 한국어 전용\n"
    "2) 의제는 미결정·중요 순서로 정렬\n"
    "3) 추천 질문은 고객이 명확히 답하기 좋은 형태 (Yes/No 보다 선택지)"
)


SCHEMA_TEXT = """{
  "next_meeting_type": "다음 미팅 추천 종류 (초도상담/디자인미팅/견적미팅 중 하나)",
  "context_summary": "이전 상담 요약 (3~5문장, 다음 미팅에 가져갈 컨텍스트)",
  "open_decisions": ["아직 결정 안 된 항목들 (구체적으로)"],
  "agenda": [
    {
      "topic": "의제 제목",
      "priority": "high / medium / low",
      "expected_minutes": "예상 소요 시간 (분 단위 숫자, 예: 10)",
      "details": "이 의제에서 다룰 세부 내용"
    }
  ],
  "preparation_items": ["디자이너가 미팅 전에 준비할 물건·자료 (도면, 자재 샘플, 견적서 등)"],
  "recommended_questions": ["고객에게 던질 추천 질문 (선택지 포함)"],
  "client_concerns_to_address": ["이전에 고객이 표현한 우려·걱정 — 다음 미팅에서 다뤄야 할"],
  "estimated_total_minutes": "전체 미팅 예상 시간 (분 숫자)",
  "follow_up_message_draft": "미팅 전날 보낼 카톡 안내 문구 초안"
}"""


def prepare_next_meeting(client_id: int, username: Optional[str] = None) -> Dict[str, Any]:
    """
    해당 고객의 모든 분석 결과를 종합해서 다음 미팅 준비 자료 생성.
    """
    with db_cursor() as cur:
        client = cur.execute(
            "SELECT id, name, descriptor, folder_name, stage FROM clients WHERE id = ?",
            (client_id,),
        ).fetchone()
        if client is None:
            raise ValueError(f"고객 {client_id} 를 찾을 수 없습니다.")

        # 과거 상담 분석 결과 모두 (시간순)
        rows = cur.execute(
            "SELECT m.meeting_type, m.started_at, a.data_json "
            "FROM meetings m LEFT JOIN analyses a ON a.meeting_id = m.id "
            "WHERE m.client_id = ? AND a.data_json IS NOT NULL "
            "ORDER BY m.started_at",
            (client_id,),
        ).fetchall()

    if not rows:
        raise ValueError("이 고객의 분석된 상담이 없습니다. 먼저 AI 분석을 1건 이상 실행해 주세요.")

    # 분석 결과 종합 (간결하게)
    history_chunks: List[str] = []
    for r in rows:
        try:
            d = json.loads(r["data_json"])
            chunk_lines = [
                f"### [{r['meeting_type']} @ {(r['started_at'] or '')[:10]}]",
            ]
            if d.get("summary"):
                chunk_lines.append(f"요약: {d['summary'][:300]}")
            if d.get("client_requests"):
                chunk_lines.append(f"요청: {', '.join(str(x) for x in d['client_requests'][:5])}")
            if d.get("pending_decisions"):
                chunk_lines.append(f"미결정: {', '.join(str(x) for x in d['pending_decisions'][:5])}")
            if d.get("action_items"):
                chunk_lines.append(f"액션: {', '.join(str(x) for x in d['action_items'][:5])}")
            if d.get("concerns"):
                chunk_lines.append(f"우려: {', '.join(str(x) for x in d['concerns'][:3])}")
            if d.get("agreed_items"):
                chunk_lines.append(f"합의: {', '.join(str(x) for x in d['agreed_items'][:5])}")
            history_chunks.append("\n".join(chunk_lines))
        except Exception:
            continue

    history_block = "\n\n".join(history_chunks)[:8000]  # 토큰 제한

    prompt = (
        f"### 고객 정보\n"
        f"고객명: {client['name']}\n"
        f"단지·평수: {client['descriptor'] or ''}\n"
        f"현재 단계: {client.get('stage') or '초도'}\n\n"
        f"### 이전 상담 내역 ({len(rows)}건)\n{history_block}\n\n"
        f"### 출력 스키마\n```json\n{SCHEMA_TEXT}\n```\n\n"
        "### 출력 규칙\n"
        "- 위 스키마 그대로 JSON 객체 하나만 출력\n"
        "- agenda 는 3~6개. priority 기준 high → low 순서\n"
        "- recommended_questions 는 3~5개. 답하기 좋게 선택지 포함\n"
        "- preparation_items 는 구체적인 물건·자료명으로 (모호한 '준비물' 금지)\n"
        "- 모든 값 한국어. 중국어·영어 금지\n\n"
        "[REMINDER] 한국어 JSON only."
    )

    model = settings_service.get_ollama_model()
    log.info(f"next_meeting_prep client={client_id} model={model} user={username}")
    resp = ollama_client.generate_with_fallback(
        username,
        model=model,
        prompt=prompt,
        system=SYSTEM_PROMPT,
        format_json=True,
        options={
            "temperature": 0.2, "top_p": 0.9,
            "num_ctx": 8192, "num_predict": 3000,
        },
    )
    raw = resp.get("response") or ""
    try:
        prep = json.loads(raw)
    except Exception as e:
        log.warning(f"next_meeting_prep JSON parse 실패: {e}")
        return {"ok": False, "error": "AI 응답이 JSON 형식이 아닙니다.", "raw_response": raw[:5000]}

    return {
        "ok": True,
        "client_id": client_id,
        "client_name": client["name"],
        "based_on_meetings": len(rows),
        "model_used": model,
        "prep": prep,
        "used_endpoint": resp.get("_used_endpoint", "local"),
    }
