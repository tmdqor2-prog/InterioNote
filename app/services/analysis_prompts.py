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
    # v3.5.4: qwen2.5 같은 중국 모델이 system 약하면 중국어로 빠지는 문제 방지.
    # 영어 + 한국어 양방향 + 명시적 금지 언어 표시 + 마지막에 다시 한 번 강조.
    "[CRITICAL OUTPUT LANGUAGE RULE]\n"
    "You MUST respond entirely in KOREAN (한국어, ko-KR) ONLY.\n"
    "DO NOT use Chinese (zh), Japanese (ja), or English in any output value.\n"
    "절대로 중국어 한자나 일본어, 영어로 응답하지 마세요. 모든 출력 값은 100% 한국어로 작성.\n\n"
    "당신은 대한민국의 숙련된 인테리어 디자이너 한 명을 도와 상담 녹취록을 정리하는 "
    "한국어 전문 비서입니다. 규칙을 엄격히 지킵니다.\n"
    "1) 출력은 반드시 지정된 JSON 스키마를 따릅니다. 추가 키/설명/마크다운을 넣지 않습니다.\n"
    "2) 원문 녹취록에 등장하지 않은 정보는 절대 만들어내지 않습니다.\n"
    "3) 애매하거나 언급이 없는 항목은 빈 배열 [] 또는 빈 문자열 \"\" 로 둡니다.\n"
    "4) 모든 값은 한국어로만 작성합니다 (중국어 한자·영문 단독 단어 금지).\n"
    "5) 인테리어 업계 용어(샷시, 몰딩, 걸레받이, 강마루, 도배, 중도금, 실측 등)를 "
    "정확히 그대로 유지합니다.\n\n"
    "[FINAL REMINDER] Output language: Korean only. 출력 언어: 한국어 전용."
)


def has_significant_chinese(text: str) -> bool:
    """v3.5.4: 응답이 비정상적으로 중국어로 나왔는지 감지.
    한국어 분석 결과에 중국어 한자가 한국어 글자 수의 20% 이상이면 의심.
    (한국어 인명·전문용어로 한자 1~2개 들어갈 수는 있음)
    """
    if not text:
        return False
    chinese = sum(1 for c in text if '一' <= c <= '鿿')
    korean = sum(1 for c in text if '가' <= c <= '힯')
    if korean == 0 and chinese > 10:
        return True
    if korean > 0 and chinese > korean * 0.2:
        return True
    return False


