'use strict';
const $ = id => document.getElementById(id);
let apiReady = false;
let curRunning = false;
let compareData = null;
let reportData = null;

function renderCompare() {
  const el = $('cmp');
  if (!el) return;
  const r = reportData || compareData;
  if (!r) {
    if (!el.querySelector('.cmp-empty'))
      el.innerHTML = '<div class="cmp-empty">체험을 완료하면 전/후 안정 상태를 비교해 드려요.</div>';
    return;
  }
  const up = r.delta >= 0;
  const qr = (reportData && reportData.qr)
    ? `<div class="cmp-qr"><div class="qrbox">${reportData.qr}</div>
         <div class="qr-cap">📱 QR을 찍으면<br>나의 <b>마음 리포트</b>를<br>볼 수 있어요</div></div>`
    : '';
  el.innerHTML =
    `<div class="cmp-grid">
       <div class="cmp-col"><span class="cmp-cap">체험 전</span><span class="cmp-score">${r.preScore}</span><span class="cmp-avg">평균 ${r.pre}</span></div>
       <div class="cmp-arrow">→</div>
       <div class="cmp-col after"><span class="cmp-cap">체험 후</span><span class="cmp-score">${r.postScore}</span><span class="cmp-avg">평균 ${r.post}</span></div>
     </div>
     <div class="cmp-delta ${up ? 'up' : 'down'}">${up ? '▲' : '▼'} 안정도 ${up ? '+' : ''}${r.delta} ${up ? '향상' : '변화'}</div>
     ${qr}`;
}

function api() { return window.pywebview && window.pywebview.api; }

// ---------- 컨트롤 ----------
function cfg() {
  const g = id => $(id).value;
  return {
    ip: g('ip'), port: g('oport'), interval: g('interval'), max_amp: g('max_amp'),
    min_med: g('min_med'), wait: g('wait'), analysis_dur: g('analysis_dur'),
    balance_n: g('balance_n'), bal_step: g('bal_step'), calm_mult: g('calm_mult'),
    min_view: g('min_view'), max_view: g('max_view'), retention: g('retention'),
  };
}

async function refreshPorts() {
  if (!api()) return false;
  try {
    const ports = await api().list_ports();
    const sel = $('port');
    const cur = sel.value;
    sel.innerHTML = '';
    (ports || []).forEach(p => { const o = document.createElement('option'); o.textContent = p; sel.appendChild(o); });
    if (ports && ports.length) {
      if ([...sel.options].some(o => o.value === cur)) sel.value = cur;
      else if ([...sel.options].some(o => o.value === 'COM4')) sel.value = 'COM4';
      else if ([...sel.options].some(o => o.value === 'COM3')) sel.value = 'COM3';
      return true;
    }
    return false;
  } catch (e) { return false; }
}

function bind() {
  $('btnRefresh').onclick = refreshPorts;
  $('btnClear').onclick = () => api() && api().clear();
  $('btnStart').onclick = () => api() && api().start_experience();
  $('btnReset').onclick = () => api() && api().reset();
  $('btnNext').onclick = () => api() && api().next_stage();
  $('btnForest').onclick = () => api() && api().test_world(0);
  $('btnDesert').onclick = () => api() && api().test_world(1);
  $('paramToggle').onclick = () => $('paramBody').classList.toggle('hide');
  $('btnOpen').onclick = async () => {
    if (!api()) return;
    if (!curRunning) {
      const r = await api().open($('port').value, $('bps').value, cfg());
      if (!(r && r.ok)) alert('열 수 없음: ' + (r && r.error));
    } else {
      await api().close();
    }
  };
}

