/* The optional review studio: plays each promo as the script unfolds, lets you nudge its cut points to clean line breaks,
   and records keep / trim / pass. Decisions stay in this browser; "Download handoff" turns them into a list for an editor.
   Times are centiseconds (cs), like the data. */
(() => {
'use strict';
const D = window.PROMO_DATA;
if (!D || !Array.isArray(D.takes) || (D.schema || 1) > 1) {
  document.body.insertAdjacentHTML('afterbegin', '<p style="padding:24px;font:16px system-ui">This results file was made by a different version of Promo Finder and cannot be shown here.</p>');
  throw new Error('Unreadable PROMO_DATA');
}
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

/* ---------- saved state (this browser only) ---------- */
const KEY = 'cutting-room:' + D.id;
const memory = {};
const store = window.PROMO_MEMORY_ONLY ? { getItem: k => memory[k] ?? null, setItem: (k, v) => { memory[k] = v; } }
  : { getItem: k => localStorage.getItem(k), setItem: (k, v) => localStorage.setItem(k, v) };
const read = k => { try { return JSON.parse(store.getItem(k) || '{}'); } catch (e) { return {}; } };
const write = (k, v) => { try { store.setItem(k, JSON.stringify(v)); } catch (e) { /* private window: keep going without saving */ } };
let saved = read(KEY);                       // { takeId: { d: 'keep'|'trim'|'pass'|null, in, out } }
const ui = { blind: false };                 // the AI-hint switch was removed; the flag stays false so the shared code reads simply
const persist = () => write(KEY, saved);
const EMPTY = !D.takes.length;
const PLAN_ORDER = ['post_first', 'library', 'hold_back', 'alternate'];
const PLAN_NAME = { post_first: 'Post first', library: 'Post later', hold_back: 'Held back for spoilers', alternate: 'Second versions' };
const PLAN_NOTE = { post_first: 'The strongest cut from each episode, earliest episodes first.', library: 'Good promos for after the first wave.', hold_back: 'These show a big twist. Save them for later.', alternate: 'The same moment as a stronger promo.' };
let order = [];
function buildOrder() { const idx = D.takes.map((_, i) => i); order = PLAN_ORDER.flatMap(p => idx.filter(i => D.takes[i].plan === p)); }
let cur = 0;
const take = () => D.takes[order[cur]];
const win = tk => tk.segments[0];
const trimFor = tk => { const s = saved[tk.id], w = win(tk); return s && s.in != null ? { in: s.in, out: s.out } : { in: w.start, out: w.end }; };
const isTrimmed = tk => { const t = trimFor(tk), w = win(tk); return t.in !== w.start || t.out !== w.end; };
const P = { playing: false, t: 0, speed: 1, last: 0, ended: false, cutTimer: 0, chan: {}, typed: null };
const E = {};
['phone', 'screen', 'gateArc', 'shotTag', 'gateTag', 'narr', 'sub', 'subWho', 'subLine', 'sfx', 'cutScreen', 'cutQuestion',
  'peekBtn', 'replayBtn', 'cutPeek', 'playBtn', 'restartBtn', 'clock', 'clockTotal', 'speedBtn', 'theatreBtn', 'timeline', 'timelineHint',
  'feed', 'slate', 'toast', 'progress'].forEach(id => { E[id] = document.getElementById(id); });
E.app = document.getElementById('v-review');
E.dlCsv = document.getElementById('rvCsv'); E.dlJson = document.getElementById('rvJson');
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const sortedTakes = () => D.takes.slice().sort((a, b) => a.rank - b.rank);
const shotWords = t => t.split(/\s+(?:on|of|as|from|showing|following|tracking|toward|towards|between|with|over|past|at|that)\b/i);
const gateCue = (w, tr) => w.cues.find(c => (c.k === 'd' || c.k === 'a') && c.s >= tr.in && c.s < tr.in + 300);
function shotParts(text) { const [head, ...rest] = shotWords(text); return { type: head.replace(/[.,]$/, '').slice(0, 38), more: rest.join(' ').slice(0, 96) }; }
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
let toastT = 0;
function toast(msg) { E.toast.textContent = msg; E.toast.classList.add('on'); clearTimeout(toastT); toastT = setTimeout(() => E.toast.classList.remove('on'), 2400); }
function go(i, play) {
  cur = clamp(i, 0, order.length - 1);
  const tk = take(), tr = trimFor(tk);
  P.t = tr.in; P.ended = false; P.chan = {}; stop();
  E.cutScreen.classList.remove('on'); E.cutPeek.hidden = true;
  const h = hueOf(tk.episode);
  E.screen.style.setProperty('--h1', h); E.screen.style.setProperty('--h2', partner(h));
  E.phone.parentElement.parentElement.style.setProperty('--glow-h', h);
  buildTimeline(); renderSlate(); markFeed(); paint();
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
  E.screen.style.setProperty('--glow', '.3');

  // the 3-second gate
  const gp = clamp((t - tr.in) / 300, 0, 1), ok = !!gateCue(w, tr);
  E.gateArc.style.strokeDasharray = `${(P.ended || gp >= 1 ? (ok ? 100 : 0) : gp * 100).toFixed(1)} 100`;
  E.gateTag.className = 'hud-gate' + (gp >= 1 ? (ok ? ' cleared' : ' quiet') : '');
  E.gateTag.textContent = gp >= 1 ? (ok ? 'Gate cleared' : 'Quiet start') : '3-second gate';

  E.clock.textContent = rel(t - tr.in);
  movePlayhead();
}
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
function storyBeats(tk, tr) {                       // the promo as a tiny story: how it opens, what turns, where it stops
  const w = win(tk), mid = (tr.in + tr.out) / 2;
  const dl = w.cues.filter(c => c.k === 'd' && c.s >= tr.in && c.e <= tr.out);
  const turn = dl.length ? dl.reduce((b, c) => Math.abs(c.s - mid) < Math.abs(b.s - mid) ? c : b) : null;
  return [['Hook', openingText(tk)], ['Turn', turn ? (turn.who ? turn.who + ': ' : '') + turn.text : ''], ['Cliffhanger', tk.ai.cliff || '']].filter(b => b[1]);
}
function renderSlate() {
  const tk = take(), w = win(tk), tr = trimFor(tk), len = (tr.out - tr.in) / 100, items = checks(w, tr), s = saved[tk.id] || {};
  const verdict = (d, label, key) => `<button class="verdict ${d} ${s.d === d ? 'on' : ''}" data-d="${d}" aria-pressed="${s.d === d}">${label}<kbd>${key}</kbd></button>`;
  const lastLines = w.cues.filter(c => (c.k === 'd' || c.k === 'a') && c.e <= tr.out && c.e > tr.out - 700).slice(-2).map(c => (c.who ? c.who + ': ' : '') + c.text);
  const v = tk.ai.viewer || {};
  const chip = (txt, cls) => txt ? `<span class="tag ${cls}">${esc(txt)}</span>` : '';
  const nth = cur + 1;
  const beats = storyBeats(tk, tr), log = (D.episodes.find(e => e.n === tk.episode) || {}).logline;
  const story = `<div class="slate-sec"><h2>The story in three beats</h2><ol class="story">${beats.map(([k, t]) => `<li><small>${k}</small><p>${esc(t)}</p></li>`).join('')}</ol>${log ? `<p class="story-log">Episode ${tk.episode}: ${esc(log)}</p>` : ''}</div>`;
  let html = `<div class="slate-card"><div class="clap"></div>
    <div class="slate-head"><div><small>Episode</small><b>${tk.episode}</b></div><div><small>${ui.blind ? 'Promo' : 'Rank'}</small><b>${ui.blind ? nth : tk.rank}</b></div><div><small>${ui.blind ? 'Of' : 'Post'}</small><b>${ui.blind ? order.length : esc(({ post_first: 'First', library: 'Library', hold_back: 'Held', alternate: 'Alt' })[tk.plan] || '')}</b></div></div>
    <div class="times"><div><small>In</small><b id="tIn">${fmt(tr.in)}</b></div><div><small>Out</small><b id="tOut">${fmt(tr.out)}</b></div><div class="len ${items[0].ok ? 'ok' : 'bad'}"><small>Length</small><b>${len.toFixed(1)} s</b></div></div>
    <div class="times-foot"><span>${isTrimmed(tk) ? 'You moved the cut points.' : 'Original cut from the tool.'}</span>${isTrimmed(tk) ? '<button class="link-btn" id="resetTrim" type="button">Reset to original</button>' : ''}</div>
    <ul class="rules">${items.map(i => `<li class="${i.ok ? 'ok' : 'bad'}">${i.ok ? ICON.ok : ICON.bad}<span>${esc(i.text)}</span></li>`).join('')}</ul></div>
    <div class="verdicts">${verdict('keep', 'Keep', 'K')}${verdict('trim', 'Trim', 'T')}${verdict('pass', 'Pass', 'P')}</div>
    <div class="slate-card">${story}
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
/* ---------- the editor handoff: your decisions and checked boundaries ---------- */
const HANDOFF_COLS = ['rank', 'post_slot', 'episode', 'segments_in_order', 'duration_seconds', 'your_decision', 'boundary_status', 'your_trim_attempt', 'original_segments', 'hook', 'cliffhanger', 'why_it_works', 'description_status', 'note'];
const REREVIEW = 'Needs re-review: the cut moved after the hook, cliffhanger and why were written.';
const segTextWith = (tk, tr) => tk.segments.map((sg, i) => `Ep ${sg.episode} ${fmt(i === 0 ? tr.in : sg.start)} to ${fmt(i === 0 ? tr.out : sg.end)}`).join(' + ');
const durWith = (tk, tr) => ((tr.out - tr.in) + tk.segments.slice(1).reduce((a, g) => a + (g.end - g.start), 0)) / 100;
const origTrim = tk => ({ in: win(tk).start, out: win(tk).end });
function trimProblems(tk, tr) {                      // the same rules the Review page shows live, plus the total length
  if (!(tr.out > tr.in)) return ['the end is not after the start'];
  const out = [], total = durWith(tk, tr);
  if (total < 20 || total > 60) out.push(`${total.toFixed(1)} seconds is outside the 20 to 60 limit`);
  checks(win(tk), tr).slice(1).forEach(c => { if (!c.ok) out.push(c.text.charAt(0).toLowerCase() + c.text.slice(1)); });
  return out;
}
function handoff() {
  const rows = [], left = [], sum = { keep: 0, trim: 0, unrated: 0, passed: 0, moved: 0, reverted: 0 };
  sortedTakes().forEach(tk => {
    const s = saved[tk.id], d = (s && s.d) || 'unrated', o = origTrim(tk), cur = trimFor(tk), moved = isTrimmed(tk);
    if (d === 'pass') { sum.passed++; left.push({ rank: tk.rank, episode: tk.episode, segments_in_order: segTextWith(tk, o), reason: 'You marked this Pass, so it is not in the handoff.' }); return; }
    const bad = moved ? trimProblems(tk, cur) : [], good = moved && !bad.length, use = good ? cur : o;
    let status = 'As found by the tool';
    if (good) { status = 'Moved by you; all checks pass'; sum.moved++; }
    if (moved && bad.length) { status = `Your trim failed the checks (${bad.join('; ')}), so the original boundaries are kept`; sum.reverted++; }
    sum[d]++;
    rows.push({ rank: tk.rank, post_slot: PLAN_NAME[tk.plan], episode: tk.episode, segments_in_order: segTextWith(tk, use), duration_seconds: +durWith(tk, use).toFixed(1),
      your_decision: d, boundary_status: status, your_trim_attempt: moved && bad.length ? segTextWith(tk, cur) : '', original_segments: good ? segTextWith(tk, o) : '',
      hook: tk.ai.hook, cliffhanger: tk.ai.cliff, why_it_works: tk.ai.why || '', description_status: good ? REREVIEW : 'Written for these boundaries',
      note: d === 'trim' && !moved ? 'Marked trim, but no new cut points were set.' : '' });
  });
  return { rows, left, sum };
}
const handoffNote = () => {
  const { sum } = handoff(), parts = [`keep ${sum.keep}`, `trim ${sum.trim}`, `not rated ${sum.unrated}`];
  return `${parts.join(', ')}${sum.passed ? ` · ${sum.passed} marked Pass and left out` : ''}${sum.moved ? ` · ${sum.moved} moved, hook and why need re-review` : ''}${sum.reverted ? ` · ${sum.reverted} invalid trim${sum.reverted > 1 ? 's' : ''} reverted to the original` : ''}`;
};
const csvCell = v => { let t = String(v ?? ''); if (/^[=+\-@\t\r]/.test(t)) t = "'" + t; return '"' + t.replace(/"/g, '""') + '"'; };
function saveBlob(blob, name) {
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
function download(kind, cols, rows, extra, name) {
  const blob = kind === 'json' ? new Blob([JSON.stringify({ show: D.show.title, ...extra, promos: rows }, null, 2)], { type: 'application/json' })
    : new Blob([[cols.join(','), ...rows.map(r => cols.map(c => csvCell(r[c])).join(','))].join('\r\n')], { type: 'text/csv;charset=utf-8' });
  saveBlob(blob, `${name}-${D.id}.${kind}`);
}
function downloadHandoff(kind) {                      // your decisions and checked boundaries, ready for an editor
  const { rows, left, sum } = handoff();
  download(kind, HANDOFF_COLS, rows, { note: 'Passed cuts are left out. A moved cut keeps the original hook, cliffhanger and why, flagged for re-review. An invalid trim is reverted to the original boundaries.', summary: sum, left_out: left }, 'editor-handoff');
  toast(rows.length ? `Downloaded the editor handoff: ${rows.length} cut${rows.length > 1 ? 's' : ''}${left.length ? `, ${left.length} left out` : ''}.` : 'Nothing to hand off: every cut is marked Pass, or the run has no promos. The file holds only the column names.');
}

function renderProgress() {
  const done = D.takes.filter(t => saved[t.id] && saved[t.id].d).length;
  E.progress.textContent = done ? `${done} of ${D.takes.length} marked` : '';
}

/* ---------- wiring ---------- */
function wire() {
  E.playBtn.addEventListener('click', () => P.playing ? stop() : start());
  E.restartBtn.addEventListener('click', () => { P.t = trimFor(take()).in; P.ended = false; E.cutScreen.classList.remove('on'); P.chan = {}; paint(); start(); });
  E.replayBtn.addEventListener('click', () => E.restartBtn.click());
  E.peekBtn.addEventListener('click', () => { const tk = take(); E.cutPeek.hidden = false; E.cutPeek.textContent = tk.next ? tk.next : 'The script has nothing more in this episode.'; });
  E.speedBtn.addEventListener('click', () => { P.speed = P.speed === 1 ? 2 : P.speed === 2 ? 4 : 1; E.speedBtn.textContent = P.speed + 'x'; });
  E.theatreBtn.addEventListener('click', () => { const on = E.app.classList.toggle('theatre'); E.theatreBtn.setAttribute('aria-pressed', on); });
  E.dlCsv.addEventListener('click', () => downloadHandoff('csv'));
  E.dlJson.addEventListener('click', () => downloadHandoff('json'));
  document.addEventListener('keydown', ev => {
    if (EMPTY || ev.metaKey || ev.ctrlKey || ev.altKey || !E.app.classList.contains('on')) return;
    if (ev.target.closest && ev.target.closest('input, textarea, select')) return;
    if (ev.target.closest && ev.target.closest('.tl-handle') && (ev.key === 'ArrowUp' || ev.key === 'ArrowDown')) return;
    const k = ev.key.toLowerCase();
    if (k === ' ') { ev.preventDefault(); P.playing ? stop() : start(); }
    else if (k === 'arrowright') go(cur + 1, true);
    else if (k === 'arrowleft') go(cur - 1, true);
    else if (k === 'k') decide('keep'); else if (k === 't') decide('trim'); else if (k === 'p') decide('pass');
    else if (k === 'r') E.restartBtn.click();
    else if (k === 'f') E.theatreBtn.click();
    else if (k === 'escape') { E.app.classList.remove('theatre'); E.theatreBtn.setAttribute('aria-pressed', false); }
    else if (k === '[' || k === ']') {
      const tk = take(), tr = { ...trimFor(tk) }, s = snap(P.t, win(tk).edges);
      if (k === '[') tr.in = Math.min(s, tr.out - 500); else tr.out = Math.max(s, tr.in + 500);
      setTrim(tk, tr, k === '[' ? 'in' : 'out'); renderSlate();
    }
  });
}

let started = false;
function start(id) {
  if (EMPTY) {
    document.getElementById('room').innerHTML = '<div style="padding:40px"><h1>Nothing to review yet</h1><p class="muted">No promo passed the checks in this run.</p></div>';
    return;
  }
  if (!started) { started = true; buildOrder(); renderFeed(); renderProgress(); wire(); }
  const at = id ? order.findIndex(di => D.takes[di].id === id) : -1;
  const firstOpen = order.findIndex(di => !(saved[D.takes[di].id] && saved[D.takes[di].id].d));
  go(at >= 0 ? at : (started && cur ? cur : Math.max(0, firstOpen)), at >= 0);
}
window.PromoReview = { start, stop };
window.dispatchEvent(new Event('promo-review-ready'));
})();