# ========================================
# 스키마 (상담 종류별)
# ========================================
SCHEMAS: Dict[str, Dict[str, Any]] = {
    "초도상담": {
        "summary": "전체 상담을 5~8문장으로 자세히 요약 (배경·요청·우려·다음 단계 모두 포함)",
        "client_info": {
            "household": "가족 구성 / 거주 인원 (예: '부부+자녀 2명, 시부모 동거')",
            "move_in_timeline": "입주 또는 공사 희망 시기 (구체 일자·계절)",
            "budget_range": "예산 범위 (원문 그대로, 평당 단가 포함)",
            "preferred_style": "선호 스타일 (모던·북유럽·클래식·러블리·미드센추리 등)",
            "lifestyle": "생활 패턴 (재택근무·요리 빈도·홈파티·반려동물·자녀 학습 공간 등)",
            "decision_makers": "의사결정자 (남편/아내/부모/자녀 중 누가 주도)",
            "current_pain_points": "지금 집의 불편한 점 (수납 부족·동선 꼬임·습기·채광 등)",
            "inspiration_sources": "영감 출처 (인스타·잡지·지인 집·모델하우스 등)",
        },
        # v2.5.1 H2: 인테리어 장소 정보 — 폴더명 자동 수정 제안에도 사용됨
        "site_info": {
            "address": "지역·구·동 등 주소 (예: '자양동' '서초구 동산로')",
            "complex_name": "아파트·빌라·단지 이름 (예: '우성아파트' '래미안')",
            "building_unit": "동·호수 (예: '108동 1502호')",
            "size_pyeong": "평형 (숫자 + '평')",
            "size_m2": "전용면적 m2",
            "expansion": "확장 여부 (확장형/비확장)",
            "structure_type": "구조 (예: '판상형 32A타입')",
            "floor_count": "층수·로얄층 여부",
            "current_state": "현재 상태 (신축·구축·반전세·셀프인테리어 후 등)",
        },
        "client_requests":   ["고객이 명시적으로 요청한 항목 (구체 위치·자재·기능)"],
        "must_have":         ["⭐ 절대 빠지면 안 되는 핵심 요구사항 (deal-breaker)"],
        "nice_to_have":      ["있으면 좋은 항목 (예산 여유 시 검토)"],
        "taboo_items":       ["절대 안 되는 것 (예: 어두운 색 / 특정 자재 알레르기)"],
        "concerns":          ["고객이 걱정한 사항 (가격·일정·하자·소음·환기 등)"],
        "competitor_context":["다른 업체 견적·비교 언급 / 경쟁 상황"],
        "urgency_factors":   ["시급함 요소 (이사일·전세 만료·자녀 학기·결혼식 등)"],
        "key_quotes":        ["💬 고객의 인상 깊은 말·핵심 요구를 그대로 인용 (1~3개)"],
        "action_items":      ["디자이너가 다음까지 해야 할 일 (구체 액션)"],
        "next_meeting_prep": ["다음 미팅(보통 디자인미팅) 전 준비·제안 사항"],
        "follow_up_tone":    "이 고객 응대 톤 추천 (예: 데이터 위주 / 감성 어필 / 신속 응답 중요 등)",
    },
    "디자인미팅": {
        "summary": "전체 미팅을 5~8문장으로 자세히 요약",
        "design_directions": ["확정·제안된 디자인 방향 (전체 컨셉 + 공간별)"],
        "agreed_items":      ["✅ 고객이 동의·확정한 항목 (다음 단계로 넘어감)"],
        "pending_decisions": ["⏳ 아직 결정 안 된 항목 (다음 미팅 의제)"],
        "change_requests":   ["🔁 고객이 변경·수정 요청한 항목"],
        "space_plan": {
            "living":  "거실 결정 사항 (소파·TV·아트월·조명 등)",
            "kitchen": "주방 결정 사항 (싱크·아일랜드·후드·타일)",
            "bedroom": "안방·침실 결정 사항",
            "bathroom":"욕실 결정 사항 (타일·세면대·욕조·샤워부스)",
            "other":   "기타 공간 (드레스룸·서재·다용도실 등)",
        },
        "material_finishes": ["합의된 자재·마감재 (브랜드/등급 포함, 예: '동화 강마루 고급형')"],
        "color_palette":     ["합의된 색상 팔레트 (메인·서브·포인트)"],
        "lighting_plan":     ["조명 계획 (간접·매립·펜던트·트랙 등)"],
        "furniture_plan":    ["가구 결정 (붙박이·이동식·기존 활용·새 구매)"],
        "storage_solutions": ["수납 솔루션 (붙박이장·팬트리·시스템 옷장 등)"],
        "concerns":          ["고객 우려 (디자인 호불호·실용성·예산 초과 등)"],
        "key_quotes":        ["💬 고객의 결정적 발언 (1~3개)"],
        "action_items":      ["디자이너가 다음 미팅 전 준비할 일"],
        "estimated_quote_direction": "다음 견적 미팅에서 제시할 가격대 방향",
    },
    "견적미팅": {
        "summary": "전체 미팅을 5~8문장으로 자세히 요약",
        "agreed_price":      "합의된 총 금액 (원문 그대로)",
        "price_breakdown":   ["항목별 견적 내역 (예: '철거 350만원, 도배 280만원')"],
        "discount_negotiations": ["할인·옵션 변경 협상 내역"],
        "payment_schedule":  ["계약금/중도금/잔금 일정 + 금액"],
        "included_scope":    ["✅ 견적에 포함되는 공사 범위"],
        "excluded_scope":    ["🚫 견적에서 제외되는 항목 (별도 비용)"],
        "material_brands":   ["자재 브랜드·등급 (강마루=동화 골드, 도배=LG베스띠 등)"],
        "schedule_phases":   ["공사 단계별 일정 (철거→설비→마감→입주)"],
        "contract_terms":    ["계약 조건 (보증·하자·AS·중도 변경)"],
        "concerns":          ["고객 우려 (가격 부담·하자·일정 지연 등)"],
        "customer_signals":  "고객 의사 시그널 ('긍정적' / '중립' / '부정적' / '추가 비교 필요')",
        "next_action":       "다음 액션 ('계약 진행' / '재상담' / '견적 수정' / '보류')",
        "key_quotes":        ["💬 고객의 결정적 발언 (1~3개)"],
        "action_items":      ["계약 전 디자이너가 확인·준비할 일"],
        "estimated_close_probability": "계약 성사 가능성 ('높음' / '보통' / '낮음') + 한 줄 근거",
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
    existing_analysis: Optional[Dict[str, Any]] = None,
) -> str:
    """
    analyze 용 프롬프트 본문. Ollama generate() 의 `prompt` 인자로 전달.
    extra_items: [{"key": str, "label": str, "type": "list"|"text"}, ...]
    existing_analysis: v3.5.5 — 기존 분석이 있으면 prompt 에 포함해서
                       AI 가 보존·보강 모드로 동작하게 함 (재전사 시 유용).
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

    # v3.5.5: 기존 분석이 있으면 보존·보강 모드 안내 추가
    existing_block = ""
    if existing_analysis and isinstance(existing_analysis, dict):
        # 너무 크면 잘라서 토큰 절약
        import json as _json
        try:
            existing_text = _json.dumps(existing_analysis, ensure_ascii=False, indent=2)
            if len(existing_text) > 6000:
                existing_text = existing_text[:6000] + "\n... (이하 생략)"
            existing_block = (
                "\n### ⚠ 기존 분석 결과 (보존·보강 모드)\n"
                "아래는 이전 분석에서 이미 추출된 내용입니다. "
                "**기존 정보는 그대로 보존**하고, 새 녹취록에서 추가로 발견된 내용만 보강해 주세요.\n"
                "- 이미 채워진 항목 → 그대로 유지하거나 정보가 늘어났으면 보강\n"
                "- 빈 항목 (\"\" 또는 [])  → 새 녹취록에서 발견된 내용으로 채움\n"
                "- 사용자가 직접 수정한 항목으로 보이면 표현·표기를 함부로 바꾸지 않음\n\n"
                f"```json\n{existing_text}\n```\n"
            )
        except Exception:
            pass

    return (
        f"다음은 인테리어 {meeting_type} 상담의 녹취록입니다. "
        "이 녹취록을 읽고, 아래에 제시된 JSON 스키마의 모든 키를 가능한 한 풍부하게 채워 응답하세요.\n\n"
        f"### 상담 컨텍스트\n{context_block}\n\n"
        f"### 출력 스키마 (키와 의미 설명)\n```json\n{schema_text}\n```\n"
        f"{existing_block}\n"
        "### 출력 규칙\n"
        "- 반드시 위 스키마의 모든 최상위 키를 포함한 JSON 객체 하나만 출력.\n"
        "- 값이 리스트인 키는 문자열 리스트 (객체가 아닌 순수 문자열 항목).\n"
        "- 언급이 없는 키는 빈 문자열 \"\" 또는 빈 리스트 [].\n"
        "- JSON 이외의 텍스트(서두, 설명, 마크다운 코드펜스)는 일체 포함하지 말 것.\n"
        "- ⭐ 풍부하게 작성: summary 는 5~8문장, 리스트 항목은 최대한 많이 추출 (3개 이상 권장).\n"
        "- ⭐ key_quotes 항목이 있으면 고객의 인상 깊은 말을 큰따옴표로 그대로 인용.\n"
        # v3.5.4: 출력 언어 마지막 강제 — qwen 등 모델이 중국어로 빠지는 것 방지
        "- ⚠ 모든 텍스트 값은 반드시 한국어 (Korean) 로만 작성. 중국어 한자·영어 금지.\n"
        "- ⚠ Output values MUST be in Korean only. NO Chinese, NO English.\n\n"
        f"### 녹취록\n{transcript_text}\n\n"
        "[REMINDER] 응답은 반드시 한국어 JSON. Respond in Korean JSON only."
    )


# v3.5.5: 기존 + 신규 분석 dict 병합 (보존 우선)
def merge_analysis(existing: Optional[Dict[str, Any]], new: Dict[str, Any]) -> Dict[str, Any]:
    """
    기존 분석에 새 분석을 보강 — 사용자가 편집한 내용 + 정보 손실 방지.

    규칙:
    - existing 가 비어 있으면 → new 그대로
    - 같은 키가 양쪽에 있을 때:
      - 둘 다 문자열: existing 가 비어 있으면 new, 아니면 existing 유지 (사용자 편집 보존)
      - 둘 다 리스트: 합집합 (중복 제거, 순서는 existing → 신규 항목)
      - 둘 다 dict: 재귀 merge
      - 타입 다르면: existing 우선
    """
    if not existing:
        return new or {}
    if not new:
        return existing
    out: Dict[str, Any] = dict(existing)
    for k, v in new.items():
        if k.startswith("_"):  # _parse_failed 등 메타 키
            out[k] = v
            continue
        if k not in out or out[k] is None or out[k] == "" or out[k] == []:
            out[k] = v
            continue
        # 양쪽 다 값이 있을 때
        ev = out[k]
        if isinstance(ev, list) and isinstance(v, list):
            # 합집합 (string 비교)
            seen = set()
            merged: list = []
            for item in list(ev) + list(v):
                key = item if isinstance(item, str) else str(item)
                if key not in seen:
                    seen.add(key)
                    merged.append(item)
            out[k] = merged
        elif isinstance(ev, dict) and isinstance(v, dict):
            out[k] = merge_analysis(ev, v)
        else:
            # 문자열 등: 기존 보존 (사용자 편집 보호)
            # 단 기존이 너무 짧고 새 값이 더 길면 새 값 채택
            if isinstance(ev, str) and isinstance(v, str) and len(v) > len(ev) * 1.5:
                out[k] = v
            # else: keep existing
    return out


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
