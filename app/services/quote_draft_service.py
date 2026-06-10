"""
v3.5.7 — AI 견적 초안 자동 생성.

기존 quote_service (v2.8.0) 는 xlsx 양식 자동 채우기.
이건 그것과 별개로 **AI 가 분석 결과 기반으로 견적 항목·예상 금액을 텍스트로 작성**.

용도:
- 견적 미팅 전에 디자이너가 "대략 이정도 금액 견적" 빠른 초안 받기
- 분석 결과의 평수·자재·요구사항 종합
- Ollama 호출 (원격 데스크톱 위임 가능)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from app.db import db_cursor
from app.services import ollama_client, settings_service

log = logging.getLogger("quote_draft")


SYSTEM_PROMPT = (
    "[CRITICAL OUTPUT LANGUAGE RULE]\n"
    "You MUST respond entirely in KOREAN (한국어) ONLY.\n"
    "DO NOT use Chinese, Japanese, or English in output values.\n\n"
    "당신은 대한민국의 숙련된 인테리어 견적 산출 전문가입니다.\n"
    "상담에서 추출된 정보(평수·구조·자재·요구사항)를 바탕으로 견적 초안을 작성합니다.\n"
    "규칙:\n"
    "1) 출력은 JSON 만. 마크다운·코드펜스·설명 금지\n"
    "2) 금액은 한국 인테리어 시장 평균 단가 기반으로 합리적으로 추정 (절대 0원 X)\n"
    "3) 평수와 자재 등급에 따라 가격 차등 — 고급 자재일수록 단가 ↑\n"
    "4) 모든 값은 한국어로 작성 (중국어 한자·영어 금지)\n"
    "5) 평수 정보 없으면 32평 기준 추정 (그 점을 가정으로 표시)"
)


SCHEMA_TEXT = """{
  "total_estimate": "총 예상 금액 (원문 형식, 예: '약 4,500만원')",
  "size_pyeong": "기준 평수 (숫자 + 평)",
  "scope_summary": "공사 범위 1~2문장",
  "items": [
    {
      "category": "공사 카테고리 (예: 철거, 도배, 강마루, 욕실, 주방, 조명, 도장 등)",
      "scope": "세부 작업 내용",
      "estimated_price": "예상 금액 (원문, 예: '약 280만원')",
      "note": "참고 사항 (자재 등급·옵션 등) — 비어있으면 빈 문자열"
    }
  ],
  "assumptions": ["견적 산출 시 가정한 사항들 (리스트)"],
  "variability_note": "최종 견적이 달라질 수 있는 변수 (1~2문장)"
}"""


def generate_quote_draft(meeting_id: int, username: Optional[str] = None) -> Dict[str, Any]:
    """
    상담 분석 결과 + 메타데이터를 바탕으로 AI 견적 초안 생성.
    이미 analyses 행이 있어야 함 (없으면 ValueError).
    """
    with db_cursor() as cur:
        meeting = cur.execute(
            "SELECT m.id, m.meeting_type, c.name as client_name, c.descriptor as client_descriptor "
            "FROM meetings m JOIN clients c ON c.id = m.client_id WHERE m.id = ?",
            (meeting_id,),
        ).fetchone()
        if meeting is None:
            raise ValueError(f"meeting {meeting_id} 를 찾을 수 없습니다.")
        analysis = cur.execute(
            "SELECT data_json FROM analyses WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()
    if analysis is None:
        raise ValueError("이 상담의 AI 분석 결과가 없습니다. 먼저 AI 분석을 실행해 주세요.")
    try:
        data = json.loads(analysis["data_json"])
    except Exception as e:
        raise ValueError(f"분석 데이터 파싱 실패: {e}")

    # 분석에서 견적용 핵심 정보 추출
    site_info = data.get("site_info") or {}
    client_info = data.get("client_info") or {}
    client_requests = data.get("client_requests") or []
    must_have = data.get("must_have") or []
    material_finishes = data.get("material_finishes") or []
    summary = data.get("summary") or ""

    # 프롬프트
    context_lines = [
        f"고객: {meeting['client_name']}",
        f"평수: {site_info.get('size_pyeong') or '정보 없음 (32평 가정)'}",
        f"전용면적: {site_info.get('size_m2') or ''}",
        f"확장 여부: {site_info.get('expansion') or ''}",
        f"구조: {site_info.get('structure_type') or ''}",
        f"예산 범위: {client_info.get('budget_range') or ''}",
        f"선호 스타일: {client_info.get('preferred_style') or ''}",
    ]

    prompt = (
        f"### 상담 컨텍스트\n{chr(10).join(context_lines)}\n\n"
        f"### 상담 요약\n{summary}\n\n"
        f"### 고객 요청\n{chr(10).join('- ' + r for r in client_requests[:10])}\n\n"
        f"### 필수 항목\n{chr(10).join('- ' + r for r in must_have[:5])}\n\n"
        f"### 합의된 자재·마감\n{chr(10).join('- ' + r for r in material_finishes[:10])}\n\n"
        f"### 출력 스키마\n```json\n{SCHEMA_TEXT}\n```\n\n"
        "### 출력 규칙\n"
        "- 위 스키마 그대로 JSON 객체 하나만 출력\n"
        "- items 는 최소 8개, 최대 15개 (전체 인테리어 카테고리 커버)\n"
        "- 모든 금액은 합리적인 시장 단가 기반 (32평 일반 리모델링 3500~5000만원 범위)\n"
        "- 한국어 JSON 만. 중국어·영어 금지\n\n"
        "[REMINDER] 한국어 JSON only."
    )

    model = settings_service.get_ollama_model()
    log.info(f"quote_draft meeting={meeting_id} model={model} user={username}")
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
        draft = json.loads(raw)
    except Exception as e:
        log.warning(f"견적 초안 JSON 파싱 실패: {e}")
        return {
            "ok": False,
            "error": "AI 응답이 JSON 형식이 아니었습니다.",
            "raw_response": raw[:5000],
        }

    return {
        "ok": True,
        "meeting_id": meeting_id,
        "client_name": meeting["client_name"],
        "model_used": model,
        "draft": draft,
        "used_endpoint": resp.get("_used_endpoint", "local"),
    }
