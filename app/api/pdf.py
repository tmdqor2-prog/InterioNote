"""
v2.6.0 A — PDF 출력 라우트.

window.print() 방식 — WebView2 의 시스템 인쇄 다이얼로그 호출.
사용자가 "Microsoft Print to PDF" 선택해서 저장. 의존성 0 (markdown 만 사용).

라우트:
- GET /api/meetings/{meeting_id}/print-summary  : AI 분석 요약 인쇄용 HTML
- GET /api/meetings/{meeting_id}/print-transcript : 전체 대화 인쇄용 HTML
"""
from __future__ import annotations

import json
from pathlib import Path

import markdown as md
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import config
from app.db import db_cursor
from app.services import settings_service

router = APIRouter(prefix="/api/meetings", tags=["pdf"])


_PRINT_BASE_CSS = """
<style>
  @page { size: A4; margin: 18mm 16mm; }
  * { box-sizing: border-box; }
  body {
    font-family: 'Malgun Gothic', '맑은 고딕', 'Apple SD Gothic Neo', sans-serif;
    font-size: 10.5pt;
    line-height: 1.55;
    color: #1f2937;
    margin: 0;
    padding: 64px 24px 16px 24px;  /* v2.6.1: top toolbar 공간 */
    background: #fff;
  }
  h1 { font-size: 18pt; margin: 0 0 4px 0; color: #111; border-bottom: 2px solid #2563eb; padding-bottom: 6px; }
  h2 { font-size: 13pt; margin: 18px 0 6px 0; color: #1e3a8a; border-left: 4px solid #2563eb; padding-left: 8px; }
  h3 { font-size: 11pt; margin: 12px 0 4px 0; color: #374151; }
  ul, ol { margin: 4px 0 8px 22px; padding: 0; }
  li { margin-bottom: 2px; }
  table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 9.5pt; }
  th, td { border: 1px solid #d1d5db; padding: 4px 8px; text-align: left; vertical-align: top; }
  th { background: #f3f4f6; font-weight: 600; }
  .meta { color: #6b7280; font-size: 9.5pt; margin-top: 2px; }
  .badge { display: inline-block; padding: 1px 8px; border-radius: 8px; background: #eff6ff; color: #1e40af; font-size: 9pt; }
  .ts { font-family: 'Consolas', 'D2Coding', monospace; color: #2563eb; font-size: 9pt; }
  .speaker-me { font-weight: 600; color: #1d4ed8; }
  .speaker-client { font-weight: 600; color: #047857; }
  .seg-row { display: grid; grid-template-columns: 60px 50px 1fr; gap: 6px; padding: 3px 0; border-bottom: 1px dashed #e5e7eb; }
  .footer { margin-top: 24px; text-align: right; font-size: 9pt; color: #9ca3af; }

  /* v2.6.1: 상단 툴바 (← 뒤로 / 🏠 홈 / 📄 PDF 저장) */
  .print-toolbar {
    position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
    background: #ffffff; border-bottom: 1px solid #e5e7eb;
    padding: 8px 16px; display: flex; align-items: center; gap: 8px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.06);
  }
  .toolbar-btn {
    background: #f3f4f6; color: #1f2937; border: 1px solid #d1d5db;
    padding: 6px 12px; border-radius: 6px; font-size: 10pt; cursor: pointer;
    font-family: inherit; transition: background 0.15s;
  }
  .toolbar-btn:hover { background: #e5e7eb; }
  .toolbar-btn.primary { background: #2563eb; color: white; border-color: #2563eb; }
  .toolbar-btn.primary:hover { background: #1d4ed8; }
  .toolbar-spacer { flex: 1; }
  .toolbar-hint { color: #6b7280; font-size: 9pt; }

  @media print {
    .print-toolbar { display: none; }
    body { padding: 0; }
  }
</style>
"""

