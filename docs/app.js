/* The cutting room: plays each candidate promo as the script unfolds, lets you trim it to legal cut points,
   and records keep / trim / pass. No framework, no build step. Times are centiseconds (cs) like the data. */
(() => {
'use strict';
const D = window.PROMO_DATA;
const $ = (s, root = document) => root.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const PALETTE = [22, 340, 262, 200, 160, 46];
const PAIR = { 22: 262, 340: 215, 262: 22, 200: 22, 160: 300, 46: 262 };           // each colour's cinematic partner
const partner = h => PAIR[h] ?? (h + 200) % 360;                       // warm orange, rose, violet, blue, teal, gold
const hueOf = s => PALETTE[[...String(s)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7) % PALETTE.length];
const fmt = cs => { const s = Math.max(0, cs) / 100; const m = Math.floor(s / 60); return String(m).padStart(2, '0') + ':' + (s - m * 60).toFixed(2).padStart(5, '0'); };
const rel = cs => (Math.max(0, cs) / 100).toFixed(1).padStart(4, '0');
const ICON = {
  play: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z" fill="currentColor"/></svg>',
  pause: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h3.6v14H7zM13.4 5H17v14h-3.6z" fill="currentColor"/></svg>',
  ok: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  bad: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 6v7M12 17.5v.5" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"/></svg>',
};

/* ---------- saved state ---------- */
const KEY = 'cutting-room:' + D.id;
const read = k => { try { return JSON.parse(localStorage.getItem(k) || '{}'); } catch (e) { return {}; } };
const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private window: keep going without saving */ } };
let saved = read(KEY);                       // { takeId: { d: 'keep'|'trim'|'pass'|null, in, out } }
const ui = Object.assign({ blind: false }, read(KEY + ':ui'));
const persist = () => write(KEY, saved);