// ---------- 게이지 ----------
function drawGauge(score) {
  const cv = $('gauge'), ctx = cv.getContext('2d');
  const W = cv.width, cx = W / 2, cy = W / 2, r = W / 2 - 22;
  ctx.clearRect(0, 0, W, W);
  // 배경 링
  ctx.lineWidth = 16; ctx.lineCap = 'round';
  ctx.strokeStyle = '#222c46';
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
  // 값 링 (그라데이션 + 글로우)
  const start = -Math.PI / 2;
  const end = start + Math.PI * 2 * (score / 100);
  const g = ctx.createLinearGradient(0, 0, W, W);
  g.addColorStop(0, '#34d3b0'); g.addColorStop(0.5, '#7fd0e0'); g.addColorStop(1, '#d98fd0');
  ctx.strokeStyle = g; ctx.shadowColor = 'rgba(52,211,176,.55)'; ctx.shadowBlur = 18;
  ctx.beginPath(); ctx.arc(cx, cy, r, start, end); ctx.stroke();
  ctx.shadowBlur = 0;
  // 숫자
  ctx.fillStyle = '#e6ebf5'; ctx.textAlign = 'center';
  ctx.font = '700 46px Malgun Gothic'; ctx.fillText(Math.round(score), cx, cy + 10);
  ctx.fillStyle = '#5f6b85'; ctx.font = '600 13px Malgun Gothic'; ctx.fillText('/ 100', cx, cy + 34);
}

// ---------- 추이 (부드러운 발광 곡선) ----------
function drawTrend(data, baseline) {
  const cv = $('trend'), ctx = cv.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = 240;
  if (cv.width !== W * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const padT = 14, padB = 22, padX = 6;
  const scale = Math.max(30, ...(data || [0]));
  const yOf = v => (H - padB) - (v / scale) * (H - padT - padB);
  // 격자
  ctx.strokeStyle = 'rgba(40,48,76,.6)'; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) { const y = padT + i * (H - padT - padB) / 4; ctx.beginPath(); ctx.moveTo(padX, y); ctx.lineTo(W - padX, y); ctx.stroke(); }
  // 기준선
  if (baseline >= 1) {
    const by = yOf(baseline);
    ctx.strokeStyle = 'rgba(224,182,84,.55)'; ctx.setLineDash([5, 5]);
    ctx.beginPath(); ctx.moveTo(padX, by); ctx.lineTo(W - padX, by); ctx.stroke(); ctx.setLineDash([]);
  }
  if (!data || data.length < 2) return;
  const n = data.length;
  const xOf = i => padX + i / (n - 1) * (W - padX * 2);
  const pts = data.map((v, i) => [xOf(i), yOf(v)]);
  // 스무딩 곡선 path (Catmull-Rom → bezier)
  function curve() {
    ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 0; i < n - 1; i++) {
      const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
      const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
      ctx.bezierCurveTo(c1x, c1y, c2x, c2y, p2[0], p2[1]);
    }
  }
  // 영역 채움 (그라데이션 페이드)
  curve(); ctx.lineTo(pts[n - 1][0], H - padB); ctx.lineTo(pts[0][0], H - padB); ctx.closePath();
  const fg = ctx.createLinearGradient(0, padT, 0, H - padB);
  fg.addColorStop(0, 'rgba(52,211,176,.28)'); fg.addColorStop(1, 'rgba(52,211,176,0)');
  ctx.fillStyle = fg; ctx.fill();
  // 발광 곡선
  const lg = ctx.createLinearGradient(0, 0, W, 0);
  lg.addColorStop(0, '#34d3b0'); lg.addColorStop(1, '#d98fd0');
  ctx.strokeStyle = lg; ctx.lineWidth = 2.6; ctx.lineJoin = 'round';
  ctx.shadowColor = 'rgba(52,211,176,.55)'; ctx.shadowBlur = 12;
  curve(); ctx.stroke(); ctx.shadowBlur = 0;
  // 끝점
  const last = pts[n - 1];
  ctx.fillStyle = '#d98fd0'; ctx.shadowColor = 'rgba(217,143,208,.8)'; ctx.shadowBlur = 12;
  ctx.beginPath(); ctx.arc(last[0], last[1], 4.5, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
}