_PRINT_FOOTER_JS = """
<div class="print-toolbar">
  <button class="toolbar-btn" onclick="goBack()" title="이전 화면으로 (Esc)">← 뒤로</button>
  <button class="toolbar-btn" onclick="goHome()" title="홈 화면으로">🏠 홈</button>
  <div class="toolbar-spacer"></div>
  <span class="toolbar-hint">Esc / 뒤로 = 종료 · Ctrl+P = 인쇄</span>
  <button class="toolbar-btn primary" onclick="window.print()">📄 PDF 로 저장 (인쇄)</button>
</div>
<div class="footer">InterioNote — 인테리어 상담 분석 · 인쇄 다이얼로그에서 "PDF 로 저장" 선택</div>
<script>
  function goBack() {
    // pywebview 환경: history.back 우선, 없으면 홈으로
    if (window.history && window.history.length > 1) {
      window.history.back();
    } else {
      window.location.href = '/';
    }
  }
  function goHome() {
    window.location.href = '/';
  }
  // ESC 키로 뒤로가기 (인쇄 다이얼로그가 열려있을 때는 다이얼로그가 ESC 를 먹음 — 정상)
  window.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      goBack();
    }
  });
</script>
"""


def _fetch_meeting(meeting_id: int):
    with db_cursor() as cur:
        m = cur.execute(
            """
            SELECT m.id, m.meeting_type, m.started_at, m.ended_at, m.duration_sec, m.notes,
                   c.name AS client_name, c.descriptor, c.folder_name
            FROM meetings m JOIN clients c ON c.id = m.client_id
            WHERE m.id = ?
            """,
            (meeting_id,),
        ).fetchone()
        if m is None:
            return None, None, None
        analysis_row = cur.execute(
            "SELECT data_json FROM analyses WHERE meeting_id = ?", (meeting_id,)
        ).fetchone()
        analysis = json.loads(analysis_row["data_json"]) if analysis_row else None
        segs = cur.execute(
            "SELECT start_ms, end_ms, speaker, text FROM transcript_segments "
            "WHERE meeting_id = ? ORDER BY start_ms",
            (meeting_id,),
        ).fetchall()
        return dict(m), analysis, [dict(s) for s in segs]


def _format_ms(ms: int) -> str:
    s = max(0, int(ms or 0)) // 1000
    h, rem = divmod(s, 3600)
    mn, sc = divmod(rem, 60)
    if h:
        return f"{h:d}:{mn:02d}:{sc:02d}"
    return f"{mn:02d}:{sc:02d}"


def _client_header(meeting: dict) -> str:
    title = meeting.get("client_name", "고객")
    desc = meeting.get("descriptor") or ""
    mtype = meeting.get("meeting_type") or "상담"
    started = (meeting.get("started_at") or "").split("T")[0]
    # v3.2.0: 담당자 + 매장명 (settings 에서)
    # v3.5.2 노트: 인쇄 페이지는 인증 없는 화이트리스트라 username 알 수 없음 →
    # 글로벌 designer 값 사용 (사용자별 값은 AI 분석·이메일 초안에만 적용).
    designer = settings_service.get_designer_info()
    designer_name = designer.get("name", "")
    store_name = designer.get("store", "")
    right_info = " · ".join(filter(None, [store_name, designer_name]))
    right_html = (
        f'<span style="float:right;font-size:9.5pt;color:#6b7280;">{right_info}</span>'
        if right_info else ""
    )
    return (
        f'<h1>🏠 {title} 고객님 — {mtype}{right_html}</h1>'
        f'<div class="meta" style="clear:both;">{desc}{" · " if desc else ""}{started}</div>'
    )


