"""
AI 분석 API (Phase 4).
v3.5.0 추가: 재분석(⑥), 발화통계(⑦), 고객 성향 프로파일(⑧), 이메일 초안(⑬)

- POST /api/meetings/{id}/analyze        : qwen 으로 분석 실행 (덮어쓰기)
- POST /api/meetings/{id}/reanalyze      : 기존 분석 삭제 후 재분석 ⑥
- GET  /api/meetings/{id}/analysis       : 저장된 분석 결과 조회
- GET  /api/meetings/{id}/speech-stats   : 발화 통계 ⑦
- POST /api/clients/{id}/personality     : 고객 성향 프로파일 생성 ⑧
- POST /api/meetings/{id}/email-draft    : 이메일 초안 생성 ⑬
- GET  /api/ollama/health                : Ollama + 모델 가용성 확인
"""
from __future__ import annotations

import json
import re
import traceback
from collections import Counter
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import config
from app.db import db_cursor
from app.services import analysis_service, ollama_client, settings_service

router = APIRouter(tags=["analysis"])


def _describe_exc(prefix: str, e: Exception) -> str:
    print(f"\n[{prefix}] {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
    return f"{type(e).__name__}: {str(e)[:400]}"


def _username(request: Request) -> str | None:
    """request.state.user 에서 username (sub) 추출. 없으면 None."""
    user = getattr(request.state, "user", None)
    return user.get("sub") if user else None


# ========================================
# Health
# ========================================
@router.get("/api/ollama/health")
def ollama_health(request: Request):
    # v3.5.2: 사용자별 원격 URL 우선
    client = ollama_client.get_client_for_user(_username(request))
    local_url = ollama_client.get_client().base_url
    is_remote = (client.base_url != local_url)
    configured = settings_service.get_ollama_model()
    try:
        models = client.list_models()
    except ollama_client.OllamaError as e:
        return {
            "ok": False,
            "base_url": client.base_url,
            "is_remote": is_remote,
            "configured_model": configured,
            "error": str(e),
        }

    names = [m.get("name") for m in models if m.get("name")]
    return {
        "ok": True,
        "base_url": client.base_url,
        "is_remote": is_remote,
        "configured_model": configured,
        "model_ready": configured in names,
        "installed_models": names,
    }


# ========================================
# v3.0.0 Phase 3: 설치된 Ollama 모델 목록
# ========================================
@router.get("/api/ollama/models")
def list_ollama_models(request: Request):
    # v3.5.2: 사용자별 원격 URL 우선
    client = ollama_client.get_client_for_user(_username(request))
    try:
        models = client.list_models()
    except ollama_client.OllamaError as e:
        return {"ok": False, "models": [], "configured_model": settings_service.get_ollama_model(), "error": str(e)}
    names = [m.get("name") for m in models if m.get("name")]
    return {
        "ok": True,
        "models": names,
        "configured_model": settings_service.get_ollama_model(),
        "base_url": client.base_url,
    }


# ========================================
# Analyze
# ========================================
@router.post("/api/meetings/{meeting_id}/analyze")
def analyze_meeting(meeting_id: int, request: Request):
    # v3.5.2: 사용자별 원격 Ollama 우선
    username = _username(request)
    client = ollama_client.get_client_for_user(username)
    configured_model = settings_service.get_ollama_model()
    try:
        models = client.list_models()
    except ollama_client.OllamaError as e:
        # 원격 실패 시 로컬로 한 번 더 체크
        local = ollama_client.get_client()
        if client.base_url != local.base_url:
            try:
                models = local.list_models()
            except ollama_client.OllamaError as e2:
                raise HTTPException(503, f"Ollama 연결 실패 (원격·로컬 모두) — 원격: {e}, 로컬: {e2}")
        else:
            raise HTTPException(503, f"Ollama 연결 실패 — {e}")
    names = [m.get("name") for m in models if m.get("name")]
    if configured_model not in names:
        raise HTTPException(
            409,
            f"모델 '{configured_model}' 이(가) Ollama 에 없습니다. "
            f"설치된 모델: {names}. 'ollama pull {configured_model}' 로 받아주세요.",
        )

    try:
        result = analysis_service.analyze_meeting(meeting_id, username=username)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ollama_client.OllamaError as e:
        raise HTTPException(502, f"Ollama 호출 실패 — {e}")
    except Exception as e:
        raise HTTPException(500, _describe_exc("analyze_meeting", e))

    return result


# ========================================
# Get existing analysis
# ========================================
@router.get("/api/meetings/{meeting_id}/analysis")
def get_analysis(meeting_id: int):
    existing = analysis_service.get_existing_analysis(meeting_id)
    if existing is None:
        return {"exists": False}
    return {"exists": True, **existing}


# ========================================
# Phase 8B+: AI 분석 결과 사용자 편집
# ========================================
class AnalysisUpdateRequest(BaseModel):
    data: Dict[str, Any]


@router.patch("/api/meetings/{meeting_id}/analysis")
def update_analysis(meeting_id: int, req: AnalysisUpdateRequest):
    """
    AI 분석 결과를 사용자 편집한 새 dict 로 통째 교체.
    DB(data_json) + 요약.md + 분석결과.json 모두 갱신.
    """
    try:
        result = analysis_service.update_analysis_data(meeting_id, req.data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, _describe_exc("update_analysis", e))
    return {"ok": True, **result}


# ========================================
# v3.5.0 ⑥: 재분석 (기존 분석 삭제 후 재실행)
# ========================================
@router.post("/api/meetings/{meeting_id}/reanalyze")
def reanalyze_meeting(meeting_id: int, request: Request):
    """기존 분석 결과를 삭제하고 처음부터 다시 분석."""
    # 기존 analyses 행 삭제
    with db_cursor() as cur:
        cur.execute("DELETE FROM analyses WHERE meeting_id = ?", (meeting_id,))
    # v3.5.2: 사용자별 원격 우선
    username = _username(request)
    client = ollama_client.get_client_for_user(username)
    configured_model = settings_service.get_ollama_model()
    try:
        models = client.list_models()
    except ollama_client.OllamaError as e:
        local = ollama_client.get_client()
        if client.base_url != local.base_url:
            try:
                models = local.list_models()
            except ollama_client.OllamaError as e2:
                raise HTTPException(503, f"Ollama 연결 실패 (원격·로컬 모두) — 원격: {e}, 로컬: {e2}")
        else:
            raise HTTPException(503, f"Ollama 연결 실패 — {e}")
    names = [m.get("name") for m in models if m.get("name")]
    if configured_model not in names:
        raise HTTPException(409, f"모델 '{configured_model}' 이(가) Ollama 에 없습니다.")
    try:
        result = analysis_service.analyze_meeting(meeting_id, username=username)
    except Exception as e:
        raise HTTPException(500, _describe_exc("reanalyze_meeting", e))
    return result


# ========================================
# v3.5.0 ⑦: 발화 통계
# ========================================
@router.get("/api/meetings/{meeting_id}/speech-stats")
def speech_stats(meeting_id: int):
    """전사 세그먼트 기반 발화 통계 분석."""
    with db_cursor() as cur:
        segs = cur.execute(
            "SELECT text, speaker, start_ms, end_ms FROM transcript_segments "
            "WHERE meeting_id = ? ORDER BY start_ms",
            (meeting_id,),
        ).fetchall()

    if not segs:
        return {"total": 0, "by_speaker": {}, "word_freq": [], "avg_duration_sec": 0}

    total = len(segs)
    by_speaker: dict[str, dict] = {}
    all_words: list[str] = []

    for s in segs:
        sp = s["speaker"] or "미분류"
        dur = max(0, (s["end_ms"] or 0) - (s["start_ms"] or 0)) / 1000
        if sp not in by_speaker:
            by_speaker[sp] = {"count": 0, "duration_sec": 0.0, "chars": 0}
        by_speaker[sp]["count"] += 1
        by_speaker[sp]["duration_sec"] += dur
        by_speaker[sp]["chars"] += len(s["text"] or "")
        # 단어 빈도: 한국어는 공백 분리 + 짧은 단어 제외
        words = re.findall(r'[가-힣a-zA-Z]{2,}', s["text"] or "")
        all_words.extend(words)

    total_dur = sum(v["duration_sec"] for v in by_speaker.values())
    # 비율 계산
    for sp in by_speaker:
        cnt = by_speaker[sp]["count"]
        by_speaker[sp]["ratio"] = round(cnt / total * 100, 1) if total else 0
        by_speaker[sp]["duration_sec"] = round(by_speaker[sp]["duration_sec"], 1)

    # 단어 빈도 Top 15 (불용어 제외)
    stopwords = {"이", "그", "저", "것", "수", "더", "이런", "저런", "그런", "어떤",
                 "있는", "있어", "있고", "하는", "하고", "해서", "되는", "되어", "되고",
                 "그래서", "그런데", "그리고", "이렇게", "저렇게", "그렇게", "어떻게"}
    freq = Counter(w for w in all_words if w not in stopwords)
    word_freq = [{"word": w, "count": c} for w, c in freq.most_common(15)]

    return {
        "total": total,
        "total_duration_sec": round(total_dur, 1),
        "avg_duration_sec": round(total_dur / total, 1) if total else 0,
        "by_speaker": by_speaker,
        "word_freq": word_freq,
    }


# ========================================
# v3.5.0 ⑧: 고객 성향 프로파일 생성 (AI)
# ========================================
@router.post("/api/clients/{client_id}/personality")
def generate_personality(client_id: int, request: Request):
    """여러 상담 분석 결과를 종합해 고객 성향 프로파일 생성."""
    with db_cursor() as cur:
        client_row = cur.execute("SELECT name FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not client_row:
            raise HTTPException(404, "고객을 찾을 수 없습니다.")
        # 분석 결과가 있는 상담 목록
        analyses = cur.execute(
            "SELECT a.data_json, m.meeting_type, m.started_at "
            "FROM analyses a JOIN meetings m ON m.id = a.meeting_id "
            "WHERE m.client_id = ? ORDER BY m.started_at",
            (client_id,),
        ).fetchall()

    if not analyses:
        raise HTTPException(400, "분석 결과가 있는 상담이 없습니다. AI 분석을 먼저 실행해 주세요.")

    # 분석 결과 요약 텍스트
    summaries = []
    for a in analyses:
        try:
            d = json.loads(a["data_json"])
            summary = d.get("summary") or d.get("요약") or ""
            concerns = d.get("주요관심사") or d.get("concerns") or []
            if isinstance(concerns, list):
                concerns = ", ".join(str(c) for c in concerns[:3])
            summaries.append(f"[{a['meeting_type']}({a['started_at'][:10]})] 요약: {summary} 관심사: {concerns}")
        except Exception:
            pass

    if not summaries:
        raise HTTPException(400, "분석 데이터를 읽을 수 없습니다.")

    client_name = client_row["name"]
    prompt = (
        f"다음은 인테리어 디자이너와 고객 '{client_name}' 의 여러 상담 분석 요약입니다.\n\n"
        + "\n".join(summaries)
        + "\n\n위 상담들을 종합해서 다음 JSON 형식으로 고객 성향 프로파일을 작성해 주세요:\n"
        '{"가격민감도": "높음|중간|낮음", "결정속도": "빠름|보통|느림", '
        '"선호스타일": "모던|북유럽|클래식|기타", "특이사항": "한두 문장", '
        '"담당자팁": "이 고객 상담 시 주의할 점 한두 문장"}'
    )

    # v3.5.2: 원격 Ollama 우선 + 자동 폴백
    model = settings_service.get_ollama_model()
    try:
        response = ollama_client.generate_with_fallback(
            _username(request),
            model=model, prompt=prompt, format_json=True,
        )
        profile = json.loads(response.get("response", "{}"))
    except Exception as e:
        raise HTTPException(502, f"AI 호출 실패: {type(e).__name__}: {str(e)[:200]}")

    # DB 저장 (clients.custom_fields 에 personality 키로 저장)
    with db_cursor() as cur:
        existing = cur.execute(
            "SELECT custom_fields FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        cf = {}
        try:
            cf = json.loads(existing["custom_fields"] or "{}")
        except Exception:
            pass
        cf["personality"] = profile
        cur.execute(
            "UPDATE clients SET custom_fields = ? WHERE id = ?",
            (json.dumps(cf, ensure_ascii=False), client_id),
        )

    return {"ok": True, "profile": profile}


# ========================================
# v3.5.0 ⑬: 이메일 초안 생성 (AI)
# ========================================
class EmailDraftRequest(BaseModel):
    tone: str = "formal"  # "formal" | "friendly"


@router.post("/api/meetings/{meeting_id}/email-draft")
def generate_email_draft(meeting_id: int, req: EmailDraftRequest, request: Request):
    """상담 분석 결과를 바탕으로 고객에게 보낼 이메일 초안 생성."""
    with db_cursor() as cur:
        meeting = cur.execute(
            "SELECT m.*, c.name as client_name FROM meetings m "
            "JOIN clients c ON c.id = m.client_id WHERE m.id = ?",
            (meeting_id,),
        ).fetchone()
        if not meeting:
            raise HTTPException(404, "상담을 찾을 수 없습니다.")
        analysis = cur.execute(
            "SELECT data_json FROM analyses WHERE meeting_id = ?", (meeting_id,)
        ).fetchone()

    if not analysis:
        raise HTTPException(400, "AI 분석 결과가 없습니다. 먼저 AI 분석을 실행해 주세요.")

    try:
        data = json.loads(analysis["data_json"])
    except Exception:
        raise HTTPException(400, "분석 데이터를 읽을 수 없습니다.")

    summary = data.get("summary") or data.get("요약") or ""
    action_items = data.get("action_items") or data.get("액션아이템") or []
    if isinstance(action_items, list):
        action_items = "\n".join(f"- {a}" for a in action_items[:5])

    tone_desc = "공식적이고 정중한 비즈니스 이메일" if req.tone == "formal" else "친근하고 따뜻한 카카오 채널 스타일"
    # v3.5.2: 로그인 사용자별 담당자 정보
    ds = settings_service.get_designer_info(username=_username(request))
    designer = ds.get("name", "담당자")
    store = ds.get("store", "")

    prompt = (
        f"다음 인테리어 상담 요약을 바탕으로 {tone_desc} 형식으로 고객에게 보낼 이메일 초안을 작성해주세요.\n\n"
        f"고객명: {meeting['client_name']}\n"
        f"상담 종류: {meeting['meeting_type']}\n"
        f"상담 요약: {summary}\n"
        f"주요 액션 아이템:\n{action_items}\n"
        f"담당 디자이너: {designer} ({store})\n\n"
        "이메일 제목과 본문을 작성해주세요. 제목은 '[제목]' 형태로 시작하고, 본문은 바로 이어서 작성하세요."
    )

    # v3.5.2: 원격 Ollama 우선 + 자동 폴백
    model = settings_service.get_ollama_model()
    try:
        response = ollama_client.generate_with_fallback(
            _username(request),
            model=model, prompt=prompt,
        )
        draft = response.get("response", "").strip()
    except Exception as e:
        raise HTTPException(502, f"AI 호출 실패: {type(e).__name__}: {str(e)[:200]}")

    # 제목 / 본문 분리
    lines = draft.split("\n", 1)
    subject_line = lines[0].strip().lstrip("[").rstrip("]")
    body = lines[1].strip() if len(lines) > 1 else draft

    return {"ok": True, "subject": subject_line, "body": body, "full": draft}