// ---------- 렌더 ----------
let lastLogKey = '';
function render(s) {
  if (!s) return;
  $('stagePill').textContent = '● ' + s.stage_name + ' · ' + s.stage + '단계' +
    (s.countdown != null ? ' · ' + s.countdown + '초' : '');
  $('stagePill').classList.toggle('emo', s.stage === 3 || s.stage === 4);
  $('rx').textContent = s.rx;
  $('runtime').textContent = s.runtime;
  $('devStatus').className = 'dev' + (s.running ? ' on' : '');
  $('devStatus').innerHTML = '<span class="dot"></span> ' + (s.running ? '디바이스 연결됨' : '대기 중');
  // OPEN/CLOSE 버튼을 실제 연결상태에 동기화 (새로고침 후에도 정확)
  curRunning = s.running;
  const bo = $('btnOpen');
  bo.textContent = s.running ? 'CLOSE' : 'OPEN';
  bo.classList.toggle('desert', s.running);
  bo.classList.toggle('connect', !s.running);

  // 상태 카드
  let state = '대기', desc = '체험을 시작하면 마음 상태를 분석합니다.', orb = '🧘';
  if (s.emotion_name === '분노') { state = '분노'; desc = '긴장이 높아요. 천천히 호흡해 보세요.'; orb = '🏜'; }
  else if (s.emotion_name === '불안') { state = '불안'; desc = '마음이 흔들려요. 지금에 머물러 보세요.'; orb = '🌲'; }
  else if (s.stage >= 1) { state = '차분함'; desc = '마음이 안정되고 균형을 이루고 있어요.'; orb = '🧘'; }
  $('stateBig').textContent = state; $('stateDesc').textContent = desc; $('orb').textContent = orb;

  const st = s.stats;
  if (st) {
    $('mAvg').textContent = st.avg; $('mPeak').textContent = st.peak; $('mRange').textContent = st.range;
    $('mMinMax').textContent = st.min + ' / ' + st.max; $('mMode').textContent = st.mode;
  }
  $('mBase').textContent = s.baseline >= 1 ? s.baseline + ' (' + s.baseline_n + ')' : '-';
  $('scoreSub').textContent = s.running ? '실시간 진정도' : '측정 대기';
  const b = s.balance;
  $('balText').textContent = b && b.n ? `분노/불안 균형 — 최근 ${b.n}명 중 분노 ${b.anger} / 불안 ${b.n - b.anger}` : '분노/불안 균형 —';

  // 전/후 비교: 새 체험 시작 시 리셋, 명상 종료(4) 진입 시 캡처
  if (s.stage <= 1) { compareData = null; reportData = null; }
  if (s.report && s.report.ready) reportData = s.report;
  if (s.stage === 4 && !compareData && s.baseline >= 1 && s.stats) {
    const sc = a => Math.max(0, Math.min(100, Math.round(100 - a * 2.5)));
    compareData = { pre: s.baseline, post: s.stats.avg, preScore: sc(s.baseline), postScore: sc(s.stats.avg) };
    compareData.delta = compareData.postScore - compareData.preScore;
  }
  renderCompare();

  drawGauge(s.score || 0);
  drawTrend(s.trend, s.baseline);

  // 로그 (최근 40줄로 잘려 길이가 40 고정되므로, 마지막 줄+길이로 변경 감지)
  if (s.log) {
    const key = s.log.length + '|' + (s.log[s.log.length - 1] || '');
    if (key !== lastLogKey) {
      lastLogKey = key;
      const el = $('log');
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      el.innerHTML = s.log.map(l => {
        let cls = '';
        if (l.includes('감정 분류') || l.includes('단계 전환') || l.includes('테스트')) cls = 'evt';
        else if (l.includes('기준 평균')) cls = 'base';
        return `<div class="${cls}">${l}</div>`;
      }).join('');
      if (atBottom) el.scrollTop = el.scrollHeight;
    }
  }
}

async function loop() {
  const dbg = $('dbg');
  const a = api();
  if (a) {
    // 포트 목록이 비어 있으면(초기/새로고침 직후) 채워질 때까지 자동 재시도
    if (!$('port').options.length) { await refreshPorts(); }
    try {
      const s = await a.poll();
      render(s);
      if (dbg) dbg.textContent = 'API OK';
    } catch (e) {
      if (dbg) dbg.textContent = 'poll 오류: ' + e;
    }
  } else {
    if (dbg) dbg.textContent = 'API 대기중…';
  }
  setTimeout(loop, 120);
}

function init() {
  bind();       // 클릭 핸들러는 api() 를 클릭 시점에 확인하므로 즉시 바인딩 안전
  loop();       // 폴링 시작 (api 준비되면 자동으로 값 불러옴)
}
window.addEventListener('pywebviewready', () => { apiReady = true; });
if (document.readyState !== 'loading') init();
else document.addEventListener('DOMContentLoaded', init);
