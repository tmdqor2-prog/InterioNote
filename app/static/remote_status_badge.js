/**
 * v3.5.3 — 원격 데스크톱 사용 상태 배지 (마스터 전용).
 *
 * 모든 HTML 페이지의 헤더 우측에 자동으로 떠 있는 작은 배지.
 * 5분마다 ping 해서 데스크톱 연결 상태를 갱신함.
 * 클릭하면 상세 모달 (URL, 지연시간, 실패 원인 등) 열림.
 *
 * 사용법: 각 HTML 의 <body> 마지막에 <script src="/static/remote_status_badge.js"></script> 삽입.
 * 페이지 로드 시 자체적으로 마스터 여부 확인 → 배지 DOM 주입 → 주기적 polling.
 */
(function() {
  'use strict';

  // 마스터 여부 확인
  function getUser() {
    try { return JSON.parse(localStorage.getItem('interionote.user') || 'null'); }
    catch(e) { return null; }
  }
  const user = getUser();
  if (!user || user.role !== 'master') return;
  // 로그인 페이지에선 표시 안 함
  if (window.location.pathname === '/login' || window.location.pathname === '/register') return;

  // 배지 DOM 만들기
  function makeBadge() {
    const wrap = document.createElement('div');
    wrap.id = 'remote-status-badge';
    wrap.style.cssText = `
      position: fixed; top: 12px; right: 16px; z-index: 9999;
      background: rgba(99,102,241,0.95); color: #fff;
      font-family: 'Segoe UI', system-ui, sans-serif;
      font-size: 12px; padding: 6px 10px; border-radius: 999px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.18); cursor: pointer;
      display: flex; align-items: center; gap: 6px;
      transition: background 0.2s; user-select: none;
    `;
    wrap.innerHTML = `
      <span class="badge-dot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#9ca3af;"></span>
      <span class="badge-icon">💻</span>
      <span class="badge-text">확인 중...</span>
    `;
    wrap.addEventListener('click', showDetailModal);
    document.body.appendChild(wrap);
    return wrap;
  }

  // 상세 모달
  function showDetailModal() {
    const old = document.getElementById('remote-status-modal');
    if (old) { old.remove(); return; }

    const s = window.__remoteStatus || {};
    const overlay = document.createElement('div');
    overlay.id = 'remote-status-modal';
    overlay.style.cssText = `
      position: fixed; inset: 0; z-index: 10000;
      background: rgba(0,0,0,0.45);
      display: flex; align-items: center; justify-content: center;
      font-family: 'Segoe UI', system-ui, sans-serif;
    `;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

    const isDark = document.documentElement.classList.contains('dark');
    const card = document.createElement('div');
    card.style.cssText = `
      background: ${isDark ? '#1f2937' : '#fff'}; color: ${isDark ? '#e5e7eb' : '#111827'};
      max-width: 420px; padding: 20px 24px; border-radius: 12px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.32);
    `;
    const stateText = s.state === 'remote_ok'   ? '🟢 데스크톱 연결됨'
                    : s.state === 'remote_fail' ? '🔴 데스크톱 연결 안 됨'
                    : '💻 노트북(이 PC) 사용 중';
    const colorBg = s.state === 'remote_ok' ? '#10b981'
                  : s.state === 'remote_fail' ? '#ef4444'
                  : '#6366f1';
    card.innerHTML = `
      <div style="font-size:18px;font-weight:600;margin-bottom:12px;display:flex;align-items:center;justify-content:space-between;">
        <span>원격 데스크톱 상태</span>
        <button id="rsm-close" style="background:none;border:none;font-size:22px;cursor:pointer;color:${isDark?'#9ca3af':'#6b7280'};">×</button>
      </div>
      <div style="background:${colorBg};color:#fff;padding:10px 14px;border-radius:8px;font-weight:600;margin-bottom:14px;">
        ${stateText}
      </div>
      ${s.reason ? `<div style="font-size:14px;line-height:1.5;color:${isDark?'#d1d5db':'#374151'};white-space:pre-wrap;">${escapeHtml(s.reason)}</div>` : ''}
      ${s.url ? `<div style="font-size:11px;font-family:monospace;color:${isDark?'#9ca3af':'#6b7280'};margin-top:8px;word-break:break-all;">URL: ${escapeHtml(s.url)}</div>` : ''}
      ${typeof s.latency_ms === 'number' ? `<div style="font-size:11px;color:${isDark?'#9ca3af':'#6b7280'};margin-top:4px;">응답 시간: ${s.latency_ms}ms</div>` : ''}
      ${s.state === 'remote_fail' ? `
        <div style="margin-top:14px;padding:10px 12px;background:${isDark?'#7f1d1d33':'#fef2f2'};border-radius:6px;font-size:13px;color:${isDark?'#fca5a5':'#991b1b'};">
          <div style="font-weight:600;margin-bottom:6px;">📋 점검 항목</div>
          <ul style="margin:0;padding-left:18px;line-height:1.7;">
            <li>데스크톱 PC 가 켜져 있나요?</li>
            <li>데스크톱에서 InterioNote 가 실행 중인가요?</li>
            <li>두 PC 가 같은 Tailscale 계정에 로그인돼 있나요?</li>
            <li>데스크톱 cmd 에서 <code>setx OLLAMA_HOST "0.0.0.0:11434" /M</code> 실행했나요?</li>
            <li>데스크톱 Ollama 가 재시작됐나요?</li>
          </ul>
        </div>
      ` : ''}
      ${s.state === 'local_only' ? `
        <div style="margin-top:14px;padding:10px 12px;background:${isDark?'#1e3a8a33':'#eff6ff'};border-radius:6px;font-size:13px;color:${isDark?'#93c5fd':'#1e40af'};">
          💡 노트북에서 데스크톱 성능을 빌려 쓰려면<br>
          <strong>설정 → AI 분석 → 🖥 원격 데스크톱 컴퓨팅</strong> 에서 설정하세요.
        </div>
      ` : ''}
      <div style="display:flex;gap:8px;margin-top:16px;">
        <button id="rsm-refresh" style="flex:1;background:${isDark?'#374151':'#f3f4f6'};color:${isDark?'#e5e7eb':'#111827'};border:none;padding:8px;border-radius:6px;font-size:13px;cursor:pointer;">🔄 다시 확인</button>
        <button id="rsm-settings" style="flex:1;background:#6366f1;color:#fff;border:none;padding:8px;border-radius:6px;font-size:13px;cursor:pointer;">⚙ 설정 열기</button>
      </div>
    `;
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    document.getElementById('rsm-close').onclick = () => overlay.remove();
    document.getElementById('rsm-refresh').onclick = () => { overlay.remove(); poll(); };
    document.getElementById('rsm-settings').onclick = () => { window.location.href = '/settings#ai'; };
  }

  function escapeHtml(s) {
    return String(s || '').replace(/[<>"']/g, c => ({'<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // 폴링
  let badge = null;
  async function poll() {
    if (!badge) badge = makeBadge();
    try {
      const r = await fetch('/api/auth/me/remote-status');
      if (!r.ok) {
        updateBadge('unknown', '?');
        return;
      }
      const d = await r.json();
      window.__remoteStatus = d;
      switch (d.state) {
        case 'remote_ok':   updateBadge('ok',   '🖥 데스크톱'); break;
        case 'remote_fail': updateBadge('fail', '🔴 연결 실패'); break;
        case 'local_only':  updateBadge('local','💻 노트북');   break;
        default:            updateBadge('unknown', '?');
      }
    } catch (e) {
      updateBadge('unknown', '?');
    }
  }

  function updateBadge(state, text) {
    if (!badge) return;
    const dot = badge.querySelector('.badge-dot');
    const txt = badge.querySelector('.badge-text');
    const colors = {
      ok:      ['#10b981', '#059669'],
      fail:    ['#ef4444', '#dc2626'],
      local:   ['#6366f1', '#4f46e5'],
      unknown: ['#9ca3af', '#6b7280'],
    };
    const [light, dark] = colors[state] || colors.unknown;
    dot.style.background = '#fff';
    badge.style.background = `linear-gradient(135deg, ${light}, ${dark})`;
    txt.textContent = text;
  }

  // 초기 + 5분마다
  setTimeout(poll, 800);   // 페이지 로드 후 첫 폴
  setInterval(poll, 5 * 60 * 1000);

  // 분석/재전사 같은 작업 직후엔 즉시 갱신 (다른 코드가 호출 가능)
  window.refreshRemoteStatus = poll;
})();
