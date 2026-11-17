'use strict';
/* NeuroScape 운영 화면.
   메인 = 진행 단계 · 안정도 · 실시간 흐름 · 결과.  연결/테스트/파라미터/로그는 설정 서랍. */
const $ = id => document.getElementById(id);
let S = null;              // 마지막 스냅샷
let compareData = null;    // 리포트가 오기 전 임시 전/후 값
let reportData = null;

function api() { return window.pywebview && window.pywebview.api; }

// ---------- 설정값 ----------
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
    const sel = $('port'), cur = sel.value;
    sel.innerHTML = '';
    (ports || []).forEach(p => { const o = document.createElement('option'); o.textContent = p; sel.appendChild(o); });
    if (ports && ports.length) {
      const has = v => [...sel.options].some(o => o.value === v);
      sel.value = has(cur) ? cur : (has('COM3') ? 'COM3' : ports[0]);
      return true;
    }
  } catch (e) { /* 무시 */ }
  return false;
}

// ---------- 서랍 / 관객 화면 ----------
function openDrawer(on) {
  $('drawer').classList.toggle('on', on);
  $('scrim').classList.toggle('on', on);
  if (on) refreshPorts();
}
function showVisitor(on) { $('visitor').hidden = !on; }

// ---------- 단계 정의 ----------
const fmt = s => { s = Math.max(0, Math.round(s)); return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); };
const WORLD = {
  forest: { name: '숲 · 불안', desc: '마음이 흔들린 상태로 분류됐어요. 숲 속에서 지금에 머무르도록 안내해요.' },
  desert: { name: '사막 · 분노', desc: '긴장이 높은 상태로 분류됐어요. 사막의 밤하늘 아래에서 호흡을 고르도록 안내해요.' },
};

function stepOf(s) {
  if (s.stage === 0) return s.exp_active ? 1 : 0;
  if (s.stage === 1) return 2;
  if (s.stage === 2) return 3;
  if (s.stage === 3) return 4;
  if (s.stage === 4 || s.stage === 5) return 5;
  return 6;
}

function describe(s) {
  const t = s.timing || {}, el = s.stage_elapsed || 0;
  const w = s.world && WORLD[s.world] ? WORLD[s.world].name.split(' ')[0] : '';
  const sigWarn = s.signal === 'contact' ? ' <span class="warn">전극 접촉이 불안정해요. 헤드밴드 위치를 확인해 주세요.</span>'
                : s.signal === 'nodata' ? ' <span class="warn">헤드밴드 신호가 끊겼어요. 전원과 블루투스를 확인해 주세요.</span>' : '';
  switch (stepOf(s)) {
    case 0:
      if (!s.running) return { title: '관객 맞이 준비', guide: '먼저 오른쪽 위 <b>설정</b>에서 EEG 헤드밴드를 연결해 주세요.', p: 0, timer: '' };
      return { title: '관객 맞이 준비', guide: 'EEG 헤드밴드와 VR 헤드셋을 씌워 주세요. 준비되면 <b>체험 시작</b>을 눌러요.' + sigWarn, p: 0, timer: '' };
    case 1: {
      const left = s.countdown != null ? s.countdown : 0;
      return { title: '인트로 영상', guide: '관객이 인트로 영상을 보고 있어요. 처음 10초 동안 평소 뇌파(기준선)를 측정해요.' + sigWarn,
               p: 1 - left / (t.intro || 71), timer: fmt((t.intro || 71) - left) + ' / ' + fmt(t.intro || 71) };
    }
    case 2:
      return { title: '명상', guide: '편안히 호흡하도록 안내해 주세요. 신호가 안정되면 자동으로 분석을 시작해요.' + sigWarn,
               p: Math.min(1, el / Math.max(1, t.min_med || 10)), timer: fmt(el) };
    case 3:
      return { title: '뇌파 분석', guide: '지금 뇌파를 기준선과 비교해 감정 월드를 정하고 있어요.',
               p: Math.min(1, el / Math.max(1, t.analysis || 6)), timer: fmt(el) + ' / ' + fmt(t.analysis || 6) };
    case 4: {
      const minV = t.min_view || 90, maxV = t.max_view || 180;
      const g = el < minV ? `뇌파가 흔들리면 오브젝트의 빛도 흔들려요. 최소 ${Math.round(minV)}초 동안 머물러요.`
                          : '뇌파가 기준선 아래로 가라앉으면 마무리로 넘어가요.';
      return { title: (w ? w + ' 월드' : '감정 월드'), guide: g + sigWarn, p: Math.min(1, el / maxV), timer: fmt(el) + ' / 최대 ' + fmt(maxV) };
    }
    case 5: {
      const seg = s.stage === 4 ? el : (t.seek_home || 15) + el;
      const tot = (t.seek_home || 15) + (t.init_world || 10);
      return { title: '마무리', guide: '장면이 처음 공간으로 돌아오고 있어요. 마음 리포트가 준비됐어요.', p: Math.min(1, seg / tot), timer: fmt(seg) + ' / ' + fmt(tot) };
    }
    default: {
      const o = t.outro || 24;
      const done = el >= o;
      return { title: done ? '체험 완료' : '엔딩 영상',
               guide: done ? '헤드셋과 헤드밴드를 벗겨 드리고, <b>결과 화면</b>으로 QR 리포트를 안내해 주세요.'
                           : '엔딩 영상이 끝나면 헤드셋을 벗겨 드려요.',
               p: Math.min(1, el / o), timer: done ? '' : fmt(el) + ' / ' + fmt(o) };
    }
  }
}

