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
const PLAN_NAME = { post_first: 'Post first', library: 'Library', hold_back: 'Held back for spoilers', alternate: 'Alternates that overlap a stronger take' };
const PLAN_NOTE = { post_first: 'The strongest cut from each episode, early episodes first.', hold_back: 'These show a big twist. Save them for later.' };
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
  'introTitle', 'introLede', 'introSub'].forEach(id => { E[id] = document.getElementById(id); });

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
  const others = D.reviewers.map(r => tk.reviews[r.id] ? `<span class="tag ${tk.reviews[r.id] === 'keep' ? 'good' : tk.reviews[r.id] === 'trim' ? 'warn' : 'bad'}">${esc(r.name)}: ${tk.reviews[r.id]}</span>` : '').join('');
  const nth = cur + 1;
  let html = `<div class="slate-card"><div class="clap"></div>
    <div class="slate-head"><div><small>Scene</small><b>Ep ${tk.episode}</b></div><div><small>Take</small><b>${ui.blind ? nth : tk.rank}</b></div><div><small>${ui.blind ? 'Of' : 'Roll'}</small><b>${ui.blind ? order.length : esc(({ post_first: 'First', library: 'Library', hold_back: 'Held', alternate: 'Alt' })[tk.plan] || '')}</b></div></div>
    <div class="times"><div><small>In</small><b id="tIn">${fmt(tr.in)}</b></div><div><small>Out</small><b id="tOut">${fmt(tr.out)}</b></div><div class="len ${items[0].ok ? 'ok' : 'bad'}"><small>Length</small><b>${len.toFixed(1)} s</b></div></div>
    <div class="times-foot"><span>${isTrimmed(tk) ? 'You moved the cut points.' : 'Original cut from the tool.'}</span>${isTrimmed(tk) ? '<button class="link-btn" id="resetTrim" type="button">Reset to original</button>' : ''}</div>
    <ul class="rules">${items.map(i => `<li class="${i.ok ? 'ok' : 'bad'}">${i.ok ? ICON.ok : ICON.bad}<span>${esc(i.text)}</span></li>`).join('')}</ul></div>
    <div class="verdicts">${verdict('keep', 'Keep', 'K')}${verdict('trim', 'Trim', 'T')}${verdict('pass', 'Pass', 'P')}</div>
    <div class="slate-card">
      <div class="slate-sec"><h2>What opens it</h2><p class="quote">${esc(openingText(tk))}</p></div>
      <div class="slate-sec"><h2>Where it ends</h2>${lastLines.map(l => `<p class="quote">${esc(l)}</p>`).join('') || '<p class="muted">The last lines before the cut.</p>'}</div>`;
  if (ui.blind) {
    html += `<div class="blind-note"><b>Blind mode is on.</b> The tool's ranking, summaries and judge verdicts are hidden, and the takes are shuffled. Rate what you see.</div></div>`;
  } else {
    html += `<div class="slate-sec"><h2>Why the tool picked it</h2>
        <p class="quote"><em>Hook</em>${esc(tk.ai.hook)}</p><p class="quote"><em>Left hanging</em>${esc(tk.ai.cliff)}</p>
        ${tk.ai.why ? `<p class="muted" style="margin-top:8px">${esc(tk.ai.why)}</p>` : ''}
        <div class="tags">${chip(tk.ai.hookType, '')}${chip(tk.ai.spoiler !== 'none' ? tk.ai.spoiler + ' spoiler' : '', 'warn')}${chip(tk.source === 'rules' ? 'No-AI baseline' : 'AI scored', '')}</div></div>
      ${v.who ? `<div class="slate-sec"><h2>What a stranger understood</h2><p class="quote">${esc(v.who)} ${esc(v.situation)}</p>
        <p class="quote"><em>Wondering</em>${esc(v.open_question)}</p>
        <div class="tags">${chip('First 3 s: ' + v.first_3s.replace('_', ' '), v.first_3s === 'stop' ? 'good' : 'warn')}${chip('Clear: ' + v.makes_sense, v.makes_sense === 'yes' ? 'good' : 'warn')}${chip('Ending: ' + v.ending, v.ending === 'unresolved' ? 'good' : 'warn')}</div>
        ${v.confusing && v.confusing !== 'nothing' ? `<p class="muted" style="margin-top:8px">Confusing: ${esc(v.confusing)}</p>` : ''}</div>` : ''}
      ${others ? `<div class="slate-sec"><h2>Other ratings</h2><div class="others">${others}</div></div>` : ''}
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
  toast(left ? `${d[0].toUpperCase() + d.slice(1)} saved. ${left} to go.` : 'All takes rated. Export your ratings when you are ready.');
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
      html += `<div class="rail-title"><h2>${ui.blind ? 'Takes in random order' : PLAN_NAME[tk.plan]}</h2><span>${n}</span></div>`;
      if (!ui.blind && PLAN_NOTE[tk.plan]) html += `<p class="rail-note">${PLAN_NOTE[tk.plan]}</p>`;
    }
    html += `<button class="take" data-i="${i}" style="--h:${hueOf(tk.episode)}" aria-label="Take ${ui.blind ? i + 1 : tk.rank}, episode ${tk.episode}">
      <span class="poster"><b>${tk.episode}</b><i>${Math.round((trimFor(tk).out - trimFor(tk).in) / 100)} s</i></span>
      <span><span class="open">${esc(openingText(tk))}</span><span class="sub">Episode ${tk.episode}${ui.blind ? '' : ', take ' + tk.rank}</span></span>
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
    if (i >= 0) go(i, true); else toast(`No take for episode ${n} in this run.`);
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
    rows.push([tk.rank, tk.id, tk.episode, tk.key, s.d, s.d === 'trim' && changed ? fmt(s.in) : '', s.d === 'trim' && changed ? fmt(s.out) : '', 'Cutting room' + (ui.blind ? ' (blind)' : '')]);
  });
  if (rows.length === 1) { toast('Rate at least one take first.'); return; }
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
  toast(on ? 'Blind mode on. AI opinions are hidden.' : 'Blind mode off.');
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

