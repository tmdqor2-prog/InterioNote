"""
상담 분석 오케스트레이터 (Phase 4).

흐름:
1. meeting + client + transcript_segments 로드
2. 프롬프트 빌드
3. Ollama 호출 (format=json)
4. JSON 파싱 (+ fallback)
5. analyses 테이블 저장 + 상담 폴더에 '분석결과.json' / '요약.md' 작성
"""
from __future__ import annotations

import json
import logging
import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app import config
from app.db import db_cursor
from app.services import analysis_prompts, meeting_finalizer, ollama_client, settings_service

log = logging.getLogger("analysis")


# ========================================
# 전사 조립
# ========================================
def _speaker_label(speaker: Optional[str]) -> str:
    if speaker == "me":
        return "디자이너"
    if speaker == "client":
        return "고객"
    return "미지정"


def _format_timestamp(ms: int) -> str:
    total = max(0, int(ms // 1000))
    m = total // 60
    s = total % 60
    return f"{m:02d}:{s:02d}"


def assemble_transcript_for_prompt(segments: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for s in segments:
        ts = _format_timestamp(int(s.get("start_ms", 0)))
        sp = _speaker_label(s.get("speaker"))
        text = (s.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[{ts}] {sp}: {text}")
    return "\n".join(lines)


# ========================================
# JSON 파싱 (방어적)
# ========================================
def _extract_json(raw: str) -> Optional[Dict[str, Any]]:
    """
    Ollama format=json 응답은 보통 그대로 JSON. 안전을 위해 실패하면 중괄호 블록 추출 재시도.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    # 가장 바깥 중괄호 블록을 greedy 로 찾아 파싱 재시도
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


# ========================================
# 요약 MD 렌더링
# ========================================
def _md_section(title: str, content: Any) -> List[str]:
    lines: List[str] = [f"### {title}"]
    if isinstance(content, list):
        if not content:
            lines.append("_(해당 없음)_")
        else:
            for item in content:
                if isinstance(item, (dict, list)):
                    lines.append(f"- `{json.dumps(item, ensure_ascii=False)}`")
                else:
                    text = str(item).strip()
                    if text:
                        lines.append(f"- {text}")
    elif isinstance(content, dict):
        if not content:
            lines.append("_(해당 없음)_")
        else:
            for k, v in content.items():
                if isinstance(v, (list, dict)):
                    lines.append(f"- **{k}:** `{json.dumps(v, ensure_ascii=False)}`")
                else:
                    text = str(v or "").strip()
                    lines.append(f"- **{k}:** {text if text else '_(해당 없음)_'}")
    else:
        text = str(content or "").strip()
        lines.append(text if text else "_(해당 없음)_")
    lines.append("")
    return lines


SECTION_TITLES: Dict[str, str] = {
    "summary": "📝 요약",
    "client_info": "👤 고객 정보",
    "site_info": "🏠 인테리어 장소 정보",
    "client_requests": "🙋 고객 요청사항",
    "concerns": "⚠ 고객 우려사항",
    "action_items": "✅ 디자이너 액션 아이템",
    "next_meeting_prep": "📅 다음 미팅 준비",
    "design_directions": "🎨 디자인 방향",
    "agreed_items": "👍 합의 항목",
    "pending_decisions": "⏳ 미결정 항목",
    "change_requests": "🔁 변경 요청",
    "material_finishes": "🧱 자재·마감",
    "agreed_price": "💰 합의 금액",
    "payment_schedule": "🗓 대금 지급 일정",
    "price_points": "💬 가격 협의 포인트",
    "included_scope": "📦 포함 범위",
    "excluded_scope": "🚫 제외 범위",
}


def render_summary_md(
    meeting_type: str,
    client_display: str,
    meeting_date: str,
    data: Dict[str, Any],
    *,
    model_used: str,
) -> str:
    lines: List[str] = []
    lines.append(f"# {meeting_type} 분석 — {client_display}")
    lines.append("")
    lines.append(f"- 일시: {meeting_date}")
    lines.append(f"- 모델: `{model_used}`")
    lines.append(f"- 분석 시각: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # summary 먼저
    if "summary" in data:
        lines += _md_section(SECTION_TITLES["summary"], data.get("summary"))

    # 나머지 키는 스키마 순서대로 (정의된 순서를 존중)
    schema = analysis_prompts.SCHEMAS.get(meeting_type, {})
    for key in schema.keys():
        if key == "summary":
            continue
        title = SECTION_TITLES.get(key, key)
        lines += _md_section(title, data.get(key))

    # 스키마 외 키가 있으면 뒤에 붙임
    extras = [k for k in data.keys() if k != "summary" and k not in schema]
    for key in extras:
        title = SECTION_TITLES.get(key, key)
        lines += _md_section(title, data.get(key))

    return "\n".join(lines)


# ========================================
# 메인 엔트리
# ========================================
def analyze_meeting(meeting_id: int, username: Optional[str] = None) -> Dict[str, Any]:
    """
    meeting_id 의 녹취록을 qwen 으로 분석.
    v3.5.2: username 이 주어지면 그 사용자의 원격 Ollama URL 우선 사용 (실패 시 로컬 폴백).
    성공 시: {data, model_used, md_path, json_path, ...}
    실패 시: OllamaError 등 예외 전파.
    """
    # 1) meeting + client 로드
    with db_cursor() as cur:
        row = cur.execute(
            """
            SELECT m.*,
                   c.name AS client_name, c.descriptor AS client_descriptor,
                   c.folder_name AS folder_name, c.folder_path AS folder_path
            FROM meetings m
            JOIN clients c ON c.id = m.client_id
            WHERE m.id = ?
            """,
            (meeting_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"meeting {meeting_id} not found")
    meeting = {k: row[k] for k in row.keys()}

    if meeting["status"] not in ("recorded", "analyzing", "done"):
        raise ValueError(
            f"분석 가능한 상담이 아닙니다 (status={meeting['status']}). "
            "녹음이 완료된 뒤 시도해 주세요."
        )

    meeting_folder_str = meeting.get("meeting_folder")
    if not meeting_folder_str:
        raise ValueError("상담 폴더가 지정되지 않은 상담입니다. (Phase 3C 마감 필요)")
    meeting_folder = Path(meeting_folder_str)
    if not meeting_folder.exists():
        raise FileNotFoundError(f"상담 폴더를 찾을 수 없습니다: {meeting_folder}")

    # 2) 세그먼트 로드 (DB 기준, 화자 라벨 반영)
    segments = meeting_finalizer.load_segments_from_db(meeting_id)
    transcript = assemble_transcript_for_prompt(segments)
    if not transcript.strip():
        raise ValueError("전사 내용이 비어 있어 분석할 수 없습니다.")

    transcript = analysis_prompts.truncate_transcript_if_needed(
        transcript, config.OLLAMA_MAX_TRANSCRIPT_CHARS
    )

    # 3) 프롬프트 빌드 (v3.0.0 Phase 3: 추가 분석 항목 주입)
    extra_items = settings_service.get_analysis_extra_items(meeting["meeting_type"])
    prompt = analysis_prompts.build_prompt(
        meeting_type=meeting["meeting_type"],
        transcript_text=transcript,
        client_name=meeting.get("client_name"),
        client_descriptor=meeting.get("client_descriptor"),
        extra_items=extra_items if extra_items else None,
    )

    # 4) 상태 표시
    _mark_status(meeting_id, "analyzing")

    # 5) Ollama 호출 (v3.0.0 Phase 3: settings 에서 모델 결정)
    # v3.5.2: 사용자별 원격 URL 우선 + 자동 폴백 (generate_with_fallback)
    model = settings_service.get_ollama_model()

    log.info(f"analyze meeting={meeting_id} model={model} chars={len(transcript)} user={username}")
    try:
        resp = ollama_client.generate_with_fallback(
            username,
            model=model,
            prompt=prompt,
            system=analysis_prompts.SYSTEM_PROMPT,
            format_json=True,
            options={
                "temperature": 0.2,
                "top_p": 0.9,
                "num_ctx": 8192,
                "num_predict": 2048,
            },
        )
    except Exception as e:
        _mark_status(meeting_id, "recorded")  # 롤백
        raise

    raw_text = resp.get("response") or ""
    eval_count = resp.get("eval_count")
    total_duration_ns = resp.get("total_duration")

    # 6) 파싱
    data = _extract_json(raw_text)
    parse_ok = data is not None
    if not parse_ok:
        log.warning(f"analyze meeting={meeting_id}: JSON parse failed — storing raw")
        data = {
            "_parse_failed": True,
            "raw_response": raw_text[:20000],  # 용량 보호
            "summary": "(AI 응답이 JSON 형식이 아니었습니다. 아래 원문을 확인하세요.)",
        }

    # 7) 파일 저장
    json_path = meeting_folder / "분석결과.json"
    md_path = meeting_folder / "요약.md"
    try:
        payload_for_file = {
            "meeting_id": meeting_id,
            "meeting_type": meeting["meeting_type"],
            "client": {
                "name": meeting.get("client_name"),
                "descriptor": meeting.get("client_descriptor"),
                "folder_name": meeting.get("folder_name"),
            },
            "model": model,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_segments": len(segments),
            "transcript_chars": len(transcript),
            "eval_count": eval_count,
            "total_duration_ns": total_duration_ns,
            "data": data,
        }
        json_path.write_text(
            json.dumps(payload_for_file, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        log.error(f"분석결과.json 저장 실패: {type(e).__name__}: {e}")

    try:
        client_display = meeting.get("client_name") or meeting.get("folder_name") or ""
        if meeting.get("client_descriptor"):
            client_display += f" ({meeting['client_descriptor']})"
        meeting_date = (meeting.get("started_at") or "").replace("T", " ")
        md_text = render_summary_md(
            meeting_type=meeting["meeting_type"],
            client_display=client_display,
            meeting_date=meeting_date,
            data=data,
            model_used=model,
        )
        md_path.write_text(md_text, encoding="utf-8")
    except Exception as e:
        log.error(f"요약.md 저장 실패: {type(e).__name__}: {e}\n{traceback.format_exc()}")

    # 8) DB 저장 (analyses upsert)
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO analyses (meeting_id, data_json, model_used)
                VALUES (?, ?, ?)
                ON CONFLICT(meeting_id) DO UPDATE SET
                    data_json = excluded.data_json,
                    model_used = excluded.model_used,
                    created_at = CURRENT_TIMESTAMP
                """,
                (meeting_id, json.dumps(data, ensure_ascii=False), model),
            )
    except Exception as e:
        log.error(f"analyses 저장 실패: {type(e).__name__}: {e}")

    _mark_status(meeting_id, "done")

    return {
        "meeting_id": meeting_id,
        "model": model,
        "parse_ok": parse_ok,
        "data": data,
        "json_path": str(json_path),
        "md_path": str(md_path),
        "eval_count": eval_count,
        "total_duration_sec": (total_duration_ns or 0) / 1_000_000_000.0,
        "source_segments": len(segments),
        "transcript_chars": len(transcript),
    }


def update_analysis_data(meeting_id: int, new_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phase 8B+: AI 분석 결과를 사용자가 수기 편집한 후 저장.
    DB(data_json) 갱신 + 요약.md / 분석결과.json 재생성.
    파일 재생성이 실패해도 DB 갱신은 성공으로 본다.
    """
    if not isinstance(new_data, dict):
        raise ValueError("data 는 dict 여야 합니다.")

    # meeting + 기존 모델명 조회 (요약.md 재생성에 필요)
    meeting = meeting_finalizer._load_meeting_and_client(meeting_id)
    if meeting is None:
        raise ValueError(f"meeting {meeting_id} not found")

    with db_cursor() as cur:
        row = cur.execute(
            "SELECT model_used FROM analyses WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"meeting {meeting_id} 의 분석 결과가 없습니다 (먼저 분석을 실행하세요).")
        model_used = row["model_used"] or settings_service.get_ollama_model()

    # DB 업데이트
    with db_cursor() as cur:
        cur.execute(
            "UPDATE analyses SET data_json = ?, created_at = CURRENT_TIMESTAMP "
            "WHERE meeting_id = ?",
            (json.dumps(new_data, ensure_ascii=False), meeting_id),
        )

    md_warning = None
    json_warning = None
    md_path = None
    json_path = None

    if meeting.get("meeting_folder"):
        folder = Path(meeting["meeting_folder"])
        md_path = folder / "요약.md"
        json_path = folder / "분석결과.json"

        # 요약.md 재생성
        try:
            client_display = meeting.get("client_name") or meeting.get("folder_name") or ""
            if meeting.get("client_descriptor"):
                client_display += f" ({meeting['client_descriptor']})"
            meeting_date = (meeting.get("started_at") or "").replace("T", " ")
            md_text = render_summary_md(
                meeting_type=meeting["meeting_type"],
                client_display=client_display,
                meeting_date=meeting_date,
                data=new_data,
                model_used=model_used,
            )
            md_path.write_text(md_text, encoding="utf-8")
        except Exception as e:
            md_warning = f"{type(e).__name__}: {e}"
            log.warning(f"요약.md 재생성 실패: {md_warning}")

        # 분석결과.json 의 data 필드 갱신 (다른 메타는 보존)
        try:
            existing_payload = {}
            if json_path.exists():
                try:
                    existing_payload = json.loads(json_path.read_text(encoding="utf-8"))
                except Exception:
                    existing_payload = {}
            existing_payload["data"] = new_data
            existing_payload["edited_at"] = datetime.now().isoformat(timespec="seconds")
            json_path.write_text(
                json.dumps(existing_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            json_warning = f"{type(e).__name__}: {e}"
            log.warning(f"분석결과.json 갱신 실패: {json_warning}")

    return {
        "meeting_id": meeting_id,
        "data": new_data,
        "model_used": model_used,
        "md_path": str(md_path) if md_path else None,
        "json_path": str(json_path) if json_path else None,
        "md_warning": md_warning,
        "json_warning": json_warning,
    }


def get_existing_analysis(meeting_id: int) -> Optional[Dict[str, Any]]:
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT id, data_json, model_used, created_at FROM analyses WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row["data_json"])
    except Exception:
        data = None
    return {
        "id": row["id"],
        "data": data,
        "model_used": row["model_used"],
        "created_at": row["created_at"],
    }


def _mark_status(meeting_id: int, status: str) -> None:
    try:
        with db_cursor() as cur:
            cur.execute(
                "UPDATE meetings SET status = ? WHERE id = ?",
                (status, meeting_id),
            )
    except Exception:
        pass
