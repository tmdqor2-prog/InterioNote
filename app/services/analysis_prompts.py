"""
상담 종류별 AI 분석 프롬프트 (Phase 4).

모든 프롬프트는 qwen2.5:3b 기준:
- 한국어 지시
- format: 'json' 을 함께 사용하므로 JSON 출력 필수 명시
- 과장/추론 금지. 원문에 없는 내용 생성 금지.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


SYSTEM_PROMPT = (
    "당신은 대한민국의 숙련된 인테리어 디자이너 한 명을 도와 상담 녹취록을 정리하는 "
    "비서입니다. 규칙을 엄격히 지킵니다.\n"
    "1) 출력은 반드시 지정된 JSON 스키마를 따릅니다. 추가 키/설명/마크다운을 넣지 않습니다.\n"
    "2) 원문 녹취록에 등장하지 않은 정보는 절대 만들어내지 않습니다.\n"
    "3) 애매하거나 언급이 없는 항목은 빈 배열 [] 또는 빈 문자열 \"\" 로 둡니다.\n"
    "4) 모든 값은 한국어로 작성합니다.\n"
    "5) 인테리어 업계 용어(샷시, 몰딩, 걸레받이, 강마루, 도배, 중도금, 실측 등)를 "
    "정확히 그대로 유지합니다."
)


# ========================================
# 스키마 (상담 종류별)
# ========================================
SCHEMAS: Dict[str, Dict[str, Any]] = {
    "초도상담": {
        "summary": "전체 상담을 3~5문장으로 요약",
        "client_info": {
            "household": "가족 구성 / 거주 인원 (언급 없으면 빈 문자열)",
            "move_in_timeline": "입주 또는 공사 희망 시기",
            "budget_range": "예산 범위 (원문 그대로)",
            "preferred_style": "선호 스타일",
        },
        # v2.5.1 H2: 인테리어 장소 정보 — 폴더명 자동 수정 제안에도 사용됨
        "site_info": {
            "address": "지역·구·동 등 주소 정보 (예: '자양동' '서초구 동산로')",
            "complex_name": "아파트·빌라·단지 이름 (예: '우성아파트' '래미안')",
            "building_unit": "동·호수 (예: '108동 1502호')",
            "size_pyeong": "평형 (숫자 + '평' — 예: '32평')",
            "size_m2": "전용면적 m2 (숫자 + 'm2' 또는 'm²')",
            "expansion": "확장 여부 (확장형/비확장 등 원문 표현)",
            "structure_type": "구조 (예: '판상형 32A타입')",
        },
        "client_requests": ["고객이 명시적으로 요청한 항목들 (리스트)"],
        "concerns": ["고객이 걱정하거나 꺼린 사항들"],
        "action_items": ["디자이너가 다음까지 해야 할 일"],
        "next_meeting_prep": ["다음 미팅(보통 디자인미팅) 전에 준비·제안해야 할 것"],
    },
    "디자인미팅": {
        "summary": "전체 상담을 3~5문장으로 요약",
        "design_directions": ["이번 미팅에서 확정 또는 제안된 디자인 방향"],
        "agreed_items": ["고객이 동의·확정한 항목"],
        "pending_decisions": ["아직 결정되지 않아 다음 미팅으로 넘어간 항목"],
        "change_requests": ["고객이 변경·수정을 요청한 항목"],
        "material_finishes": ["합의된 자재·마감재 (예: 강마루 고급형, 도장 무광 등)"],
        "action_items": ["디자이너가 다음 미팅 전에 준비할 일"],
    },
    "견적미팅": {
        "summary": "전체 상담을 3~5문장으로 요약",
        "agreed_price": "합의된 총 금액 (원문 그대로, 없으면 빈 문자열)",
        "payment_schedule": ["계약금/중도금/잔금 등 대금 지급 일정"],
        "price_points": ["가격 협의 포인트 (할인, 옵션 변경 등)"],
        "included_scope": ["견적에 포함되는 공사 범위"],
        "excluded_scope": ["견적에서 제외되는 항목"],
        "concerns": ["고객이 가격·범위·일정에 대해 우려한 부분"],
        "action_items": ["계약 전 디자이너가 확인·준비할 일"],
    },
}


def _render_schema_as_example(schema: Dict[str, Any]) -> str:
    """스키마 dict 를 '키 → 설명' 형태 JSON 텍스트로 렌더."""
    import json as _json

    return _json.dumps(schema, ensure_ascii=False, indent=2)


def build_prompt(
    meeting_type: str,
    transcript_text: str,
    *,
    client_name: Optional[str] = None,
    client_descriptor: Optional[str] = None,
    extra_items: Optional[List[dict]] = None,
) -> str:
    """
    analyze 용 프롬프트 본문. Ollama generate() 의 `prompt` 인자로 전달.
    extra_items: [{"key": str, "label": str, "type": "list"|"text"}, ...]
    """
    if meeting_type not in SCHEMAS:
        raise ValueError(f"unknown meeting_type: {meeting_type}")
    # 기본 스키마 복사 후 추가 항목 병합
    schema: Dict[str, Any] = dict(SCHEMAS[meeting_type])
    if extra_items:
        for item in extra_items:
            key = str(item.get("key", "")).strip()
            label = str(item.get("label", "")).strip()
            type_ = str(item.get("type", "list")).strip()
            if key and label and key not in schema:
                # 타입에 따라 예시 값 형태를 다르게 (LLM 이 타입 추론하도록)
                schema[key] = [f"{label} (리스트 형태로)"] if type_ == "list" else f"{label}"
    schema_text = _render_schema_as_example(schema)

    context_lines: List[str] = []
    context_lines.append(f"상담 종류: {meeting_type}")
    if client_name:
        if client_descriptor:
            context_lines.append(f"고객: {client_name} ({client_descriptor})")
        else:
            context_lines.append(f"고객: {client_name}")
    context_block = "\n".join(context_lines)

    return (
        f"다음은 인테리어 {meeting_type} 상담의 녹취록입니다. "
        "이 녹취록을 읽고, 아래에 제시된 JSON 스키마의 모든 키를 채워 응답하세요.\n\n"
        f"### 상담 컨텍스트\n{context_block}\n\n"
        f"### 출력 스키마 (키와 의미 설명)\n```json\n{schema_text}\n```\n\n"
        "### 출력 규칙\n"
        "- 반드시 위 스키마의 모든 최상위 키를 포함한 JSON 객체 하나만 출력.\n"
        "- 값이 리스트인 키는 문자열 리스트 (객체가 아닌 순수 문자열 항목).\n"
        "- 언급이 없는 키는 빈 문자열 \"\" 또는 빈 리스트 [].\n"
        "- JSON 이외의 텍스트(서두, 설명, 마크다운 코드펜스)는 일체 포함하지 말 것.\n\n"
        f"### 녹취록\n{transcript_text}\n"
    )


def truncate_transcript_if_needed(text: str, max_chars: int) -> str:
    """
    전사가 너무 길면 중간을 잘라내고 '[...중략...]' 표시.
    시작/종료 구간은 보존 (요약 품질을 위해).
    """
    if len(text) <= max_chars:
        return text
    head_keep = int(max_chars * 0.6)
    tail_keep = max_chars - head_keep - 30  # for [...중략...] 마커
    if tail_keep < 500:
        tail_keep = 500
        head_keep = max_chars - tail_keep - 30
    return (
        text[:head_keep].rstrip()
        + "\n\n[...분량 제한으로 중간 구간 생략...]\n\n"
        + text[-tail_keep:].lstrip()
    )