// ---------- 버튼 상태 ----------
function primaryAction(s) {
  if (!s || !s.running) return { label: 'EEG 연결하기', act: 'connect' };
  const st = stepOf(s);
  if (st === 0) return { label: '체험 시작', act: 'start' };
  if (st === 6) return { label: '결과 화면 보기', act: 'visitor', ready: !!(reportData || compareData) };
  return { label: '체험 진행 중', act: null };
}
function secondaryAction(s) {
  if (!s || !s.running) return null;
  const st = stepOf(s);
  if (st === 0) return null;
  if (st === 6) return { label: '다음 관객 준비', act: 'next', calm: true };
  return { label: '체험 중단', act: 'stop' };
}

async function doAction(act) {
  const a = api();
  if (act === 'connect') return openDrawer(true);
  if (!a) return;
  if (act === 'start') {
    if (S && S.signal !== 'ok' && !S.test &&
        !confirm('헤드밴드 신호가 아직 안정적이지 않아요. 그래도 시작할까요?')) return;
    compareData = null; reportData = null;
    return a.start_experience();
  }
  if (act === 'visitor') return showVisitor(true);
  if (act === 'stop') {
    if (!confirm('체험을 중단하고 처음 대기 상태로 돌아갈까요?')) return;
    return a.reset();
  }
  if (act === 'next') { showVisitor(false); compareData = null; reportData = null; return a.reset(); }
}

function bind() {
  $('btnSettings').onclick = () => openDrawer(true);
  $('btnCloseDrawer').onclick = () => openDrawer(false);
  $('scrim').onclick = () => openDrawer(false);
  $('btnShowVisitor').onclick = () => showVisitor(true);
  $('btnCloseVisitor').onclick = () => showVisitor(false);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { showVisitor(false); openDrawer(false); }
  });
  $('btnPrimary').onclick = () => doAction($('btnPrimary').dataset.act);
  $('btnSecondary').onclick = () => doAction($('btnSecondary').dataset.act);

  $('btnRefresh').onclick = refreshPorts;
  $('btnClear').onclick = () => api() && api().clear();
  $('btnNext').onclick = () => api() && api().next_stage();
  $('btnForest').onclick = () => api() && api().test_world(0);
  $('btnDesert').onclick = () => api() && api().test_world(1);
  $('btnOpen').onclick = async () => {
    if (!api()) return;
    if (S && S.running) { await api().close(); return; }
    const r = await api().open($('port').value, $('bps').value, cfg());
    if (!(r && r.ok)) alert('헤드밴드에 연결하지 못했어요.\n헤드밴드 전원과 블루투스를 확인해 주세요.\n\n(' + (r && r.error) + ')');
    else openDrawer(false);
  };
  $('btnTest').onclick = async () => {
    if (!api()) return;
    if (S && S.running) await api().close();
    const r = await api().open_test(cfg(), $('testEmo').value);
    if (!(r && r.ok)) alert('테스트 모드를 시작하지 못했어요: ' + (r && r.error));
    else openDrawer(false);
  };
}