/* ---------- opening ---------- */
function roll(blind) {
  if (blind) { ui.blind = true; write(KEY + ':ui', ui); E.blindBtn.setAttribute('aria-pressed', true); E.app.classList.add('blind'); buildOrder(); renderFeed(); }
  E.intro.classList.add('rolling');
  E.app.removeAttribute('aria-hidden');
  setTimeout(() => E.intro.classList.add('gone'), reduced ? 0 : 1000);
  go(0, true);
}
function init() {
  document.title = D.show.title + ': cutting room';
  E.showTitle.textContent = D.show.title;
  if (D.show.demo) { const d = document.getElementById('demoPill'); d.hidden = false; }
  E.introTitle.textContent = D.show.title;
  const n = D.takes.length, eps = new Set(D.takes.map(t => t.episode)).size;
  E.introLede.textContent = `${n} takes from ${eps} episodes are waiting for your call`;
  E.introSub.textContent = 'Each take is a promo the tool found. Watch it play as the script unfolds, trim it to clean cut points, then keep it, trim it or pass.';
  E.blindBtn.setAttribute('aria-pressed', ui.blind); E.app.classList.toggle('blind', ui.blind);
  buildOrder(); renderStrip(); renderFeed(); renderProgress(); wire();
  const firstOpen = order.findIndex(di => !(saved[D.takes[di].id] && saved[D.takes[di].id].d));   // resume where you left off
  go(Math.max(0, firstOpen), false);
  E.rollBtn.addEventListener('click', () => roll(false));
  E.rollBlindBtn.addEventListener('click', () => roll(true));
  if (location.hash === '#skip') { E.intro.classList.add('gone'); E.app.removeAttribute('aria-hidden'); }
}
init();
})();