# ========================================
# 요약 (AI 분석 결과) 인쇄
# ========================================
@router.get("/{meeting_id}/print-summary", response_class=HTMLResponse)
def print_summary(meeting_id: int):
    meeting, analysis, _ = _fetch_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(404, "meeting not found")

    body_parts = [_client_header(meeting)]

    if not analysis:
        body_parts.append('<div style="color: #ef4444;">⚠ 아직 AI 분석이 진행되지 않았습니다.</div>')
    else:
        # 요약
        if analysis.get("summary"):
            body_parts.append(f'<h2>📌 요약</h2><div>{markdown_to_html(analysis["summary"])}</div>')

        # site_info (인테리어 장소 정보)
        site = analysis.get("site_info") or {}
        if any(site.values()):
            rows = []
            for k, label in [
                ("address", "주소"), ("complex_name", "단지/건물명"),
                ("building_unit", "동/호"), ("size_pyeong", "평형"),
                ("size_m2", "면적(m²)"), ("expansion", "확장 여부"),
                ("structure_type", "구조/공사 종류"),
            ]:
                v = site.get(k)
                if v:
                    rows.append(f"<tr><th style='width: 30%;'>{label}</th><td>{v}</td></tr>")
            if rows:
                body_parts.append("<h2>🏠 인테리어 장소 정보</h2><table>" + "".join(rows) + "</table>")

        # 체크리스트
        checklist = analysis.get("checklist") or analysis.get("checks") or []
        if checklist and isinstance(checklist, list):
            body_parts.append("<h2>✅ 체크리스트</h2><ul>" +
                              "".join(f"<li>{item}</li>" for item in checklist) + "</ul>")

        # 액션 아이템
        actions = analysis.get("action_items") or []
        if actions and isinstance(actions, list):
            body_parts.append("<h2>🎯 액션 아이템</h2><ul>" +
                              "".join(f"<li>{item}</li>" for item in actions) + "</ul>")

        # 기타 키들 (요약/site_info/checklist/action_items 외)
        skip = {"summary", "site_info", "checklist", "checks", "action_items"}
        for k, v in (analysis.items() if isinstance(analysis, dict) else []):
            if k in skip or not v:
                continue
            label = k.replace("_", " ").title()
            if isinstance(v, list):
                body_parts.append(f"<h2>📋 {label}</h2><ul>" +
                                  "".join(f"<li>{item}</li>" for item in v) + "</ul>")
            elif isinstance(v, dict):
                rows = "".join(f"<tr><th>{kk}</th><td>{vv}</td></tr>" for kk, vv in v.items() if vv)
                if rows:
                    body_parts.append(f"<h2>📋 {label}</h2><table>{rows}</table>")
            else:
                body_parts.append(f"<h2>📋 {label}</h2><div>{v}</div>")

    if meeting.get("notes"):
        body_parts.append(f'<h2>📝 상담 메모</h2><div>{markdown_to_html(meeting["notes"])}</div>')

    return HTMLResponse(_render_print(meeting, "AI 분석 요약", "".join(body_parts)))


# ========================================
# 전체 대화 인쇄
# ========================================
@router.get("/{meeting_id}/print-transcript", response_class=HTMLResponse)
def print_transcript(meeting_id: int):
    meeting, _, segs = _fetch_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(404, "meeting not found")

    body_parts = [_client_header(meeting)]
    body_parts.append(f'<div class="meta">총 {len(segs)} 발화 · 길이 {_format_ms((meeting.get("duration_sec") or 0)*1000)}</div>')
    body_parts.append("<h2>📄 전체 대화</h2>")

    rows = []
    for s in segs:
        ts = _format_ms(s["start_ms"])
        sp = s.get("speaker")
        sp_label = ""
        sp_class = ""
        if sp == "me":
            sp_label = "나"; sp_class = "speaker-me"
        elif sp == "client":
            sp_label = "고객"; sp_class = "speaker-client"
        else:
            sp_label = "·"
        text = (s.get("text") or "").replace("<", "&lt;").replace(">", "&gt;")
        rows.append(
            f'<div class="seg-row"><div class="ts">{ts}</div>'
            f'<div class="{sp_class}">{sp_label}</div><div>{text}</div></div>'
        )
    body_parts.append("".join(rows))

    return HTMLResponse(_render_print(meeting, "전체 대화", "".join(body_parts)))


def _render_print(meeting: dict, page_title: str, body_html: str) -> str:
    title = f"{meeting.get('client_name', '고객')} {page_title} - InterioNote"
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>{title}</title>
{_PRINT_BASE_CSS}
</head>
<body>
{body_html}
{_PRINT_FOOTER_JS}
</body>
</html>"""


def markdown_to_html(text: str) -> str:
    """안전한 Markdown → HTML 변환."""
    if not text:
        return ""
    return md.markdown(text, extensions=["nl2br", "tables"])