// ---------- 게이지 ----------
function drawGauge(score, active) {
  const cv = $('gauge'), ctx = cv.getContext('2d');
  const W = cv.width, c = W / 2, r = W / 2 - 16;
  ctx.clearRect(0, 0, W, W);
  ctx.lineCap = 'round';
  ctx.lineWidth = 10; ctx.strokeStyle = 'rgba(255,255,255,.06)';
  ctx.beginPath(); ctx.arc(c, c, r, 0.75 * Math.PI, 2.25 * Math.PI); ctx.stroke();
  if (active) {
    const end = 0.75 * Math.PI + 1.5 * Math.PI * Math.max(0, Math.min(1, score / 100));
    const g = ctx.createLinearGradient(0, W, W, 0);
    g.addColorStop(0, '#8fb8ff'); g.addColorStop(1, '#7fe0c8');
    ctx.strokeStyle = g; ctx.shadowColor = 'rgba(127,224,200,.35)'; ctx.shadowBlur = 14;
    ctx.beginPath(); ctx.arc(c, c, r, 0.75 * Math.PI, end); ctx.stroke(); ctx.shadowBlur = 0;
  }
  ctx.textAlign = 'center';
  ctx.fillStyle = active ? '#e9edf4' : '#4b5466';
  ctx.font = '600 58px "Segoe UI Variable Display","Segoe UI",sans-serif';
  ctx.fillText(active ? Math.round(score) : '–', c, c + 18);
  ctx.fillStyle = '#6c7689'; ctx.font = '500 13px "Segoe UI","Malgun Gothic",sans-serif';
  ctx.fillText('/ 100', c, c + 44);
}

// ---------- 실시간 흐름 ----------
function drawTrend(data, baseline) {
  const cv = $('trend'), ctx = cv.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight || 200;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const padT = 10, padB = 10, padR = 8;
  const top = Math.max(24, baseline * 3 || 0, ...(data || [0]));
  const yOf = v => (H - padB) - (v / top) * (H - padT - padB);
  ctx.strokeStyle = 'rgba(255,255,255,.04)'; ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) { const y = padT + i * (H - padT - padB) / 4; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
  if (baseline >= 1) {
    const by = yOf(baseline);
    ctx.strokeStyle = 'rgba(170,179,196,.45)'; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(0, by); ctx.lineTo(W, by); ctx.stroke(); ctx.setLineDash([]);
  }
  if (!data || data.length < 2) {
    ctx.fillStyle = '#4b5466'; ctx.font = '13px "Segoe UI","Malgun Gothic",sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('헤드밴드가 연결되면 뇌파 활동이 여기에 그려져요', W / 2, H / 2);
    return;
  }
  // 부드럽게: 3포인트 이동평균
  const sm = data.map((v, i) => (data[Math.max(0, i - 1)] + v + data[Math.min(data.length - 1, i + 1)]) / 3);
  const n = sm.length, xOf = i => i / (n - 1) * (W - padR);
  const pts = sm.map((v, i) => [xOf(i), yOf(v)]);
  const path = () => {
    ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 0; i < n - 1; i++) {
      const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      ctx.bezierCurveTo(p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6,
                        p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6, p2[0], p2[1]);
    }
  };
  path(); ctx.lineTo(W - padR, H - padB); ctx.lineTo(0, H - padB); ctx.closePath();
  const fg = ctx.createLinearGradient(0, padT, 0, H);
  fg.addColorStop(0, 'rgba(127,224,200,.18)'); fg.addColorStop(1, 'rgba(127,224,200,0)');
  ctx.fillStyle = fg; ctx.fill();
  ctx.strokeStyle = '#7fe0c8'; ctx.lineWidth = 2; ctx.lineJoin = 'round';
  path(); ctx.stroke();
  const l = pts[n - 1];
  ctx.fillStyle = '#7fe0c8'; ctx.beginPath(); ctx.arc(l[0], l[1], 3.5, 0, Math.PI * 2); ctx.fill();
}

