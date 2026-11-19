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
const EMPTY = !D.takes.length;                                    // a strict judge, or a provider that stopped, can leave zero promos
const RUN = D.run || {};
const NOAI = RUN.ai === false;                                    // timing rules only: candidates for an editor, not judged promos
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const COV = new Map((D.coverage || []).map(c => [c.episode, c]));
const FILLED = (D.coverage || []).filter(c => c.status === 'Rules candidate').length;   // episodes covered only by the no-AI rules   // the per-episode ledger: the real source of each episode's status

/* ---------- order: AI plan order, or a seeded shuffle in blind mode ---------- */
const PLAN_ORDER = ['post_first', 'library', 'hold_back', 'alternate'];
const PLAN_NAME = { post_first: 'Post first', library: 'Post later', hold_back: 'Hold back (big spoilers)', alternate: 'Second versions of a cut above' };
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
['app', 'phone', 'screen', 'gateArc', 'shotTag', 'gateTag', 'narr', 'sub', 'subWho', 'subLine', 'sfx', 'cutScreen', 'cutQuestion',
  'peekBtn', 'replayBtn', 'cutPeek', 'playBtn', 'restartBtn', 'clock', 'clockTotal', 'speedBtn', 'theatreBtn', 'timeline', 'timelineHint',
  'feed', 'slate', 'strip', 'progress', 'blindBtn', 'exportBtn', 'helpBtn', 'help', 'toast', 'showTitle',
  'promosPage', 'qualityPage', 'nav', 'newBtn', 'newShow'].forEach(id => { E[id] = document.getElementById(id); });

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
  E.progress.title = 'Promos you have marked Keep, Trim or Pass';
  if (!done) { E.progress.innerHTML = ''; return; }
  E.progress.innerHTML = `<svg viewBox="0 0 34 34" aria-hidden="true"><circle class="p-track" cx="17" cy="17" r="14"/><circle class="p-fill" cx="17" cy="17" r="14" stroke-dasharray="${(done / total * c).toFixed(1)} ${c.toFixed(1)}"/></svg><span>${done} of ${total} rated</span>`;
}

