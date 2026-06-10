/**
 * v3.5.7 — 마감 작업 백그라운드 진행 배지 (모든 페이지 공통).
 * 헤더 우측 상단 remote_status_badge 옆에 떠 있는 작은 알림.
 * 5초마다 /api/finalize/active 폴링.
 */
(function() {
  'use strict';

  function getUser() {
    try { return JSON.parse(localStorage.getItem('interionote.user') || 'null'); }
    catch(e) { return null; }
  }
  const user = getUser();
  if (!user) return;
  if (window.location.pathname === '/login' || window.location.pathname === '/register') return;

  let badge = null;

  function makeBadge() {
    const wrap = document.createElement('div');
    wrap.id = 'finalize-progress-badge';
    wrap.style.cssText = `
      position: fixed; top: 12px; right: 200px; z-index: 9998;
      background: linear-gradient(135deg, #f59e0b, #d97706); color: #fff;
      font-family: 'Segoe UI', system-ui, sans-serif;
      font-size: 12px; padding: 6px 10px; border-radius: 999px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.18); cursor: pointer;
      display: none; align-items: center; gap: 6px; user-select: none;
    `;
    wrap.innerHTML = `
      <span style="display:inline-block;width:10px;height:10px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;"></span>
      <span class="fpb-text">마감 중...</span>
    `;
    // CSS animation
    if (!document.getElementById('fpb-style')) {
      const style = document.createElement('style');
      style.id = 'fpb-style';
      style.textContent = '@keyframes spin { 100% { transform: rotate(360deg); } }';
      document.head.appendChild(style);
    }
    wrap.addEventListener('click', () => {
      alert('녹음 마감(MP3 인코딩 + 파일 저장)이 백그라운드로 진행 중입니다.\n완료되면 알림이 사라집니다.\n그 동안 다른 작업 자유롭게 진행하세요.');
    });
    document.body.appendChild(wrap);
    return wrap;
  }

  async function poll() {
    if (!badge) badge = makeBadge();
    try {
      const r = await fetch('/api/finalize/active');
      if (!r.ok) return;
      const d = await r.json();
      const active = d.active || [];
      if (active.length === 0) {
        badge.style.display = 'none';
      } else {
        badge.style.display = 'flex';
        const txt = badge.querySelector('.fpb-text');
        if (txt) txt.textContent = active.length === 1
          ? '🔄 마감 중...'
          : `🔄 ${active.length}건 마감 중`;
      }
    } catch(e) {}
  }

  setTimeout(poll, 1500);
  setInterval(poll, 5000);
})();