// ---------- 결과 ----------
function setResult(r) {
  const has = !!r;
  $('resultCard').hidden = !has;
  document.querySelector('.layout').classList.toggle('has-result', has);
  if (!has) return;
  const up = r.delta >= 0;
  $('rPre').textContent = r.preScore; $('rPost').textContent = r.postScore;
  $('rDelta').textContent = (up ? '+' : '') + r.delta + (up ? ' 안정' : '');
  $('rDelta').className = 'res-delta' + (up ? '' : ' down');
  $('vPre').textContent = r.preScore; $('vPost').textContent = r.postScore;
  $('vDelta').textContent = up ? `마음이 ${r.delta}만큼 더 고요해졌어요` : '오늘은 마음이 조금 분주했어요. 그것도 괜찮아요.';
  $('vDelta').className = 'v-delta' + (up ? '' : ' down');
  const w = r.world || (S && S.world);
  $('vWorld').innerHTML = w ? `당신이 머문 곳 · <b class="${w}">${WORLD[w].name.split(' ')[0]}</b>` : '';
  const qr = (reportData && reportData.qr) || '';
  if ($('rQr').dataset.k !== String(qr.length)) {
    $('rQr').innerHTML = qr; $('vQr').innerHTML = qr; $('rQr').dataset.k = String(qr.length);
  }
  $('rQr').hidden = !qr; document.querySelector('.v-qr-wrap').hidden = !qr;
}