/* ---------- order: AI plan order, or a seeded shuffle in blind mode ---------- */
const PLAN_ORDER = ['post_first', 'library', 'hold_back', 'alternate'];
const PLAN_NAME = { post_first: 'Post first', library: 'Library', hold_back: 'Held back for spoilers', alternate: 'Alternates that overlap a stronger promo' };
const PLAN_NOTE = { post_first: 'The strongest cut from each episode, early episodes first.', library: 'Good promos to post after the first wave.', hold_back: 'These show a big twist. Save them for later.', alternate: 'Same moment as a stronger promo. Use only if you want a second version.' };
function seeded(arr, seed) {
  let s = [...String(seed)].reduce((a, c) => (a * 33 + c.charCodeAt(0)) >>> 0, 5381); const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) { s = (s * 1664525 + 1013904223) >>> 0; const j = s % (i + 1); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
let order = [];
function buildOrder() {
  const idx = D.takes.map((_, i) => i);
  order = ui.blind ? seeded(idx, D.id) : PLAN_ORDER.flatMap(p => idx.filter(i => D.takes[i].plan === p));
}
let cur = 0;
const take = () => D.takes[order[cur]];
const win = tk => tk.segments[0];
const trimFor = tk => { const s = saved[tk.id], w = win(tk); return s && s.in != null ? { in: s.in, out: s.out } : { in: w.start, out: w.end }; };
const isTrimmed = tk => { const t = trimFor(tk), w = win(tk); return t.in !== w.start || t.out !== w.end; };

/* ---------- playback state ---------- */
const P = { playing: false, t: 0, speed: 1, last: 0, ended: false, cutTimer: 0, chan: {}, typed: null };

/* ---------- elements ---------- */
const E = {};
['app', 'intro', 'phone', 'screen', 'gateArc', 'shotTag', 'gateTag', 'narr', 'sub', 'subWho', 'subLine', 'sfx', 'cutScreen', 'cutQuestion',
  'peekBtn', 'replayBtn', 'cutPeek', 'playBtn', 'restartBtn', 'clock', 'clockTotal', 'speedBtn', 'theatreBtn', 'timeline', 'timelineHint',
  'feed', 'slate', 'strip', 'progress', 'blindBtn', 'exportBtn', 'helpBtn', 'help', 'toast', 'showTitle', 'rollBtn', 'rollBlindBtn',
  'introTitle', 'introLede', 'introSub', 'promosPage', 'seasonPage', 'qualityPage', 'nav'].forEach(id => { E[id] = document.getElementById(id); });

/* ---------- small helpers over a take's cues ---------- */
const shotWords = t => t.split(/\s+(?:on|of|as|from|showing|following|tracking|toward|towards|between|with|over|past|at|that)\b/i);
function shotParts(text) { const [head, ...rest] = shotWords(text); return { type: head.replace(/[.,]$/, '').slice(0, 38), more: rest.join(' ').slice(0, 96) }; }
const gateCue = (w, tr) => w.cues.find(c => (c.k === 'd' || c.k === 'a') && c.s >= tr.in && c.s < tr.in + 300);
function checks(w, tr) {
  const len = (tr.out - tr.in) / 100, items = [];
  items.push({ ok: len >= 20 && len <= 60, text: len >= 20 && len <= 60 ? `${len.toFixed(1)} seconds, inside the 20 to 60 limit` : `${len.toFixed(1)} seconds, but a promo must run 20 to 60` });
  items.push({ ok: !!gateCue(w, tr), text: gateCue(w, tr) ? 'Something happens in the first 3 seconds' : 'Nothing happens in the first 3 seconds' });
  const fd = w.cues.find(c => c.k === 'd' && c.s >= tr.in);
  const dangling = fd && /^(\.\.\.|…)/.test(fd.text);
  items.push({ ok: !dangling, text: dangling ? 'Opens on a line that continues an earlier sentence' : 'Opens on a complete thought' });
  const dl = w.cues.filter(c => c.k === 'd');
  const before = [...dl].reverse().find(c => c.e <= tr.out), after = dl.find(c => c.s >= tr.out);
  const mid = before && after && before.who === after.who && after.s - before.e <= 150 && /^(\.\.\.|…)/.test(after.text);
  items.push({ ok: !mid, text: mid ? 'Ends before the speaker finishes the sentence' : 'Ends on a finished line, never inside one' });
  return items;
}
const openingText = tk => (tk.ai.opening || '').replace(/^["“]|["”]$/g, '') || (ui.blind ? 'Opens on a camera shot' : tk.ai.hook);
const snap = (cs, edges) => edges.reduce((best, e) => Math.abs(e - cs) < Math.abs(best - cs) ? e : best, edges[0]);
function pulseAt(ep, pos) {
  let g = .12; for (const [p, h, c] of ep.pulse) if (Math.abs(p - pos) < .035) g = Math.max(g, Math.max(h, c) / 3); return g;
}
const epOf = n => D.episodes.find(e => e.n === n);

/* ---------- toast ---------- */
let toastT = 0;
function toast(msg) { E.toast.textContent = msg; E.toast.classList.add('on'); clearTimeout(toastT); toastT = setTimeout(() => E.toast.classList.remove('on'), 2200); }

/* ---------- loading a take ---------- */
function go(i, play) {
  cur = clamp(i, 0, order.length - 1);
  const tk = take(), tr = trimFor(tk);
  P.t = tr.in; P.ended = false; P.chan = {}; stop();
  E.cutScreen.classList.remove('on'); E.cutPeek.hidden = true;
  const h = hueOf(tk.episode);
  E.screen.style.setProperty('--h1', h); E.screen.style.setProperty('--h2', partner(h));
  E.phone.parentElement.parentElement.style.setProperty('--glow-h', h);
  buildTimeline(); renderSlate(); markFeed(); markStrip(); paint();
  E.clockTotal.textContent = '/ ' + ((tr.out - tr.in) / 100).toFixed(1);
  if (play && !reduced) start();
}
function start() {
  if (P.ended) { P.t = trimFor(take()).in; P.ended = false; E.cutScreen.classList.remove('on'); P.chan = {}; }
  P.playing = true; P.last = performance.now(); E.playBtn.innerHTML = ICON.pause; E.playBtn.setAttribute('aria-label', 'Pause');
  requestAnimationFrame(tick);
}
function stop() { P.playing = false; E.playBtn.innerHTML = ICON.play; E.playBtn.setAttribute('aria-label', 'Play'); clearTimeout(P.cutTimer); }
function tick(now) {
  if (!P.playing) return;
  const tr = trimFor(take());
  P.t += (now - P.last) / 10 * P.speed; P.last = now;
  if (P.t >= tr.out) { P.t = tr.out; endClip(); return; }
  paint(); requestAnimationFrame(tick);
}
function endClip() {
  stop(); P.ended = true; paint();
  const tk = take();
  E.cutQuestion.textContent = ui.blind ? 'What do you need to know next?' : (tk.ai.cliff || 'What happens next?');
  clearTimeout(P.cutTimer);
  P.cutTimer = setTimeout(() => { if (P.ended) E.cutScreen.classList.add('on'); }, reduced ? 0 : 750);
}

/* ---------- painting the reel ---------- */
function paint() {
  const tk = take(), w = win(tk), tr = trimFor(tk), t = P.t;
  const active = k => { let b = null; for (const c of w.cues) if (c.k === k && c.s <= t && t < c.e && (!b || c.s >= b.s)) b = c; return b; };
  const cam = active('c'), act = active('a'), dia = active('d'), sfx = active('s');

  if ((cam && cam.id) !== P.chan.cam) {
    P.chan.cam = cam && cam.id;
    if (cam) { const s = shotParts(cam.text); E.shotTag.innerHTML = `<b>${esc(s.type)}</b><small>${esc(s.more)}</small>`; } else E.shotTag.innerHTML = '';
  }
  if ((act && act.id) !== P.chan.act) { P.chan.act = act && act.id; E.narr.textContent = act ? act.text.slice(0, 160) : ''; E.narr.classList.toggle('on', !!act); }
  if ((sfx && sfx.id) !== P.chan.sfx) { P.chan.sfx = sfx && sfx.id; E.sfx.textContent = sfx ? sfx.text.slice(0, 80) : ''; E.sfx.classList.toggle('on', !!sfx); }
  if ((dia && dia.id) !== P.chan.dia) {
    P.chan.dia = dia && dia.id; P.typed = null;
    if (dia) {
      E.subWho.textContent = dia.who;
      E.subWho.style.setProperty('--sh', hueOf(dia.who));
      E.subLine.innerHTML = dia.text.split(/\s+/).map(x => `<span class="w">${esc(x)}</span>`).join(' ');
      P.typed = [...E.subLine.querySelectorAll('.w')];
      const h = hueOf(dia.who);
      E.screen.style.setProperty('--h1', h); E.screen.style.setProperty('--h2', partner(h));
      E.phone.parentElement.parentElement.style.setProperty('--glow-h', h);
    } else { E.subWho.textContent = ''; E.subLine.innerHTML = ''; }
  }
  if (dia && P.typed) {
    const span = Math.max(60, (dia.e - dia.s) * .82), n = reduced ? P.typed.length : Math.ceil(P.typed.length * clamp((t - dia.s) / span, 0, 1));
    P.typed.forEach((el, i) => { el.classList.toggle('on', i < n); el.classList.toggle('now', i === n - 1 && n < P.typed.length); });
  }
  E.screen.style.setProperty('--glow', (ui.blind ? .3 : pulseAt(epOf(w.episode), t / w.duration)).toFixed(2));   // the glow follows the AI's scores, so blind mode holds it steady

  // the 3-second gate
  const gp = clamp((t - tr.in) / 300, 0, 1), ok = !!gateCue(w, tr);
  E.gateArc.style.strokeDasharray = `${(P.ended || gp >= 1 ? (ok ? 100 : 0) : gp * 100).toFixed(1)} 100`;
  E.gateTag.className = 'hud-gate' + (gp >= 1 ? (ok ? ' cleared' : ' quiet') : '');
  E.gateTag.textContent = gp >= 1 ? (ok ? 'Gate cleared' : 'Quiet start') : '3-second gate';

  E.clock.textContent = rel(t - tr.in);
  movePlayhead();
}

/* ---------- timeline: vertical, time runs down beside the reel ---------- */
let TL = null;
function buildTimeline() {
  const tk = take(), w = win(tk), span = w.hi - w.lo, tl = E.timeline;
  const pct = cs => ((cs - w.lo) / span * 100).toFixed(3) + '%';
  const col = (k, cls) => `<div class="tl-col ${k}">` + w.cues.filter(c => c.k === k).map(c => {
    const a = Math.max(c.s, w.lo), z = Math.min(c.e, w.hi);
    return `<i class="tl-cue ${cls}" style="top:${pct(a)};height:${((z - a) / span * 100).toFixed(3)}%" title="${esc((c.who ? c.who + ': ' : '') + c.text)}"></i>`;
  }).join('') + '</div>';
  let h = '';
  for (let s = Math.ceil(w.lo / 1000) * 1000; s < w.hi; s += 1000) h += `<span class="tl-tick" style="top:${pct(s)}">${fmt(s).slice(0, 5)}</span>`;
  h += '<div class="tl-shade" id="shT"></div><div class="tl-shade" id="shB"></div><div class="tl-gate" id="tlGate"></div><div class="tl-band" id="tlBand"></div>';
  h += col('d', 'd') + col('a', 'a') + col('c', 'c');
  h += '<div class="tl-col e">' + w.edges.map(e => `<i class="tl-edge" style="top:${pct(e)}"></i>`).join('') + '</div>';
  h += '<button class="tl-handle in" id="hIn" role="slider" aria-label="In point" data-label="In"></button><button class="tl-handle out" id="hOut" role="slider" aria-label="Out point" data-label="Out"></button>';
  h += '<div class="tl-head" id="tlHead"></div><span class="tl-readout" id="tlRead"></span>';
  tl.innerHTML = h;
  TL = { w, pct, span, head: $('#tlHead', tl), read: $('#tlRead', tl), hIn: $('#hIn', tl), hOut: $('#hOut', tl), band: $('#tlBand', tl),
    gate: $('#tlGate', tl), shT: $('#shT', tl), shB: $('#shB', tl) };
  bindTimeline(); layoutTimeline();
}
function layoutTimeline() {
  const tk = take(), tr = trimFor(tk), { w, pct, span } = TL, L = cs => (cs - w.lo) / span * 100;
  TL.hIn.style.top = pct(tr.in); TL.hOut.style.top = pct(tr.out);
  TL.hIn.setAttribute('aria-valuenow', rel(tr.in)); TL.hOut.setAttribute('aria-valuenow', rel(tr.out));
  Object.assign(TL.band.style, { top: pct(tr.in), height: (L(tr.out) - L(tr.in)) + '%' });
  Object.assign(TL.gate.style, { top: pct(tr.in), height: (300 / span * 100) + '%' });
  Object.assign(TL.shT.style, { top: '0', height: L(tr.in) + '%' });
  Object.assign(TL.shB.style, { top: pct(tr.out), height: (100 - L(tr.out)) + '%' });
}
function movePlayhead() {
  if (!TL) return;
  const y = clamp((P.t - TL.w.lo) / TL.span * 100, 0, 100) + '%';
  TL.head.style.top = y; TL.read.style.top = y; TL.read.textContent = fmt(P.t).slice(3);
}
function bindTimeline() {
  const tl = E.timeline;
  const csAt = ev => { const r = tl.getBoundingClientRect(); return TL.w.lo + clamp((ev.clientY - r.top) / r.height, 0, 1) * TL.span; };
  const move = (which, cs) => {
    const tk = take(), tr = { ...trimFor(tk) }, s = snap(cs, TL.w.edges);
    if (which === 'in') tr.in = Math.min(s, tr.out - 500); else tr.out = Math.max(s, tr.in + 500);
    setTrim(tk, tr, which);
  };
  [['in', TL.hIn], ['out', TL.hOut]].forEach(([which, el]) => {
    el.addEventListener('pointerdown', ev => { ev.stopPropagation(); el.setPointerCapture(ev.pointerId); el.classList.add('drag'); stop(); });
    el.addEventListener('pointermove', ev => { if (el.classList.contains('drag')) move(which, csAt(ev)); });
    el.addEventListener('pointerup', () => { el.classList.remove('drag'); renderSlate(); });
    el.addEventListener('keydown', ev => {
      if (ev.key !== 'ArrowUp' && ev.key !== 'ArrowDown') return;
      ev.preventDefault();
      const tr = trimFor(take()), at = which === 'in' ? tr.in : tr.out, edges = TL.w.edges;
      const i = edges.indexOf(at), next = edges[clamp(i + (ev.key === 'ArrowDown' ? 1 : -1), 0, edges.length - 1)];
      move(which, next); renderSlate();
    });
  });
  let scrub = false;
  const seek = ev => { const tr = trimFor(take()); P.t = clamp(csAt(ev), tr.in, tr.out); P.ended = false; E.cutScreen.classList.remove('on'); paint(); };
  tl.addEventListener('pointerdown', ev => { if (ev.target.closest('.tl-handle')) return; scrub = true; tl.setPointerCapture(ev.pointerId); stop(); seek(ev); });
  tl.addEventListener('pointermove', ev => { if (scrub) seek(ev); });
  tl.addEventListener('pointerup', () => { scrub = false; });
}
function setTrim(tk, tr, which) {
  const s = saved[tk.id] || { d: null };
  saved[tk.id] = { d: s.d, in: tr.in, out: tr.out }; persist();
  // show the result of the edit: the new opening for an In change, the last lines before the cut for an Out change
  P.t = which === 'in' ? tr.in + 40 : which === 'out' ? Math.max(tr.in, tr.out - 30) : clamp(P.t, tr.in, tr.out);
  P.ended = false; P.chan = {}; E.cutScreen.classList.remove('on');
  layoutTimeline(); paint();
  E.clockTotal.textContent = '/ ' + ((tr.out - tr.in) / 100).toFixed(1);
  const items = checks(win(tk), tr), len = $('.len', E.slate);
  if (len) { len.className = 'len ' + (items[0].ok ? 'ok' : 'bad'); len.querySelector('b').textContent = ((tr.out - tr.in) / 100).toFixed(1) + ' s'; }
  const inB = $('#tIn', E.slate), outB = $('#tOut', E.slate);
  if (inB) { inB.textContent = fmt(tr.in); outB.textContent = fmt(tr.out); }
}

/* ---------- slate (verdict panel) ---------- */
function renderSlate() {
  const tk = take(), w = win(tk), tr = trimFor(tk), len = (tr.out - tr.in) / 100, items = checks(w, tr), s = saved[tk.id] || {};
  const verdict = (d, label, key) => `<button class="verdict ${d} ${s.d === d ? 'on' : ''}" data-d="${d}" aria-pressed="${s.d === d}">${label}<kbd>${key}</kbd></button>`;
  const lastLines = w.cues.filter(c => (c.k === 'd' || c.k === 'a') && c.e <= tr.out && c.e > tr.out - 700).slice(-2).map(c => (c.who ? c.who + ': ' : '') + c.text);
  const v = tk.ai.viewer || {};
  const chip = (txt, cls) => txt ? `<span class="tag ${cls}">${esc(txt)}</span>` : '';
  const nth = cur + 1;
  let html = `<div class="slate-card"><div class="clap"></div>
    <div class="slate-head"><div><small>Episode</small><b>${tk.episode}</b></div><div><small>${ui.blind ? 'Promo' : 'Rank'}</small><b>${ui.blind ? nth : tk.rank}</b></div><div><small>${ui.blind ? 'Of' : 'Post'}</small><b>${ui.blind ? order.length : esc(({ post_first: 'First', library: 'Library', hold_back: 'Held', alternate: 'Alt' })[tk.plan] || '')}</b></div></div>
    <div class="times"><div><small>In</small><b id="tIn">${fmt(tr.in)}</b></div><div><small>Out</small><b id="tOut">${fmt(tr.out)}</b></div><div class="len ${items[0].ok ? 'ok' : 'bad'}"><small>Length</small><b>${len.toFixed(1)} s</b></div></div>
    <div class="times-foot"><span>${isTrimmed(tk) ? 'You moved the cut points.' : 'Original cut from the tool.'}</span>${isTrimmed(tk) ? '<button class="link-btn" id="resetTrim" type="button">Reset to original</button>' : ''}</div>
    <ul class="rules">${items.map(i => `<li class="${i.ok ? 'ok' : 'bad'}">${i.ok ? ICON.ok : ICON.bad}<span>${esc(i.text)}</span></li>`).join('')}</ul></div>
    <div class="verdicts">${verdict('keep', 'Keep', 'K')}${verdict('trim', 'Trim', 'T')}${verdict('pass', 'Pass', 'P')}</div>
    <div class="slate-card">
      <div class="slate-sec"><h2>What opens it</h2><p class="quote">${esc(openingText(tk))}</p></div>
      <div class="slate-sec"><h2>Where it ends</h2>${lastLines.map(l => `<p class="quote">${esc(l)}</p>`).join('') || '<p class="muted">The last lines before the cut.</p>'}</div>`;
  if (ui.blind) {
    html += `<div class="blind-note"><b>AI hints are hidden.</b> The tool's ranking, summaries and verdicts are off and the promos are shuffled. Rate what you see.</div></div>`;
  } else {
    html += `<div class="slate-sec"><h2>Why the tool picked it</h2>
        <p class="quote"><em>Hook</em>${esc(tk.ai.hook)}</p><p class="quote"><em>Left hanging</em>${esc(tk.ai.cliff)}</p>
        ${tk.ai.why ? `<p class="muted" style="margin-top:8px">${esc(tk.ai.why)}</p>` : ''}
        <div class="tags">${chip(tk.ai.hookType, '')}${chip(tk.ai.spoiler !== 'none' ? tk.ai.spoiler + ' spoiler' : '', 'warn')}${chip(tk.source === 'rules' ? 'No-AI baseline' : 'AI scored', '')}</div></div>
      ${v.who ? `<div class="slate-sec"><h2>What a stranger understood</h2><p class="quote">${esc(v.who)} ${esc(v.situation)}</p>
        <p class="quote"><em>Wondering</em>${esc(v.open_question)}</p>
        <div class="tags">${chip('First 3 s: ' + v.first_3s.replace('_', ' '), v.first_3s === 'stop' ? 'good' : 'warn')}${chip('Clear: ' + v.makes_sense, v.makes_sense === 'yes' ? 'good' : 'warn')}${chip('Ending: ' + v.ending, v.ending === 'unresolved' ? 'good' : 'warn')}</div>
        ${v.confusing && v.confusing !== 'nothing' ? `<p class="muted" style="margin-top:8px">Confusing: ${esc(v.confusing)}</p>` : ''}</div>` : ''}
      <div class="slate-sec"><p class="muted">${esc(tk.ai.planReason || '')}</p></div></div>`;
  }
  E.slate.innerHTML = html;
  E.slate.querySelectorAll('.verdict').forEach(b => b.addEventListener('click', () => decide(b.dataset.d)));
  const r = $('#resetTrim', E.slate); if (r) r.addEventListener('click', () => { const w2 = win(take()); setTrim(take(), { in: w2.start, out: w2.end }, 'in'); renderSlate(); });
}
function decide(d) {
  const tk = take(), tr = trimFor(tk);
  saved[tk.id] = { d, in: tr.in, out: tr.out }; persist();
  renderSlate(); markFeed(); renderProgress();
  const left = D.takes.filter(t => !(saved[t.id] && saved[t.id].d)).length;
  toast(left ? `${d[0].toUpperCase() + d.slice(1)} saved. ${left} to go.` : 'All promos rated. Export your ratings when you are ready.');
  if (cur < order.length - 1) setTimeout(() => go(cur + 1, true), 420);
}

/* ---------- feed, strip, progress ---------- */
function renderFeed() {
  let html = '', last = null;
  order.forEach((di, i) => {
    const tk = D.takes[di], group = ui.blind ? 'blind' : tk.plan;
    if (group !== last) {
      last = group;
      const n = ui.blind ? order.length : D.takes.filter(t => t.plan === tk.plan).length;
      html += `<div class="rail-title"><h2>${ui.blind ? 'Promos in random order' : PLAN_NAME[tk.plan]}</h2><span>${n}</span></div>`;
      if (!ui.blind && PLAN_NOTE[tk.plan]) html += `<p class="rail-note">${PLAN_NOTE[tk.plan]}</p>`;
    }
    html += `<button class="take" data-i="${i}" style="--h:${hueOf(tk.episode)}" aria-label="Promo ${ui.blind ? i + 1 : tk.rank}, episode ${tk.episode}">
      <span class="poster"><b>${tk.episode}</b><i>${Math.round((trimFor(tk).out - trimFor(tk).in) / 100)} s</i></span>
      <span><span class="open">${esc(openingText(tk))}</span><span class="sub">Episode ${tk.episode}${ui.blind ? '' : ', rank ' + tk.rank}</span></span>
      <span class="verdict-dot"></span></button>`;
  });
  E.feed.innerHTML = html;
  E.feed.querySelectorAll('.take').forEach(b => b.addEventListener('click', () => go(+b.dataset.i, true)));
  markFeed();
}
function markFeed() {
  E.feed.querySelectorAll('.take').forEach(b => {
    const i = +b.dataset.i, tk = D.takes[order[i]], s = saved[tk.id];
    b.classList.toggle('on', i === cur);
    const dot = b.querySelector('.verdict-dot'); dot.className = 'verdict-dot' + (s && s.d ? ' ' + s.d : '');
    b.querySelector('.poster i').textContent = Math.round((trimFor(tk).out - trimFor(tk).in) / 100) + ' s';
  });
  // scroll only inside the feed (never the page): on small screens the feed sits below the player and must not pull the page down
  const on = E.feed.querySelector('.take.on'), f = E.feed;
  if (on && f.scrollHeight > f.clientHeight + 4) f.scrollTo({ top: on.offsetTop - f.clientHeight / 3, behavior: reduced ? 'auto' : 'smooth' });
}
function renderStrip() {
  E.strip.innerHTML = D.episodes.map(ep => {
    const bars = ep.pulse.map(([p, h, c]) => { const x = (p * 46 + 1).toFixed(1), top = 27 - Math.max(h, c) * 8.2;
      return `<line x1="${x}" x2="${x}" y1="27" y2="${top.toFixed(1)}" stroke="${h >= c ? '#ff641c' : '#f8c543'}" stroke-width="1.6" stroke-linecap="round"/>`; }).join('');
    const has = ep.takes.length > 0;
    return `<button class="tile ${has ? 'has' : ''} ${ep.scored ? '' : 'dim'}" data-ep="${ep.n}" title="${has ? `Episode ${ep.n}: ${ep.takes.length} take${ep.takes.length > 1 ? 's' : ''}` : ep.scored ? `Episode ${ep.n}: scored, no take passed` : `Episode ${ep.n}: not scored in this run`}">
      <b>${ep.n}</b><svg class="pulse" viewBox="0 0 48 28" aria-hidden="true"><line x1="1" x2="47" y1="27" y2="27" stroke="rgba(255,255,255,.14)"/>${bars}</svg>${has ? `<span class="count">${ep.takes.length}</span>` : ''}</button>`;
  }).join('');
  E.strip.querySelectorAll('.tile').forEach(t => t.addEventListener('click', () => {
    const n = +t.dataset.ep, i = order.findIndex(di => D.takes[di].episode === n);
    if (i >= 0) go(i, true); else toast(`No promo for episode ${n} in this run.`);
  }));
}
function markStrip() {
  const n = take().episode;
  E.strip.querySelectorAll('.tile').forEach(t => t.classList.toggle('on', +t.dataset.ep === n));
  const on = E.strip.querySelector('.tile.on'), s = E.strip;
  if (on) s.scrollTo({ left: on.offsetLeft - s.clientWidth / 2 + on.clientWidth / 2, behavior: reduced ? 'auto' : 'smooth' });
}
function renderProgress() {
  const done = D.takes.filter(t => saved[t.id] && saved[t.id].d).length, total = D.takes.length, c = 2 * Math.PI * 14;
  E.progress.innerHTML = `<svg viewBox="0 0 34 34" aria-hidden="true"><circle class="p-track" cx="17" cy="17" r="14"/><circle class="p-fill" cx="17" cy="17" r="14" stroke-dasharray="${(done / total * c).toFixed(1)} ${c.toFixed(1)}"/></svg><span>${done} of ${total} rated</span>`;
}

/* ---------- export ---------- */
function exportCsv() {
  const rows = [['rank', 'id', 'episode', 'segments_in_order', 'decision', 'suggested_in', 'suggested_out', 'reviewer']];
  D.takes.forEach(tk => {
    const s = saved[tk.id]; if (!s || !s.d) return;
    const w = win(tk), changed = s.in !== w.start || s.out !== w.end;
    rows.push([tk.rank, tk.id, tk.episode, tk.key, s.d, s.d === 'trim' && changed ? fmt(s.in) : '', s.d === 'trim' && changed ? fmt(s.out) : '', 'Cutting room' + (ui.blind ? ' (AI hints hidden)' : '')]);
  });
  if (rows.length === 1) { toast('Rate at least one promo first.'); return; }
  const cell = v => { let t = String(v); if (/^[=+\-@\t\r]/.test(t)) t = "'" + t; return '"' + t.replace(/"/g, '""') + '"'; };
  const blob = new Blob([rows.map(r => r.map(cell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `cutting-room-${D.id}${ui.blind ? '-blind' : ''}.csv`;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  toast(`Exported ${rows.length - 1} ratings.`);
}

/* ---------- blind mode ---------- */
function setBlind(on) {
  ui.blind = on; write(KEY + ':ui', ui); E.app.classList.toggle('blind', on);
  E.blindBtn.setAttribute('aria-pressed', on);
  const keepId = take().id; buildOrder(); cur = Math.max(0, order.findIndex(di => D.takes[di].id === keepId));
  renderFeed(); go(cur, false);
  toast(on ? 'AI hints hidden. Promos are shuffled.' : 'AI hints are back.');
}

/* ---------- wiring ---------- */
function wire() {
  E.playBtn.addEventListener('click', () => P.playing ? stop() : start());
  E.restartBtn.addEventListener('click', () => { P.t = trimFor(take()).in; P.ended = false; E.cutScreen.classList.remove('on'); P.chan = {}; paint(); start(); });
  E.replayBtn.addEventListener('click', () => E.restartBtn.click());
  E.peekBtn.addEventListener('click', () => { const tk = take(); E.cutPeek.hidden = false; E.cutPeek.textContent = tk.next ? tk.next : 'The script has nothing more in this episode.'; });
  E.speedBtn.addEventListener('click', () => { P.speed = P.speed === 1 ? 2 : P.speed === 2 ? 4 : 1; E.speedBtn.textContent = P.speed + 'x'; });
  E.theatreBtn.addEventListener('click', () => { const on = E.app.classList.toggle('theatre'); E.theatreBtn.setAttribute('aria-pressed', on); });
  E.blindBtn.addEventListener('click', () => setBlind(!ui.blind));
  E.exportBtn.addEventListener('click', exportCsv);
  E.helpBtn.addEventListener('click', () => E.help.showModal());
  document.addEventListener('keydown', ev => {
    if (E.help.open || ev.metaKey || ev.ctrlKey || ev.altKey || !E.intro.classList.contains('gone')) return;
    if (view === 'promos') { const k0 = ev.key; if (k0 === 'ArrowRight' || k0 === 'ArrowDown') { ev.preventDefault(); stepPromo(1); } else if (k0 === 'ArrowLeft' || k0 === 'ArrowUp') { ev.preventDefault(); stepPromo(-1); } return; }
    if (view !== 'review') return;
    if (ev.target.closest && ev.target.closest('.tl-handle') && (ev.key === 'ArrowUp' || ev.key === 'ArrowDown')) return;
    const k = ev.key.toLowerCase();
    if (k === ' ' ) { ev.preventDefault(); P.playing ? stop() : start(); }
    else if (k === 'arrowright') go(cur + 1, true);
    else if (k === 'arrowleft') go(cur - 1, true);
    else if (k === 'k') decide('keep'); else if (k === 't') decide('trim'); else if (k === 'p') decide('pass');
    else if (k === 'r') E.restartBtn.click();
    else if (k === 'b') setBlind(!ui.blind);
    else if (k === 'f') E.theatreBtn.click();
    else if (k === 'escape') { E.app.classList.remove('theatre'); E.theatreBtn.setAttribute('aria-pressed', false); }
    else if (k === '[' || k === ']') {
      const tk = take(), tr = { ...trimFor(tk) }, s = snap(P.t, win(tk).edges);
      if (k === '[') tr.in = Math.min(s, tr.out - 500); else tr.out = Math.max(s, tr.in + 500);
      setTrim(tk, tr, k === '[' ? 'in' : 'out'); renderSlate();
    }
  });
}

/* ---------- pages ---------- */
const VIEWS = ['promos', 'review', 'season', 'quality', 'new'];
let view = 'promos';
const segText = tk => {
  const t = trimFor(tk);
  return tk.segments.map((sg, i) => `Ep ${sg.episode} ${fmt(i === 0 ? t.in : sg.start)} to ${fmt(i === 0 ? t.out : sg.end)}`).join(' + ');
};
const durOf = tk => { const t = trimFor(tk); return ((t.out - t.in) + tk.segments.slice(1).reduce((a, g) => a + (g.end - g.start), 0)) / 100; };
const pct = (n, d) => d ? Math.round(n / d * 100) + '%' : 'n/a';
const pulseSvg = ep => {
  const bars = ep.pulse.map(([p, h, c]) => { const x = (p * 46 + 1).toFixed(1), top = 27 - Math.max(h, c) * 8.2;
    return `<line x1="${x}" x2="${x}" y1="27" y2="${top.toFixed(1)}" stroke="${h >= c ? '#ff641c' : '#f8c543'}" stroke-width="1.6" stroke-linecap="round"/>`; }).join('');
  return `<svg class="pulse" viewBox="0 0 48 28" aria-hidden="true"><line x1="1" x2="47" y1="27" y2="27" stroke="rgba(255,255,255,.14)"/>${bars}</svg>`;
};

let selPromo = null;
function renderPromos() {
  const n = D.takes.length, eps = new Set(D.takes.map(t => t.episode)).size;
  const sorted = D.takes.slice().sort((a, b) => a.rank - b.rank);
  if (!selPromo || !D.takes.some(t => t.id === selPromo)) selPromo = sorted[0] && sorted[0].id;
  const groups = PLAN_ORDER.map(g => ({ g, list: D.takes.filter(t => t.plan === g).sort((a, b) => a.rank - b.rank) })).filter(x => x.list.length);
  const poster = tk => {
    const h = hueOf(tk.episode), s = saved[tk.id], q = (tk.ai.hook || '').replace(/^["“]|["”]$/g, '');
    return `<button class="poster-card ${tk.id === selPromo ? 'on' : ''}" data-sel="${esc(tk.id)}" type="button" style="--h:${h};--h2:${partner(h)}" aria-label="Rank ${tk.rank}, episode ${tk.episode}, ${esc(q)}">
      <span class="pc-top"><b>${tk.rank}</b><span>Ep ${tk.episode}</span><span class="pc-len">${durOf(tk).toFixed(0)} s</span></span>
      <span class="pc-hook">${esc(q)}</span>
      <span class="pc-cut" aria-hidden="true"></span>
      <span class="pc-end"><small>Ends on</small>${esc(tk.ai.cliff || '')}</span>
      ${s && s.d ? `<i class="pc-dot ${s.d}" title="You said ${s.d}"></i>` : ''}
    </button>`;
  };
  E.promosPage.innerHTML = `
    <div class="promos-wide">
      <header class="page-head">
        <h1>${n} promos found in ${eps} of ${D.show.episodes} episodes</h1>
        <p class="lede">Each poster is one promo: the lit top is its hook, the dimmed bottom is where the clip cuts off. Pick one to see its times and why it works.</p>
        <div class="head-actions"><button class="pill primary" id="dlCsv" type="button">Download results (CSV)</button><button class="pill" id="dlJson" type="button">Download results (JSON)</button></div>
        <details class="how"><summary>How the order was decided</summary>
          <ul>
            <li><b>The strongest from each episode goes first</b>, earliest episodes first, because a new viewer lands on episode 1.</li>
            <li><b>Clips a stranger could not follow are dropped</b>: an AI that sees only the clip must say what is happening and what it is waiting for.</li>
            <li><b>Big twists are held back</b> so a promo does not spoil the show.</li>
            <li><b>Overlapping cuts become alternates</b> instead of repeating the same moment twice.</li>
          </ul></details>
      </header>
      <div class="deck-layout">
        <div class="deck">${groups.map(({ g, list }) => `<section class="deck-group"><div class="rail-title"><h2>${PLAN_NAME[g]}</h2><span>${list.length}</span></div><p class="rail-note">${PLAN_NOTE[g]}</p><div class="poster-grid">${list.map(poster).join('')}</div></section>`).join('')}</div>
        <aside class="ticket" id="ticket" aria-live="polite"></aside>
      </div>
    </div>`;
  E.promosPage.querySelectorAll('[data-sel]').forEach(b => b.addEventListener('click', () => pickPromo(b.dataset.sel, true)));
  $('#dlCsv', E.promosPage).addEventListener('click', () => downloadResults('csv'));
  $('#dlJson', E.promosPage).addEventListener('click', () => downloadResults('json'));
  renderTicket();
}
function pickPromo(id, open) {
  selPromo = id;
  E.promosPage.querySelectorAll('.poster-card').forEach(b => b.classList.toggle('on', b.dataset.sel === id));
  renderTicket();
  if (open) $('#ticket').classList.add('open');
}
function renderTicket() {
  const tk = D.takes.find(t => t.id === selPromo), el = $('#ticket'); if (!tk || !el) return;
  const s = saved[tk.id], t = trimFor(tk), edited = isTrimmed(tk);
  const sorted = D.takes.slice().sort((a, b) => a.rank - b.rank), i = sorted.indexOf(tk);
  const seg = tk.segments.map((sg, k) => `<li><span class="seg-n">${tk.segments.length > 1 ? 'Segment ' + (k + 1) : 'Clip'}</span><b>Ep ${sg.episode}</b><span class="tc">${fmt(k === 0 ? t.in : sg.start)}</span><span class="arrow">to</span><span class="tc">${fmt(k === 0 ? t.out : sg.end)}</span></li>`).join('');
  const plain = `Ep ${tk.episode}: ${segText(tk)}. Hook: ${tk.ai.hook} Cliffhanger: ${tk.ai.cliff} Why: ${tk.ai.why || ''}`;
  el.innerHTML = `<button class="sheet-close icon-btn" id="tkClose" type="button" aria-label="Close details">&times;</button>
    <div class="tk-head"><span class="tk-rank">${tk.rank}</span><div><p class="tk-eyebrow">${esc(PLAN_NAME[tk.plan])}</p><h2>Episode ${tk.episode}, ${durOf(tk).toFixed(1)} seconds</h2></div></div>
    <ul class="segs">${seg}</ul>
    <p class="tk-note">${tk.segments.length > 1 ? 'Play the segments in this order.' : 'One continuous stretch.'}${edited ? ' <span class="tag warn">you moved the cut</span>' : ''}${s && s.d ? ` <span class="tag ${s.d === 'keep' ? 'good' : s.d === 'trim' ? 'warn' : 'bad'}">you said ${s.d}</span>` : ''}</p>
    <dl class="tk-facts">
      <div><dt>Hook${tk.ai.hookType ? ` <small>${esc(tk.ai.hookType.replace(/_/g, ' '))}</small>` : ''}</dt><dd>${esc(tk.ai.hook)}</dd></div>
      <div><dt>Cliffhanger</dt><dd>${esc(tk.ai.cliff)}</dd></div>
      <div><dt>Why it works</dt><dd>${esc(tk.ai.why || 'No summary was written for this cut.')}</dd></div>
      <div><dt>Why this slot</dt><dd>${esc(tk.ai.planReason || PLAN_NOTE[tk.plan] || '')}${tk.ai.spoiler && tk.ai.spoiler !== 'none' ? ` <span class="tag warn">${esc(tk.ai.spoiler)} spoiler</span>` : ''}</dd></div>
    </dl>
    <div class="tk-actions"><button class="pill primary" id="tkWatch" type="button">Watch and trim</button><button class="pill" id="tkCopy" type="button">Copy for the editor</button></div>
    <div class="tk-nav"><button class="chip" id="tkPrev" type="button" ${i === 0 ? 'disabled' : ''}>Previous</button><span>${i + 1} of ${sorted.length}</span><button class="chip" id="tkNext" type="button" ${i === sorted.length - 1 ? 'disabled' : ''}>Next</button></div>`;
  $('#tkWatch', el).addEventListener('click', () => openTake(tk.id));
  $('#tkCopy', el).addEventListener('click', () => { (navigator.clipboard ? navigator.clipboard.writeText(plain) : Promise.reject()).then(() => toast('Copied.'), () => toast('Copy is blocked here. Use Download results instead.')); });
  $('#tkClose', el).addEventListener('click', () => el.classList.remove('open'));
  $('#tkPrev', el).addEventListener('click', () => stepPromo(-1)); $('#tkNext', el).addEventListener('click', () => stepPromo(1));
}
function stepPromo(d) {
  const sorted = D.takes.slice().sort((a, b) => a.rank - b.rank), i = sorted.findIndex(t => t.id === selPromo), nx = sorted[clamp(i + d, 0, sorted.length - 1)];
  if (nx) { pickPromo(nx.id, $('#ticket').classList.contains('open')); const c = E.promosPage.querySelector('.poster-card.on'); if (c) c.scrollIntoView({ block: 'nearest', behavior: reduced ? 'auto' : 'smooth' }); }
}

function renderSeason() {
  const covered = D.episodes.filter(e => e.takes.length).length;
  E.seasonPage.innerHTML = `
    <header class="page-head"><h1>Every episode at a glance</h1>
      <p class="lede">${covered} of ${D.show.episodes} episodes have a promo. The small line under each episode shows where the AI saw a good place to open a clip (orange) or end one (gold); taller means stronger.</p></header>
    <div class="season-grid">${D.episodes.map(ep => `<button class="season-tile ${ep.takes.length ? 'has' : ''}" data-ep="${ep.n}" type="button">
      <b>Episode ${ep.n}</b>${ep.scored ? pulseSvg(ep) : '<span class="muted">Not scored in this run</span>'}
      <span class="logline">${esc(ep.logline || '')}</span>
      <span class="season-foot">${ep.takes.length ? `<span class="tag good">${ep.takes.length} promo${ep.takes.length > 1 ? 's' : ''}</span>` : ep.scored ? '<span class="tag warn">scored, no promo passed</span>' : '<span class="tag">not run</span>'}</span></button>`).join('')}</div>`;
  E.seasonPage.querySelectorAll('.season-tile').forEach(b => b.addEventListener('click', () => {
    const t = D.takes.find(x => x.episode === +b.dataset.ep);
    if (t) openTake(t.id); else toast(`No promo for episode ${b.dataset.ep} in this run.`);
  }));
}

function renderQuality() {
  const q = D.quality || {}, w = q.writer || {}, v = q.viewer || {}, j = q.judge || {}, rej = Object.entries(q.rejections || {});
  const rows = Object.values(saved).filter(x => x && x.d), keptTop = D.takes.filter(t => t.plan === 'post_first' && saved[t.id] && saved[t.id].d);
  const kept = a => a.filter(t => saved[t.id].d !== 'pass').length;
  const bars = rej.map(([k, c]) => `<li><span>${esc(k)}</span><i style="--w:${(c / Math.max(...rej.map(r => r[1])) * 100).toFixed(0)}%"></i><b>${c}</b></li>`).join('');
  const kind = r => r.kind === 'human' ? 'Human reviewer' : 'Second AI (not a person)';
  const slotBias = j.average_place_by_slot ? Math.max(...Object.values(j.average_place_by_slot)) - Math.min(...Object.values(j.average_place_by_slot)) : null;
  E.qualityPage.innerHTML = `
    <header class="page-head"><h1>Where the tool picks badly</h1>
      <p class="lede">Measured on this run, not promised. Each check says what it tests, what the number is, and what it cannot prove.</p></header>
    <div class="cards2">
      <article class="card stat"><h2>Hard rules</h2><p class="big ${q.violations ? 'bad' : 'good'}">${q.violations ?? 'n/a'} broken</p>
        <p class="muted">Across ${q.promos ?? D.takes.length} promos: 20 to 60 seconds, something in the first 3 seconds, no cut through a spoken line, no opening on a half-sentence. Code re-checks every promo, so this should be zero. <b>Cannot prove</b> the promo is good, only that it is legal.</p></article>
      <article class="card stat"><h2>Does it find the writers' own cliffhangers?</h2><p class="big">${w.labels ? `${w.hit_last_10s} of ${w.labels}` : 'n/a'}</p>
        <p class="muted">The scripts' continuity notes flag some episode-ending cliffhangers. This counts promos that end within 10 seconds of one. <b>Cannot prove</b> a viewer would stop scrolling.</p></article>
      <article class="card stat"><h2>Does a stranger follow it?</h2><p class="big">${v.ai ? pct(v.ai.passed, v.ai.viewed) : 'n/a'}</p>
        <p class="muted">${v.ai ? `An AI that sees only the clip passed ${v.ai.passed} of ${v.ai.viewed} AI-picked cuts` : ''}${v.rules && v.rules.viewed ? ` and ${v.rules.passed} of ${v.rules.viewed} cuts from a plain no-AI baseline` : ''}. <b>Cannot prove</b> the AI judge is right; it is another model.</p></article>
      <article class="card stat"><h2>Is the ranking judge steady?</h2><p class="big">${j.repeat_pair_agreement != null ? Math.round(j.repeat_pair_agreement * 100) + '%' : 'n/a'}</p>
        <p class="muted">When the same pair was compared twice in different positions, the judge agreed with itself this often${slotBias != null ? `; position bias spread ${slotBias.toFixed(2)} (0 means none)` : ''}. <b>Cannot prove</b> the order matches an editor's taste.</p></article>
    </div>
    <section class="card wide"><h2>What it threw away, and why</h2>
      ${rej.length ? `<ul class="bars">${bars}</ul><p class="muted">Every rejected cut is kept in <code>rejected.json</code> so a person can overrule the tool.</p>` : '<p class="muted">Nothing was rejected in this run.</p>'}
      <p class="muted">Coverage: ${q.coverage && q.coverage.episodes ? `${q.coverage.episodes_with_a_promo} of ${q.coverage.episodes} scored episodes have a promo.` : 'n/a'}</p></section>
    <section class="card wide"><h2>People against the tool</h2>
      ${(q.reviews || []).length ? `<ul class="rev">${q.reviews.map(r => `<li><b>${kind(r)}</b> rated ${r.n}: keep ${r.keep}, trim ${r.trim}, pass ${r.pass}.</li>`).join('')}</ul>
        ${q.agreement ? `<p class="muted">The two reviewers gave the same verdict on ${q.agreement.identical} of ${q.agreement.cuts} promos (Cohen's kappa ${q.agreement.kappa_three_way}). A second AI is not a stand-in for a person, so these are reported separately.</p>` : ''}`
        : '<p class="muted">No outside ratings were loaded with this run.</p>'}
      <div class="yours"><h3>Your ratings in this browser</h3>
        ${rows.length ? `<p>You rated ${rows.length} of ${D.takes.length}: keep ${rows.filter(x => x.d === 'keep').length}, trim ${rows.filter(x => x.d === 'trim').length}, pass ${rows.filter(x => x.d === 'pass').length}.${keptTop.length ? ` Of the ${keptTop.length} "Post first" promos you rated, you kept or trimmed ${kept(keptTop)}.` : ''}</p>` : '<p class="muted">Rate promos on the Review page and your numbers appear here. Export them and run the tool with <code>--review</code> to score it against you.</p>'}</div></section>
    <section class="card wide"><h2>Known weak spots</h2>
      <ul class="weak">
        <li><b>It reads a script, not footage.</b> It cannot see acting, pacing or whether a face makes someone stop.</li>
        <li><b>The judges are models.</b> A strict judge can throw out a good cut; a lenient one can wave through a dull one. Without people rating cuts nobody knows which.</li>
        <li><b>One continuous stretch.</b> The brief allows joining moments across episodes. The current finder does not build joins; the older editor mode did, and it was less reliable.</li>
        <li><b>Timestamps come from the screenplay.</b> If the final edit drifts from it, every cut point drifts too.</li>
        <li><b>Small samples.</b> One show and one made-up demo so far. Treat the numbers as a first reading.</li>
      </ul></section>`;
}

/* ---------- results download (the deliverable) ---------- */
function downloadResults(kind) {
  const rows = D.takes.slice().sort((a, b) => a.rank - b.rank).map(tk => ({
    rank: tk.rank, post_slot: PLAN_NAME[tk.plan], episode: tk.episode,
    segments_in_order: segText(tk), duration_seconds: +durOf(tk).toFixed(1),
    hook: tk.ai.hook, cliffhanger: tk.ai.cliff, why_it_works: tk.ai.why, why_this_slot: tk.ai.planReason,
    spoiler: tk.ai.spoiler || 'none', moved_by_you: isTrimmed(tk) ? 'yes' : 'no',
  }));
  let blob, name = `promos-${D.id}.${kind}`;
  if (kind === 'json') blob = new Blob([JSON.stringify({ show: D.show.title, promos: rows }, null, 2)], { type: 'application/json' });
  else {
    const cell = v => { let t = String(v ?? ''); if (/^[=+\-@\t\r]/.test(t)) t = "'" + t; return '"' + t.replace(/"/g, '""') + '"'; };
    const cols = Object.keys(rows[0]);
    blob = new Blob([[cols.join(','), ...rows.map(r => cols.map(c => cell(r[c])).join(','))].join('\r\n')], { type: 'text/csv;charset=utf-8' });
  }
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  toast(`Downloaded ${rows.length} promos.`);
}

/* ---------- router ---------- */
function openTake(id) {
  if (ui.blind) setBlind(false);
  location.hash = '#/review';
  const i = order.findIndex(di => D.takes[di].id === id);
  setTimeout(() => go(Math.max(0, i), true), 30);
}
function route() {
  const v = (location.hash.match(/^#\/(\w+)/) || [])[1];
  view = VIEWS.includes(v) ? v : 'promos';
  E.app.dataset.view = view;
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('on', el.id === 'v-' + view));
  E.nav.querySelectorAll('a').forEach(a => { const on = a.dataset.nav === view; a.classList.toggle('on', on); if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  if (view !== 'review') stop();
  if (view === 'promos') renderPromos();
  if (view === 'season') renderSeason();
  if (view === 'quality') renderQuality();
  if (view === 'review') { go(cur, false); }
  const sc = document.querySelector('.view.on'); if (sc) sc.scrollTop = 0;
  document.title = ({ promos: 'Promos', review: 'Review', season: 'Season', quality: 'Quality', new: 'New show' })[view] + ' · ' + D.show.title + ' · Promo Finder';
}

/* ---------- opening ---------- */
function roll(target) {
  E.intro.classList.add('rolling');
  E.app.removeAttribute('aria-hidden');
  setTimeout(() => E.intro.classList.add('gone'), reduced ? 0 : 1000);
  location.hash = '#/' + target;
  if (target === 'review') go(cur, true);
}
function init() {
  E.showTitle.textContent = D.show.title;
  if (D.show.demo) { const d = document.getElementById('demoPill'); d.hidden = false; }
  E.introTitle.textContent = D.show.title;
  const n = D.takes.length, eps = new Set(D.takes.map(t => t.episode)).size;
  E.introLede.textContent = `${n} promos found in ${eps} episodes`;
  E.introSub.textContent = 'Ranked in posting order, each with its start and end times, the hook, the cliffhanger and why it works. Watch any of them as the script plays, trim it, and say keep, trim or pass.';
  E.blindBtn.setAttribute('aria-pressed', ui.blind); E.app.classList.toggle('blind', ui.blind);
  buildOrder(); renderStrip(); renderFeed(); renderProgress(); wire();
  const firstOpen = order.findIndex(di => !(saved[D.takes[di].id] && saved[D.takes[di].id].d));   // resume where you left off
  cur = Math.max(0, firstOpen);
  E.rollBtn.addEventListener('click', () => roll('promos'));
  E.rollBlindBtn.addEventListener('click', () => roll('review'));
  window.addEventListener('hashchange', route);
  route();
  if (location.hash.length > 2) { E.intro.classList.add('gone'); E.app.removeAttribute('aria-hidden'); }   // a deep link skips the title card
}
init();
})();
