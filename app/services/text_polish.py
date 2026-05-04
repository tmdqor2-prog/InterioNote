"""
v2.5.1 — 한국어 전사 텍스트 정리 (간단 룰 기반).
Whisper 출력에 마침표·쉼표 누락이 많아 가독성이 떨어지는 것을 보완.

원칙:
- 절대 의미를 바꾸지 않음 (단어 추가/삭제 없음, 구두점만 추가)
- 짧은 문장은 건드리지 않음
- 이미 종결 부호 (. ? !) 가 있으면 두지 않음
- 안전한 종결어미만 인식 (다, 요, 까)

retranscribe_service 가 새 카드 생성 후 적용. 사용자가 직접 편집한 카드 (edited_at) 는 건드리지 않음.
"""
from __future__ import annotations

import re

# 종결어미 + 그 앞 자모 패턴 — 안전한 매칭
# "...니다" "...해요" "...까요" "...죠" 같은 일반 종결
_SENTENCE_END_RE = re.compile(
    r"("
    r"(?:습니다|입니다|랍니다|봅니다|냅니다|냅니까|입니까|십니까|니까|니다)"
    r"|"
    r"(?:어요|아요|에요|예요|이요|야요|봐요|네요|군요|구요|데요|죠)"
    r"|"
    r"(?:거든요|거든|는데요|는데|던데요|던데|만요|구만|군요|구나)"
    r")(?=[\s가-힣]|$)"
)

# 이미 마침표 뒤 / 띄어쓰기 안 된 곳에 마침표 + 공백
_FIX_NO_SPACE_AFTER_PERIOD = re.compile(r"\.([가-힣A-Za-z0-9])")


def polish_korean(text: str) -> str:
    """
    안전한 구두점 추가:
    - 종결어미 직후에 마침표가 없고 다음에 새 단어가 오면 마침표 + 공백 추가
    - 마침표 뒤에 띄어쓰기 빠진 것 보정
    원본 텍스트가 너무 짧거나 (~10자 이하) 이미 잘 형식화됐으면 변경 없음.
    """
    if not text:
        return text
    s = text.strip()
    if len(s) < 12:
        return text
    if "." in s or "?" in s or "!" in s:
        # 이미 어느 정도 구두점 있는 경우 — 띄어쓰기만 보정
        return _FIX_NO_SPACE_AFTER_PERIOD.sub(r". \1", s)

    # 종결어미 위치마다 마침표 + 공백 삽입
    out = _SENTENCE_END_RE.sub(r"\1.", s)
    # 마침표 뒤 띄어쓰기 보정
    out = _FIX_NO_SPACE_AFTER_PERIOD.sub(r". \1", out)
    # 끝에 마침표 없으면 추가 (단, 짧은 단답은 제외)
    if out and out[-1] not in ".?!":
        out = out + "."
    # 중복 공백 정리
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out


def polish_segments_in_place(segments: list, *, only_unedited: bool = True) -> int:
    """segments 리스트의 text 를 in-place 로 정리. 반환: 변경된 카드 수.
    only_unedited=True: edited_at 가 채워진 카드는 건드리지 않음.
    """
    changed = 0
    for s in segments:
        if not isinstance(s, dict):
            continue
        if only_unedited and s.get("edited_at"):
            continue
        original = s.get("text") or ""
        polished = polish_korean(original)
        if polished != original:
            s["text"] = polished
            changed += 1
    return changed