// ---------- 렌더 ----------
let lastLogKey = '';
function render(s) {
  S = s;
  // 상단 상태
  const dev = $('chipDev');
  dev.className = 'chip' + (s.test ? ' test' : (s.running ? ' ok' : ''));
  dev.querySelector('span').textContent = s.test ? '테스트 모드' : (s.running ? 'EEG 연결됨' : 'EEG 미연결');
  const sig = $('chipSig');
  const sigTxt = { off: '신호 없음', nodata: '신호 끊김', contact: '전극 확인', ok: '착용 양호' }[s.signal] || '신호 없음';
  sig.className = 'chip' + (s.signal === 'ok' ? ' ok' : (s.running ? ' warn' : ''));
  sig.querySelector('span').textContent = sigTxt;
  $('runtime').textContent = s.runtime;

  // 진행
  const st = stepOf(s), d = describe(s);
  $('stepNo').textContent = st === 0 ? '준비' : `STEP ${st} / 6`;
  $('stageTitle').textContent = d.title;
  $('stageGuide').innerHTML = d.guide;
  $('stageTimer').textContent = d.timer || '';
  $('stageBar').style.width = Math.round(Math.max(0, Math.min(1, d.p)) * 100) + '%';
  document.querySelectorAll('#timeline li').forEach(li => {
    const k = +li.dataset.step;
    li.classList.toggle('done', st > k || (st === 6 && k === 6 && (s.stage_elapsed || 0) >= ((s.timing || {}).outro || 24)));
    li.classList.toggle('now', st === k);
  });
  $('checks').hidden = st !== 0;
  $('ckDev').className = 'check' + (s.running ? ' ok' : '');
  $('ckSig').className = 'check' + (s.signal === 'ok' ? ' ok' : (s.running ? ' warn' : ''));

  // 버튼
  if (s.stage <= 3) { compareData = null; reportData = null; }   // 새 관객 / 진행 중엔 결과 숨김
  if (s.report && s.report.ready && s.stage >= 4) reportData = s.report;
  if (s.stage === 4 && !compareData && s.baseline >= 1 && s.stats) {
    const sc = a => Math.max(0, Math.min(100, Math.round(100 - a * 2.5)));
    compareData = { pre: s.baseline, post: s.stats.avg, preScore: sc(s.baseline), postScore: sc(s.stats.avg) };
    compareData.delta = compareData.postScore - compareData.preScore;
  }
  const pa = primaryAction(s), sa = secondaryAction(s);
  const bp = $('btnPrimary');
  bp.textContent = pa.label; bp.dataset.act = pa.act || '';
  bp.disabled = !pa.act || (pa.act === 'visitor' && !pa.ready);
  const bs = $('btnSecondary');
  bs.hidden = !sa;
  if (sa) { bs.textContent = sa.label; bs.dataset.act = sa.act; bs.classList.toggle('calm', !!sa.calm); }

  // 안정도
  // 안정도: 마음 리포트와 같은 기준 (100 - 평균×2.5) 으로 맞춰 운영 화면과 관객 결과가 일치하게
  const active = s.running && (s.stats != null) && st >= 1;
  const calm = s.stats ? Math.max(0, Math.min(100, Math.round(100 - s.stats.avg * 2.5))) : 0;
  drawGauge(calm, active);
  $('scoreSub').textContent = !s.running ? '측정 전' : (st === 0 ? '체험을 시작하면 측정해요' : (s.baseline >= 1 ? '기준선 대비 지금의 고요함' : '기준선 측정 중'));

  // 월드
  const wc = $('worldCard');
  wc.className = 'card world' + (s.world ? ' ' + s.world : '');
  $('worldName').textContent = s.world ? WORLD[s.world].name : (st === 3 ? '분석 중…' : '분석 전');
  $('worldDesc').textContent = s.world ? WORLD[s.world].desc : '명상이 끝나면 뇌파로 월드를 정해요.';

  drawTrend(st >= 1 ? s.trend : [], s.baseline);
  setResult(reportData || compareData);

  // 설정 서랍 내부
  const bo = $('btnOpen');
  bo.textContent = s.running && !s.test ? '연결 끊기' : '연결';
  bo.classList.toggle('on', s.running && !s.test);
  const bt = $('btnTest');
  bt.textContent = s.test ? '테스트 종료' : '가상 EEG로 연결';
  bt.classList.toggle('on', !!s.test);
  if (s.test) bt.onclick = async () => { await api().close(); };
  else bt.onclick = async () => {
    if (!api()) return;
    if (S && S.running) await api().close();
    const r = await api().open_test(cfg(), $('testEmo').value);
    if (!(r && r.ok)) alert('테스트 모드를 시작하지 못했어요: ' + (r && r.error)); else openDrawer(false);
  };
  $('rx').textContent = s.rx + ' 패킷';
  const b = s.balance;
  $('balText').textContent = b && b.n ? `최근 ${b.n}명 · 분노(사막) ${b.anger} / 불안(숲) ${b.n - b.anger}` : '아직 체험한 관객이 없어요.';

  if (s.log && $('drawer').classList.contains('on')) {
    const key = s.log.length + '|' + (s.log[s.log.length - 1] || '');
    if (key !== lastLogKey) {
      lastLogKey = key;
      const el = $('log');
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      el.innerHTML = s.log.map(l => {
        const cls = (l.includes('감정 분류') || l.includes('단계 전환') || l.includes('테스트')) ? 'evt' : (l.includes('기준 평균') ? 'base' : '');
        return `<div class="${cls}">${l.replace(/</g, '&lt;')}</div>`;
      }).join('');
      if (atBottom) el.scrollTop = el.scrollHeight;
    }
  }
}

async function loop() {
  const a = api();
  if (a) {
    if (!$('port').options.length) await refreshPorts();
    try { render(await a.poll()); } catch (e) { /* 다음 주기에 재시도 */ }
  } else {
    render(DEMO);
  }
  setTimeout(loop, 150);
}

// pywebview 밖(브라우저 미리보기)에서 화면을 보기 위한 정적 상태
const DEMO = { running: false, test: false, stage: 0, exp_active: false, signal: 'off', runtime: '00:00:00',
  stats: null, score: 0, trend: [], baseline: 0, rx: 0, balance: { n: 0, anger: 0 }, log: [], timing: {} };

function init() { bind(); loop(); }
if (document.readyState !== 'loading') init();
else document.addEventListener('DOMContentLoaded', init);