/* ---------- export ---------- */
function exportCsv() {
  const rows = [['rank', 'id', 'episode', 'segments_in_order', 'decision', 'suggested_in', 'suggested_out', 'reviewer', 'note']];
  D.takes.forEach(tk => {
    const s = saved[tk.id]; if (!s || !s.d) return;
    const w = win(tk), changed = s.in !== w.start || s.out !== w.end;
    const bad = s.d === 'trim' && changed ? trimProblems(tk, { in: s.in, out: s.out }) : [];     // a trim that breaks a rule is not a suggestion
    rows.push([tk.rank, tk.id, tk.episode, tk.key, s.d, s.d === 'trim' && changed && !bad.length ? fmt(s.in) : '', s.d === 'trim' && changed && !bad.length ? fmt(s.out) : '', 'Cutting room' + (ui.blind ? ' (AI hints hidden)' : ''),
      bad.length ? `trim ignored: ${bad.join('; ')}` : '']);
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
    if (EMPTY || E.help.open || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (view === 'promos') { const k0 = ev.key; if (k0 === 'Escape') closeDrawer(); else if (drawerOpen && (k0 === 'ArrowRight' || k0 === 'ArrowDown')) { ev.preventDefault(); stepPromo(1); } else if (drawerOpen && (k0 === 'ArrowLeft' || k0 === 'ArrowUp')) { ev.preventDefault(); stepPromo(-1); } return; }
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
const VIEWS = ['promos', 'review', 'quality'];
let view = 'promos';
const segText = tk => {
  const t = trimFor(tk);
  return tk.segments.map((sg, i) => `Ep ${sg.episode} ${fmt(i === 0 ? t.in : sg.start)} to ${fmt(i === 0 ? t.out : sg.end)}`).join(' + ');
};
const durOf = tk => { const t = trimFor(tk); return ((t.out - t.in) + tk.segments.slice(1).reduce((a, g) => a + (g.end - g.start), 0)) / 100; };
const pct = (n, d) => d ? Math.round(n / d * 100) + '%' : 'n/a';
const unq = s => String(s ?? '').replace(/^["“]|["”]$/g, '');
const sortedTakes = () => D.takes.slice().sort((a, b) => a.rank - b.rank);
const mmss = cs => { const s = Math.round(Math.max(0, cs) / 100), m = Math.floor(s / 60); return m + ':' + String(s % 60).padStart(2, '0'); };
const range = (sg, tr) => `${fmt(tr ? tr.in : sg.start)} to ${fmt(tr ? tr.out : sg.end)}`;

let selPromo = null, drawerOpen = false, reelT = 0, reelI = 0;
const flt = { ep: 0, mode: 'list' };
const clearReel = () => { clearTimeout(reelT); reelT = 0; };

/* ---------- what happened in this run, and cuts that were never judged ---------- */
function runStrip() {
  const r = RUN, w = r.warnings || [], items = [['Episodes in this run', `${r.requested ?? D.show.episodes} of ${r.pack ?? D.show.episodes}`]];
  if (r.ai) { items.push(['Scored by AI', r.scored != null ? String(r.scored) : 'n/a']); items.push(['Cuts judged', `${r.judged ?? 0} of ${r.candidates ?? 0}`]); }
  else items.push(['AI used', 'none, timing rules only']);
  items.push(['Shortlisted', String(r.shortlisted ?? D.takes.length)]);
  items.push(['Provider', r.ai ? (w.length ? 'interrupted' : 'no interruption') : 'not used']);
  return `<ul class="runstrip" aria-label="What happened in this run">${items.map(([a, b]) => `<li class="${a === 'Provider' && w.length ? 'warn' : ''}"><span>${esc(a)}</span><b>${esc(b)}</b></li>`).join('')}</ul>`;
}
function runBanner() {
  const w = RUN.warnings || [], out = [];
  if (w.length) out.push(`<div class="banner warn" role="status"><b>This run did not finish cleanly.</b><ul>${w.map(x => `<li>${esc(x)}</li>`).join('')}</ul><p>Cuts that were not judged are marked "Review needed". Run it again later or pick another engine: finished work is cached, so repeating costs nothing.</p></div>`);
  if (EMPTY) out.push(`<div class="banner" role="status"><b>No promo passed the checks in this run.</b><p>${w.length ? 'The run stopped early, so the judge never saw the candidates.' : 'The judge, or the rules, rejected every candidate.'} The timing-checked cuts further down are material for an editor to review. Nobody has judged them as promos.</p></div>`);
  return out.join('');
}
function candidatesHtml() {
  const list = (D.coverage || []).filter(c => c.cut && c.status !== 'Viewer passed' && c.status !== 'Timing checked');
  const lede = FILLED ? `${FILLED} episodes were not judged by the AI; the no-AI rules found a timing-checked cut for each. They are material for an editor, not judged promos.` : 'Timing-checked (20 to 60 seconds, cut on clean line breaks) but not judged as promos.';
  if (!list.length) return '';
  return `<section class="rail-band cand-band"><div class="rail-head"><h2>Cuts for an editor to review</h2><span class="count">${list.length}</span><p>${lede}</p></div>
    <div class="cand-grid">${list.map(c => `<article class="cand"><header><b>Episode ${c.episode}</b><span class="tag warn">${c.status === 'Rules candidate' ? 'rules pick, not judged' : esc(c.status)}</span></header>
      <p class="tc">${c.cut.segments.map(sg => `${esc(sg.start)} to ${esc(sg.end)}`).join(' + ')}</p>
      <dl><dt>Opens</dt><dd>${esc(c.cut.opening)}</dd><dt>Ends</dt><dd>${esc(c.cut.ending)}</dd></dl><p class="muted">${esc(c.reason)}</p></article>`).join('')}</div></section>`;
}

/* ---------- promos: reel hero, poster rails, ledger, detail drawer ---------- */
function posterHtml(tk) {
  const h = hueOf(tk.episode), s = saved[tk.id], q = unq(tk.ai.hook);
  return `<button class="poster-card ${tk.id === selPromo && drawerOpen ? 'on' : ''}" data-sel="${esc(tk.id)}" type="button" style="--h:${h};--h2:${partner(h)}" aria-label="Rank ${tk.rank}, episode ${tk.episode}, ${esc(q)}">
    <span class="pc-top"><b>${tk.rank}</b><span>Ep ${tk.episode}</span><span class="pc-len">${durOf(tk).toFixed(0)} s</span></span>
    <span class="pc-hook">${esc(q)}</span>
    <span class="pc-cut" aria-hidden="true"></span>
    <span class="pc-end"><small>Ends on</small>${esc(tk.ai.cliff || '')}</span>
    ${s && s.d ? `<i class="pc-dot ${s.d}" title="You said ${s.d}"></i>` : ''}
  </button>`;
}
function ledgerHtml(list) {
  return `<div class="ledger-wrap"><table class="ledger"><thead><tr><th>Rank</th><th>Where to cut</th><th>Hook</th><th>Cliffhanger</th><th>Why it works</th></tr></thead><tbody>${list.map(tk => `
    <tr data-sel="${esc(tk.id)}" tabindex="0"><td class="lg-rank">${tk.rank}</td>
    <td class="lg-where"><b>Episode ${tk.episode}</b>${tk.segments.map((sg, i) => `<span class="tc">${range(sg, i === 0 ? trimFor(tk) : null)}</span>`).join('')}<span class="tag">${esc(PLAN_NAME[tk.plan])}</span></td>
    <td>${esc(unq(tk.ai.hook))}</td><td>${esc(tk.ai.cliff || '')}</td><td class="lg-why">${esc(tk.ai.why || '')}</td></tr>`).join('')}</tbody></table></div>`;
}
function reelHtml(tk) {
  const h = hueOf(tk.episode);
  return `<button class="reel ph0" id="reelCard" type="button" style="--h:${h};--h2:${partner(h)}" aria-label="Open promo ${tk.rank}: ${esc(unq(tk.ai.hook))}">
      <span class="r-top"><b>${tk.rank}</b><span>Episode ${tk.episode}</span><span class="r-len">${durOf(tk).toFixed(0)} s</span></span>
      <span class="r-label" id="reelLabel">The hook</span>
      <span class="r-hook">${esc(unq(tk.ai.hook))}</span>
      <span class="r-cut" aria-hidden="true"></span>
      <span class="r-end"><small>Ends on</small>${esc(tk.ai.cliff || '')}</span>
    </button>`;
}
function playReel(top) {
  clearReel();
  if (!$('#reelCard')) return;
  const tk = top[reelI % top.length];
  $('#reelCard').outerHTML = reelHtml(tk);
  const card = $('#reelCard'), label = $('#reelLabel');
  card.addEventListener('click', () => pickPromo(tk.id, true));
  E.promosPage.querySelectorAll('.reel-dots button').forEach((b, k) => b.classList.toggle('on', k === reelI % top.length));
  const phase = (p, text) => { card.className = 'reel ph' + p; label.textContent = text; };
  if (reduced) { phase(3, 'Ends on'); return; }
  const steps = [[60, () => phase(1, 'The hook, first 3 seconds')], [3300, () => phase(2, 'The cut')], [4300, () => phase(3, 'Ends on')], [9500, () => { reelI++; playReel(top); }]];
  let at = 0;
  const run = k => { if (k >= steps.length) return; reelT = setTimeout(() => { steps[k][1](); run(k + 1); }, steps[k][0] - at); at = steps[k][0]; };
  run(0);
}
function renderPromos() {
  clearReel();
  const n = D.takes.length, eps = new Set(D.takes.map(t => t.episode)).size, all = sortedTakes();
  if (!selPromo || !D.takes.some(t => t.id === selPromo)) selPromo = all[0] && all[0].id;
  const top = all.slice(0, 3);
  const epsWith = [...new Set(all.map(t => t.episode))].sort((a, b) => a - b);
  const shown = all.filter(t => !flt.ep || t.episode === flt.ep);
  const groups = PLAN_ORDER.map(g => ({ g, list: shown.filter(t => t.plan === g) })).filter(x => x.list.length);
  const body = EMPTY ? '' : !shown.length ? '<p class="empty band">No promos for that episode.</p>'
    : flt.mode === 'list' ? ledgerHtml(shown)
    : groups.map(({ g, list }) => `<section class="rail-band ${g === 'post_first' ? 'first' : ''}"><div class="rail-head"><h2>${PLAN_NAME[g]}</h2><span class="count">${list.length}</span><p>${PLAN_NOTE[g]}</p></div><div class="rail ${g === 'post_first' ? 'big' : ''}">${list.map(posterHtml).join('')}</div></section>`).join('');
  const off = EMPTY ? ' disabled' : '';
  const reelRow = EMPTY || flt.mode !== 'posters' ? '' : `<section class="reel-row"><div class="reel-stage"><button class="reel ph0" id="reelCard" type="button"><span id="reelLabel"></span></button>
        <div class="reel-dots" role="group" aria-label="Preview another promo">${top.map(t => `<button type="button" aria-label="Preview promo ${t.rank}"></button>`).join('')}</div></div>
      <div><h2>Preview the top ${top.length}</h2><p>Each one opens on its hook, cuts, and ends on the cliffhanger. Click a preview to open it.</p></div></section>`;
  E.promosPage.innerHTML = `
    <section class="hero-band slim">
      <div class="hero-copy">
        <h1>${EMPTY ? 'No promo passed the checks' : NOAI ? `${plural(n, 'candidate cut', 'candidate cuts')} to review` : `${plural(n, 'promo', 'promos')}, ready to post`}</h1>
        <p class="lede">${EMPTY ? `Nothing from ${esc(D.show.title)} reached the shortlist in this run. What was tried, and what is left for an editor, is below.` : NOAI ? `Timing-checked cuts from ${eps} of the ${RUN.requested ?? D.show.episodes} episodes run, from ${esc(D.show.title)}, found by rules with no AI. Material for an editor to review; nobody has judged them as promos.` : `From ${eps} of the ${RUN.requested ?? D.show.episodes} episodes run of ${esc(D.show.title)}${RUN.requested && RUN.requested < D.show.episodes ? (FILLED ? ` (the other ${D.show.episodes - RUN.requested} have rules picks, not judged)` : ` (${D.show.episodes - RUN.requested} more were not run)`) : ''}. Post them in this order. Each opens on a hook and ends on a cliffhanger.`}</p>
        <div class="head-actions">
          <details class="dl"><summary class="pill primary">Download</summary>
            <div class="dl-menu">
              <div><b>All results</b><span>${EMPTY ? 'Nothing to export: no promo passed the checks.' : 'As the tool found them. Your trims and ratings never change this.'}</span><div><button class="pill" id="dlCsv" type="button"${off}>CSV</button><button class="pill" id="dlJson" type="button"${off}>JSON</button></div></div>
              <div><b>For the editor</b><span id="hoNote">${EMPTY ? 'Nothing to hand off: no promo passed the checks.' : esc(handoffNote())}</span><div><button class="pill" id="hoCsv" type="button"${off}>CSV</button><button class="pill" id="hoJson" type="button"${off}>JSON</button></div></div>
            </div></details>
          ${EMPTY ? '' : '<a class="pill" href="#/review">Review and rate</a>'}
        </div>
        ${runStrip()}
        ${EMPTY || NOAI ? '' : `<details class="how"><summary>How the order was decided</summary>
          <ul>
            <li><b>The strongest from each episode goes first</b>, earliest episodes first, because a new viewer lands on episode 1.</li>
            <li><b>Clips a stranger could not follow are dropped</b>: an AI that sees only the clip must say what is happening and what it is waiting for.</li>
            <li><b>Big twists are held back</b> so a promo does not spoil the show.</li>
            <li><b>Overlapping cuts become second versions</b> instead of repeating the same moment twice.</li>
          </ul></details>`}
      </div>
    </section>
    ${runBanner()}
    <section class="toolbar" aria-label="Layout and filter"${EMPTY ? ' hidden' : ''}>
      <div class="seg-toggle" role="group" aria-label="Layout"><button type="button" data-mode="list" aria-pressed="${flt.mode === 'list'}">List</button><button type="button" data-mode="posters" aria-pressed="${flt.mode === 'posters'}">Posters</button></div>
      <div class="ep-filter" role="group" aria-label="Filter by episode"><button class="chip" type="button" data-fep="0" aria-pressed="${!flt.ep}">All episodes</button>${epsWith.map(e => `<button class="chip" type="button" data-fep="${e}" aria-pressed="${flt.ep === e}">Ep ${e}</button>`).join('')}</div>
    </section>
    ${reelRow}
    <div id="deckBody">${body}${candidatesHtml()}</div>
    <div class="scrim" id="scrim"></div>
    <aside class="drawer" id="drawer" aria-live="polite" aria-label="Promo details"></aside>`;
  reelI = 0; if (top.length && $('#reelCard')) playReel(top);
  E.promosPage.querySelectorAll('.reel-dots button').forEach((b, k) => { b.addEventListener('click', () => { reelI = k; playReel(top); }); });
  const reelBox = $('.reel-stage', E.promosPage);
  if (reelBox) {
    reelBox.addEventListener('mouseenter', () => { if (!reduced) clearReel(); });
    reelBox.addEventListener('mouseleave', () => { if (!reduced && view === 'promos' && !drawerOpen) { reelI++; playReel(top); } });
  }
  E.promosPage.querySelectorAll('[data-sel]').forEach(b => {
    b.addEventListener('click', () => pickPromo(b.dataset.sel, true));
    if (b.tagName === 'TR') b.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pickPromo(b.dataset.sel, true); } });
  });
  E.promosPage.querySelectorAll('[data-mode]').forEach(b => b.addEventListener('click', () => { flt.mode = b.dataset.mode; renderPromos(); }));
  E.promosPage.querySelectorAll('[data-fep]').forEach(b => b.addEventListener('click', () => { flt.ep = +b.dataset.fep; renderPromos(); }));
  $('#dlCsv', E.promosPage).addEventListener('click', () => downloadResults('csv'));
  $('#dlJson', E.promosPage).addEventListener('click', () => downloadResults('json'));
  $('#hoCsv', E.promosPage).addEventListener('click', () => downloadHandoff('csv'));
  $('#hoJson', E.promosPage).addEventListener('click', () => downloadHandoff('json'));
  E.promosPage.querySelectorAll('.dl-menu button').forEach(b => b.addEventListener('click', () => { $('.dl', E.promosPage).open = false; }));
  $('#scrim', E.promosPage).addEventListener('click', closeDrawer);
  if (!EMPTY) renderDrawer();
}
function pickPromo(id, open) {
  selPromo = id; if (open) drawerOpen = true;
  E.promosPage.querySelectorAll('.poster-card').forEach(b => b.classList.toggle('on', drawerOpen && b.dataset.sel === id));
  renderDrawer();
  if (open) clearReel();
}
function closeDrawer() { drawerOpen = false; E.promosPage.querySelectorAll('.poster-card.on').forEach(b => b.classList.remove('on')); renderDrawer(); }
function renderDrawer() {
  const tk = D.takes.find(t => t.id === selPromo), el = $('#drawer'), sc = $('#scrim'); if (!tk || !el) return;
  el.classList.toggle('open', drawerOpen); sc.classList.toggle('open', drawerOpen); el.setAttribute('aria-hidden', String(!drawerOpen));
  if (!drawerOpen) return;
  const s = saved[tk.id], t = trimFor(tk), edited = isTrimmed(tk), all = sortedTakes(), i = all.indexOf(tk);
  const seg = tk.segments.map((sg, k) => `<li><span class="seg-n">${tk.segments.length > 1 ? 'Segment ' + (k + 1) : 'Clip'}</span><b>Ep ${sg.episode}</b><span class="tc">${fmt(k === 0 ? t.in : sg.start)}</span><span class="arrow">to</span><span class="tc">${fmt(k === 0 ? t.out : sg.end)}</span></li>`).join('');
  const plain = `Ep ${tk.episode}: ${segText(tk)}. Hook: ${tk.ai.hook} Cliffhanger: ${tk.ai.cliff} Why: ${tk.ai.why || ''}${edited ? ' (You moved the cut, so re-check the hook, cliffhanger and why.)' : ''}`;
  const cv = tk.ai.viewer || {};
  el.innerHTML = `<button class="drawer-close icon-btn" id="tkClose" type="button" aria-label="Close details (Esc)">&times;</button>
    <div class="tk-head"><span class="tk-rank">${tk.rank}</span><div><p class="tk-eyebrow">${esc(PLAN_NAME[tk.plan])}</p><h2>Episode ${tk.episode}, ${durOf(tk).toFixed(1)} seconds</h2></div></div>
    <ul class="segs">${seg}</ul>
    <p class="tk-note">${tk.segments.length > 1 ? 'Play the segments in this order.' : 'One continuous stretch.'}${edited ? ' <span class="tag warn">you moved the cut</span>' : ''}${edited && trimProblems(tk, t).length ? ` <span class="tag bad">your trim breaks a rule: ${esc(trimProblems(tk, t).join('; '))}. The handoff keeps the original cut.</span>` : ''}${s && s.d ? ` <span class="tag ${s.d === 'keep' ? 'good' : s.d === 'trim' ? 'warn' : 'bad'}">you said ${s.d}</span>` : ''}</p>
    <dl class="tk-facts">
      <div><dt>Hook <small>what is on screen in the first 3 seconds</small></dt><dd>${esc(tk.ai.hook)}</dd></div>
      <div><dt>Cliffhanger</dt><dd>${esc(tk.ai.cliff)}</dd></div>
      <div><dt>Why it works</dt><dd>${esc(tk.ai.why || 'No summary was written for this cut.')}</dd></div>
      ${cv.situation ? `<div><dt>What a first-time viewer understood</dt><dd>${esc(cv.situation)}${cv.open_question ? ` <span class="muted">Waiting to learn: ${esc(cv.open_question)}</span>` : ''}</dd></div>` : ''}
      <div><dt>Why this slot</dt><dd>${esc(tk.ai.planReason || PLAN_NOTE[tk.plan] || '')}${tk.ai.spoiler && tk.ai.spoiler !== 'none' ? ` <span class="tag warn">${esc(tk.ai.spoiler)} spoiler</span>` : ''}</dd></div>
    </dl>
    <div class="tk-actions"><button class="pill primary" id="tkWatch" type="button">Watch and trim</button><button class="pill" id="tkCopy" type="button">Copy for the editor</button></div>
    <div class="tk-nav"><button class="chip" id="tkPrev" type="button" ${i === 0 ? 'disabled' : ''}>Previous</button><span>${i + 1} of ${all.length}</span><button class="chip" id="tkNext" type="button" ${i === all.length - 1 ? 'disabled' : ''}>Next</button></div>`;
  $('#tkWatch', el).addEventListener('click', () => { drawerOpen = false; openTake(tk.id); });
  $('#tkCopy', el).addEventListener('click', () => { (navigator.clipboard ? navigator.clipboard.writeText(plain) : Promise.reject()).then(() => toast('Copied.'), () => toast('Copy is blocked here. Use Download results instead.')); });
  $('#tkClose', el).addEventListener('click', closeDrawer);
  $('#tkPrev', el).addEventListener('click', () => stepPromo(-1)); $('#tkNext', el).addEventListener('click', () => stepPromo(1));
}
function stepPromo(d) {
  if (!drawerOpen) return;
  const all = sortedTakes(), i = all.findIndex(t => t.id === selPromo), nx = all[clamp(i + d, 0, all.length - 1)];
  if (nx) { pickPromo(nx.id, true); const c = E.promosPage.querySelector('.poster-card.on'); if (c) c.scrollIntoView({ block: 'nearest', inline: 'center', behavior: reduced ? 'auto' : 'smooth' }); }
}
function showPromo(id) { selPromo = id; drawerOpen = true; if (view === 'promos') renderPromos(); else location.hash = '#/promos'; }

/* ---------- season: one wide row per episode, promos drawn where they sit ---------- */
const trackSvg = ep => {
  const bars = ep.pulse.map(([p, h, c]) => { const x = (p * 1000).toFixed(1), top = 54 - Math.max(h, c) * 15;
    return `<line x1="${x}" x2="${x}" y1="56" y2="${top.toFixed(1)}" stroke="${h >= c ? '#ff641c' : '#f8c543'}" stroke-width="2.4" stroke-linecap="round" vector-effect="non-scaling-stroke"/>`; }).join('');
  return `<svg class="ep-pulse" viewBox="0 0 1000 60" preserveAspectRatio="none" aria-hidden="true">${bars}</svg>`;
};
function seasonHtml() {
  const covered = D.episodes.filter(e => e.takes.length).length, inRun = (COV.size - FILLED) || D.episodes.length;
  const none = Math.max(0, inRun - covered), notRun = D.episodes.length - inRun - FILLED;
  const row = ep => {
    const takes = ep.takes.map(id => D.takes.find(t => t.id === id)).filter(Boolean), dur = Math.max(1, ep.duration);
    const brackets = takes.flatMap(tk => tk.segments.filter(sg => sg.episode === ep.n).map(sg => {
      const l = (sg.start / dur * 100).toFixed(2), w = Math.max(1.2, (sg.end - sg.start) / dur * 100).toFixed(2);
      return `<button class="br" type="button" data-take="${esc(tk.id)}" style="left:${l}%;width:${w}%" aria-label="Promo ${tk.rank}, ${mmss(sg.start)} to ${mmss(sg.end)}"><i>${tk.rank}</i></button>`; })).join('');
    const c = COV.get(ep.n);
    const state = takes.length ? `<span class="tag good">${NOAI ? plural(takes.length, 'candidate', 'candidates') : plural(takes.length, 'promo', 'promos')}</span>`
      : !c ? '<span class="tag">not in this run</span>'
      : c.status === 'Review needed' ? '<span class="tag warn">review needed</span>'
      : c.status === 'Rules candidate' ? '<span class="tag">rules pick, not judged</span>'
      : c.status === 'No eligible cut' ? '<span class="tag bad">no eligible cut</span>' : `<span class="tag">${esc(c.status.toLowerCase())}</span>`;
    const cand = !takes.length && c && c.cut ? c.cut.segments.map(sg => `<span class="br unjudged" title="A timing-checked cut that was not judged: ${esc(sg.start)} to ${esc(sg.end)}" style="left:${(sg.start_cs / dur * 100).toFixed(2)}%;width:${Math.max(1.2, (sg.end_cs - sg.start_cs) / dur * 100).toFixed(2)}%"></span>`).join('') : '';
    const why = !takes.length && c ? `<p class="ep-why">${esc(c.reason)}${c.cut ? ' A timing-checked cut for review is drawn dashed.' : ''}</p>` : '';
    return `<li class="eprow ${takes.length ? 'has' : 'gap'}"><div class="ep-id"><b>${String(ep.n).padStart(2, '0')}</b><span>${mmss(ep.duration)}</span></div>
      <div class="ep-body"><p class="ep-log">${esc(ep.logline || 'No logline in the script.')}</p>${why}<div class="ep-track">${ep.scored ? trackSvg(ep) : ''}<span class="ep-base"></span>${brackets}${cand}</div></div>
      <div class="ep-side">${state}${takes[0] ? `<button class="pill" type="button" data-take="${esc(takes[0].id)}">Open</button>` : ''}</div></li>`;
  };
  return `
    <section class="band season-head"><h2>Episode by episode</h2>
      <p class="lede">Each row is one episode, start to end. Orange and gold lines show where the AI saw a good place to open a clip or end one. Boxes are the promos, placed where they sit in the episode.</p>
      <ul class="runstrip"><li><span>${NOAI ? 'With a candidate' : 'With a promo'}</span><b>${covered} of ${inRun}</b></li><li><span>Run, but none passed</span><b>${none}</b></li>${FILLED ? `<li><span>Rules picks only, not judged</span><b>${FILLED}</b></li>` : ''}${notRun ? `<li><span>Not run at all</span><b>${notRun}</b></li>` : ''}</ul></section>
    <section class="legend"><span><i class="lg o"></i>Good place to open</span><span><i class="lg g"></i>Good place to end</span><span><i class="lg b"></i>A promo, numbered by rank</span><span><i class="lg d"></i>A cut nobody has judged</span><span class="muted">Taller lines are stronger.</span></section>
    <ol class="eprows">${D.episodes.map(row).join('')}</ol>`;
}

/* ---------- quality: measured checks, each with what it cannot prove ---------- */
function renderQuality() {
  const q = D.quality || {}, w = q.writer || {}, v = q.viewer || {}, j = q.judge || {}, rej = Object.entries(q.rejections || {});
  const rows = Object.values(saved).filter(x => x && x.d), keptTop = D.takes.filter(t => t.plan === 'post_first' && saved[t.id] && saved[t.id].d);
  const kept = a => a.filter(t => saved[t.id].d !== 'pass').length;
  const mx = Math.max(1, ...rej.map(r => r[1]));
  const bars = rej.map(([k, c]) => `<li><span>${esc(k)}</span><i style="--w:${(c / mx * 100).toFixed(0)}%"></i><b>${c}</b></li>`).join('');
  const kind = r => r.kind === 'human' ? 'Human reviewer' : 'Second AI (not a person)';
  const slotBias = j.average_place_by_slot ? Math.max(...Object.values(j.average_place_by_slot)) - Math.min(...Object.values(j.average_place_by_slot)) : null;
  const meter = (label, a, b) => b ? `<div class="meter-row"><span>${label}</span><div class="meter"><i style="--w:${Math.round(a / b * 100)}%"></i></div><b>${pct(a, b)}</b></div>` : '';
  const cov = q.coverage && q.coverage.episodes ? q.coverage : null;
  E.qualityPage.innerHTML = `
    <section class="hero-band" data-mark="%">
      <div class="hero-copy"><h1>Where the tool picks badly</h1>
        <p class="lede">Measured on this run, not promised. Every check says what it tests, what the number is, and what it cannot prove.</p></div>
      <dl class="stat-stack"><div><dt>Rules broken</dt><dd class="${q.violations ? 'bad' : 'good'}">${q.violations ?? 'n/a'}</dd></div><div><dt>Promos checked</dt><dd>${q.promos ?? D.takes.length}</dd></div>${v.ai ? `<div><dt>Cold viewer followed</dt><dd>${pct(v.ai.passed, v.ai.viewed)}</dd></div>` : ''}</dl>
    </section>
    ${runBanner()}
    <section class="q-grid">
      <article class="qc a"><h2>Hard rules</h2>${EMPTY ? '<p class="qbig">n/a</p><p>There are no promos to check. Nothing in this run has been judged, so there is no rule result to report.</p>' : `<p class="qbig ${q.violations ? 'bad' : 'good'}">${q.violations ?? 'n/a'} broken</p>
        <p>Across ${q.promos ?? D.takes.length} promos: 20 to 60 seconds, something in the first 3 seconds, no cut through a spoken line, no opening on a half-sentence. Code re-checks every promo, so this should be zero.</p>`}<p class="cant">Cannot prove the promo is good, only that it is legal.</p></article>
      <article class="qc b"><h2>Does it find the writers' own cliffhangers?</h2><p class="qbig">${w.labels ? `${w.hit_last_10s} of ${w.labels}` : 'n/a'}</p>
        ${w.labels ? meter('Promos ending within 10 s of one', w.hit_last_10s, w.labels) : ''}
        <p>The scripts' continuity notes flag some episode-ending cliffhangers. This counts promos that end within 10 seconds of one.</p><p class="cant">Cannot prove a viewer would stop scrolling.</p></article>
      <article class="qc c"><h2>Does a stranger follow it?</h2>
        ${v.ai ? meter('AI-picked cuts', v.ai.passed, v.ai.viewed) : '<p class="qbig">n/a</p>'}${v.rules && v.rules.viewed ? meter('Plain no-AI baseline', v.rules.passed, v.rules.viewed) : ''}
        <p>An AI that sees only the clip says what is happening and what it is waiting for. A pass means it understood.</p><p class="cant">Cannot prove the AI judge is right; it is another model.</p></article>
      <article class="qc d"><h2>Is the ranking judge steady?</h2><p class="qbig">${j.repeat_pair_agreement != null ? Math.round(j.repeat_pair_agreement * 100) + '%' : 'n/a'}</p>
        <p>When the same pair was compared twice in different positions, the judge agreed with itself this often${slotBias != null ? `. Position bias spread ${slotBias.toFixed(2)} (0 means none)` : ''}.</p><p class="cant">Cannot prove the order matches an editor's taste.</p></article>
    </section>
    <section class="band dark q-split">
      <div><h2>What it threw away, and why</h2>
        ${rej.length ? `<ul class="bars">${bars}</ul><p class="muted">Every rejected cut is kept in <code>rejected.json</code> so a person can overrule the tool.</p>` : '<p class="muted">Nothing was rejected in this run.</p>'}</div>
      <div class="cover"><p class="qbig">${cov ? `${cov.episodes_with_a_promo} of ${cov.episodes}` : 'n/a'}</p><p>scored episodes have a promo.</p></div>
    </section>
    <section class="band warm q-split">
      <div><h2>People against the tool</h2>
        ${(q.reviews || []).length ? `<ul class="rev">${q.reviews.map(r => `<li><b>${kind(r)}</b> rated ${r.n}: keep ${r.keep}, trim ${r.trim}, pass ${r.pass}.</li>`).join('')}</ul>
          ${q.agreement ? `<p class="muted">The two reviewers gave the same verdict on ${q.agreement.identical} of ${q.agreement.cuts} promos (Cohen's kappa ${q.agreement.kappa_three_way}). A second AI is not a stand-in for a person, so these are reported separately.</p>` : ''}`
          : '<p class="muted">No outside ratings were loaded with this run.</p>'}</div>
      <div class="yours"><h2>Your ratings in this browser</h2>
        ${rows.length ? `<p>You rated ${rows.length} of ${D.takes.length}: keep ${rows.filter(x => x.d === 'keep').length}, trim ${rows.filter(x => x.d === 'trim').length}, pass ${rows.filter(x => x.d === 'pass').length}.${keptTop.length ? ` Of the ${keptTop.length} "Post first" promos you rated, you kept or trimmed ${kept(keptTop)}.` : ''}</p>` : '<p class="muted">Rate promos on the Review page and your numbers appear here. Export them and run the tool with <code>--review</code> to score it against you.</p>'}</div>
    </section>
    <section class="band weak-band"><h2>Known weak spots</h2>
      <ul class="weak2">
        <li><b>It reads a script, not footage.</b><span>It cannot see acting, pacing or whether a face makes someone stop.</span></li>
        <li><b>The judges are models.</b><span>A strict judge can throw out a good cut; a lenient one can wave through a dull one. Without people rating cuts nobody knows which.</span></li>
        <li><b>One continuous stretch.</b><span>The brief allows joining moments across episodes. The current finder does not build joins; the older editor mode did, and it was less reliable.</span></li>
        <li><b>Timestamps come from the screenplay.</b><span>If the final edit drifts from it, every cut point drifts too.</span></li>
        <li><b>Small samples.</b><span>One show and one made-up demo so far. Treat the numbers as a first reading.</span></li>
      </ul></section>
    <section class="season-sec" id="seasonSec">${seasonHtml()}</section>`;
  E.qualityPage.querySelectorAll('[data-take]').forEach(b => b.addEventListener('click', () => showPromo(b.dataset.take)));
}

/* ---------- downloads: the original results, and the editor handoff ---------- */
const ORIGINAL_COLS = ['rank', 'post_slot', 'episode', 'segments_in_order', 'duration_seconds', 'hook', 'cliffhanger', 'why_it_works', 'why_this_slot', 'spoiler'];
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
function downloadResults(kind) {                      // exactly as the tool found them: never changed by trims or ratings
  const rows = sortedTakes().map(tk => ({
    rank: tk.rank, post_slot: PLAN_NAME[tk.plan], episode: tk.episode, segments_in_order: segTextWith(tk, origTrim(tk)),
    duration_seconds: +durWith(tk, origTrim(tk)).toFixed(1), hook: tk.ai.hook, cliffhanger: tk.ai.cliff, why_it_works: tk.ai.why, why_this_slot: tk.ai.planReason, spoiler: tk.ai.spoiler || 'none',
  }));
  download(kind, ORIGINAL_COLS, rows, {}, 'promos-original');
  toast(rows.length ? `Downloaded the original ${rows.length} promos.` : 'This run has no promos, so the file holds only the column names.');
}
function downloadHandoff(kind) {                      // your decisions and checked boundaries, ready for an editor
  const { rows, left, sum } = handoff();
  download(kind, HANDOFF_COLS, rows, { note: 'Passed cuts are left out. A moved cut keeps the original hook, cliffhanger and why, flagged for re-review. An invalid trim is reverted to the original boundaries.', summary: sum, left_out: left }, 'editor-handoff');
  toast(rows.length ? `Downloaded the editor handoff: ${rows.length} cut${rows.length > 1 ? 's' : ''}${left.length ? `, ${left.length} left out` : ''}.` : 'Nothing to hand off: every cut is marked Pass, or the run has no promos. The file holds only the column names.');
}

/* ---------- router ---------- */
function openTake(id) {
  if (ui.blind) setBlind(false);
  location.hash = '#/review';
  const i = order.findIndex(di => D.takes[di].id === id);
  setTimeout(() => go(Math.max(0, i), true), 30);
}
function route() {
  let v = (location.hash.match(/^#\/(\w+)/) || [])[1];
  if (v === 'new') { history.replaceState(null, '', '#/promos'); v = 'promos'; if (!E.newShow.open) E.newShow.showModal(); }   // old link: now a dialog
  if (v === 'season') { history.replaceState(null, '', '#/quality'); v = 'quality'; }                                    // old link: now a section
  view = VIEWS.includes(v) ? v : 'promos';
  E.app.dataset.view = view;
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('on', el.id === 'v-' + view));
  E.nav.querySelectorAll('a').forEach(a => { const on = a.dataset.nav === view; a.classList.toggle('on', on); if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  if (view !== 'review') stop();
  if (view !== 'promos') clearReel();
  if (view === 'promos') renderPromos();
  if (view === 'quality') renderQuality();
  if (view === 'review' && !EMPTY) go(cur, false);
  const sc = document.querySelector('.view.on'); if (sc) sc.scrollTop = 0;
  document.title = ({ promos: 'Promos', review: 'Review', quality: 'How good is it' })[view] + ' · ' + D.show.title + ' · Promo Finder';
}

/* ---------- start ---------- */
function init() {
  E.showTitle.textContent = D.show.title;
  if (D.show.demo) { const d = document.getElementById('demoPill'); d.hidden = false; }
  const n = D.takes.length;
  E.blindBtn.setAttribute('aria-pressed', ui.blind); E.app.classList.toggle('blind', ui.blind);
  wire();
  if (EMPTY) {                                                  // nothing to play or rate: say so, and keep every other page working
    E.app.classList.add('empty-run');
    document.getElementById('v-review').insertAdjacentHTML('beforeend', `<div class="review-empty"><h1>Nothing to review yet</h1>
      <p class="lede">No promo passed the checks in this run, so there is nothing to play or rate. The Promos page lists the timing-checked cuts an editor can still look at, and "How good is it" shows why each episode has none.</p>
      <div class="export-box" style="max-width:520px"><div><a class="pill primary" href="#/promos">See what was found</a><a class="pill" href="#/quality">How good is it</a></div></div></div>`);
  } else {
    buildOrder(); renderStrip(); renderFeed(); renderProgress();
    const firstOpen = order.findIndex(di => !(saved[D.takes[di].id] && saved[D.takes[di].id].d));   // resume where you left off
    cur = Math.max(0, firstOpen);
  }
  E.newBtn.addEventListener('click', () => E.newShow.showModal());
  window.addEventListener('hashchange', route);
  route();
}
init();
})();
