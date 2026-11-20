/* Promo Finder: one page, five views (Promos, Season, Quality, Run it, Review). Reads window.PROMO_DATA, written by build_data.py
   or handed over from memory by the in-page runner. Review's script and styles load the first time that tab opens. */
(() => {
'use strict';
const D = window.PROMO_DATA;
if (!D || !Array.isArray(D.takes) || (D.schema || 1) > 1) {       // a payload this page cannot read: say so instead of half-drawing
  document.body.insertAdjacentHTML('afterbegin', '<p style="padding:24px;font:16px system-ui">This results file was made by a different version of Promo Finder and cannot be shown here. Run the show again with this version.</p>');
  throw new Error('Unreadable PROMO_DATA (schema ' + (D && D.schema) + ')');
}
const SELF = document.currentScript && document.currentScript.src;        // where this script came from: sibling files load from there
const $ = (s, root = document) => root.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const unq = s => String(s ?? '').replace(/^["“]|["”]$/g, '');
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const pct = (n, d) => d ? Math.round(n / d * 100) + '%' : 'n/a';
const fmt = cs => { const s = Math.max(0, cs) / 100, m = Math.floor(s / 60); return String(m).padStart(2, '0') + ':' + (s - m * 60).toFixed(2).padStart(5, '0'); };
const mmss = cs => { const t = Math.round(Math.max(0, cs) / 100); return Math.floor(t / 60) + ':' + String(t % 60).padStart(2, '0'); };
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const PALETTE = [22, 340, 262, 200, 160, 46];                      // warm orange, rose, violet, blue, teal, gold
const PAIR = { 22: 262, 340: 215, 262: 22, 200: 22, 160: 300, 46: 262 };
const partner = h => PAIR[h] ?? (h + 200) % 360;
const hueOf = s => PALETTE[[...String(s)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7) % PALETTE.length];

const EMBED = !!window.PROMO_MEMORY_ONLY;                          // inside the Run it tab: this same page, fed from memory
if (EMBED) document.body.classList.add('embedded');
const RUN = D.run || {};
const Q = D.quality || {};
const EMPTY = !D.takes.length;                                     // a strict judge, or a provider that stopped, can leave zero promos
const NOAI = RUN.ai === false;                                     // timing rules only: candidates for an editor, not judged promos
const COV = D.coverage || [];
const PLAN_ORDER = ['post_first', 'library', 'hold_back', 'alternate'];
const PLAN_NAME = { post_first: 'Post first', library: 'Post later', hold_back: 'Held back for spoilers', alternate: 'Second versions' };
const PLAN_NOTE = {
  post_first: 'The strongest cut from each episode, earliest episodes first, because a new viewer lands on episode 1.',
  library: 'Good promos for after the first wave.',
  hold_back: 'These show a big twist. Save them for later.',
  alternate: 'The same moment as a stronger promo. Use one only if you want a second version.',
};
const takes = D.takes.slice().sort((a, b) => a.rank - b.rank);
const epsWith = new Set(takes.map(t => t.episode)).size;
const requested = RUN.requested ?? D.show.episodes;
const filter = { ep: 0 };

/* ---------- helpers ---------- */
const segLine = tk => tk.segments.map(s => `Episode ${s.episode}, ${fmt(s.start)} to ${fmt(s.end)}`).join(' then ');
const segKey = tk => tk.segments.map(s => `Ep ${s.episode} [${fmt(s.start)} – ${fmt(s.end)}]`).join(' + ');
const secs = tk => tk.segments.reduce((a, s) => a + (s.end - s.start), 0) / 100;
const hook = tk => unq(tk.ai.opening || tk.ai.hook);
let toastT = 0;
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('on'), 2400); }

function download(name, type, data) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}
const fileBase = () => (D.show.title || 'show').replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '').toLowerCase() + '-promos';
function rows() {
  return takes.map(tk => ({
    rank: tk.rank, post_slot: PLAN_NAME[tk.plan], episode: tk.episode, segments_in_order: segKey(tk), duration_s: Math.round(secs(tk) * 10) / 10,
    hook: unq(tk.ai.opening || tk.ai.hook), cliffhanger: tk.ai.cliff || '', why_it_works: tk.ai.why || '', why_this_slot: tk.ai.planReason || '',
    segments: tk.segments.map(s => ({ episode: s.episode, start: fmt(s.start), end: fmt(s.end) })),
  }));
}
function downloadCsv() {
  const cols = ['rank', 'post_slot', 'episode', 'segments_in_order', 'duration_s', 'hook', 'cliffhanger', 'why_it_works', 'why_this_slot'];
  const cell = v => { v = String(v ?? ''); if (/^[=+\-@]/.test(v)) v = "'" + v; return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };   // a leading = + - @ would run as a formula in a spreadsheet
  download(fileBase() + '.csv', 'text/csv;charset=utf-8', [cols.join(','), ...rows().map(r => cols.map(c => cell(r[c])).join(','))].join('\n') + '\n');
}
function downloadJson() { download(fileBase() + '.json', 'application/json', JSON.stringify({ show: D.show.title, promos: rows() }, null, 1) + '\n'); }

/* a promo anywhere in the app can be opened on the Promos page, scrolled to and expanded */
function openPromo(id) {
  filter.ep = 0; renderPromos(); location.hash = '#/promos';
  setTimeout(() => {
    const el = document.getElementById(id); if (!el) return;
    el.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' });
    el.classList.add('flash'); const d = el.querySelector('details'); if (d) d.open = true;
    setTimeout(() => el.classList.remove('flash'), 2200);
  }, 90);
}

/* ---------- promos: reel hero, ranked cards ---------- */
let reelT = 0, reelI = 0;
const clearReel = () => { clearTimeout(reelT); reelT = 0; };
function reelHtml(tk) {
  const h = hueOf(tk.episode);
  return `<button class="reel ph0" id="reelCard" type="button" style="--h:${h};--h2:${partner(h)}" aria-label="Open promo ${tk.rank}: ${esc(hook(tk))}">
      <span class="r-top"><b>${tk.rank}</b><span>Episode ${tk.episode}</span><span class="r-len">${Math.round(secs(tk))} s</span></span>
      <span class="r-label" id="reelLabel">The hook</span>
      <span class="r-hook">${esc(hook(tk))}</span>
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
  card.addEventListener('click', () => openPromo(tk.id));
  document.querySelectorAll('#promosPage .reel-dots button').forEach((b, k) => b.classList.toggle('on', k === reelI % top.length));
  const phase = (p, text) => { card.className = 'reel ph' + p; label.textContent = text; };
  if (reduced) { phase(3, 'Ends on'); return; }
  const steps = [[60, () => phase(1, 'The hook, first 3 seconds')], [3300, () => phase(2, 'The cut')], [4300, () => phase(3, 'Ends on')], [9500, () => { reelI++; playReel(top); }]];
  let at = 0;
  const go = k => { if (k >= steps.length) return; reelT = setTimeout(() => { steps[k][1](); go(k + 1); }, steps[k][0] - at); at = steps[k][0]; };
  go(0);
}
function runStrip() {
  const w = RUN.warnings || [], items = [['Episodes searched', `${requested} of ${RUN.pack ?? D.show.episodes}`]];
  if (RUN.ai) { items.push(['Scored by AI', RUN.scored != null ? String(RUN.scored) : 'n/a']); items.push(['Cuts judged', `${RUN.judged ?? 0} of ${RUN.candidates ?? 0}`]); }
  else items.push(['AI used', 'none, timing rules only']);
  items.push(['Shortlisted', String(RUN.shortlisted ?? takes.length)]);
  items.push(['Provider', RUN.ai ? (w.length ? 'interrupted' : 'no interruption') : 'not used']);
  return `<ul class="runstrip" aria-label="What happened in this run">${items.map(([a, b]) => `<li class="${a === 'Provider' && w.length ? 'warn' : ''}"><span>${esc(a)}</span><b>${esc(b)}</b></li>`).join('')}</ul>`;
}
function scriptHtml(tk) {
  return tk.segments.map((sg, i) => {
    const lines = (sg.cues || []).filter(c => c.s >= sg.start && c.s < sg.end).map(c => {
      const first3 = c.s < sg.start + 300;
      const label = c.k === 'd' ? `<b>${esc(c.who)}</b>` : `<i>${c.k === 'a' ? 'Action' : c.k === 'c' ? 'Camera' : 'Sound'}</i>`;
      return `<li class="${first3 ? 'f3' : ''}"><time>${fmt(c.s)}</time>${label}<span>${esc(c.text)}</span></li>`;
    }).join('');
    return `${tk.segments.length > 1 ? `<h4>Segment ${i + 1}: episode ${sg.episode}, ${fmt(sg.start)} to ${fmt(sg.end)}</h4>` : ''}<ol class="script">${lines}</ol>`;
  }).join('');
}
function promoHtml(tk) {
  const h = hueOf(tk.episode);
  return `<article class="promo" id="${esc(tk.id)}" style="--h:${h}">
    <header><b class="rank">${tk.rank}</b><span class="where">${esc(segLine(tk))}</span><span class="len">${Math.round(secs(tk))} s</span></header>
    <div class="open"><small>Opens on</small><q>${esc(hook(tk))}</q></div>
    <div class="cut" aria-hidden="true"></div>
    <div class="close"><small>Ends on</small><p>${esc(tk.ai.cliff || '')}</p></div>
    <p class="why"><b>Why it works</b> ${esc(tk.ai.why || 'No reason was written for this cut.')}</p>
    ${tk.ai.spoiler && tk.ai.spoiler !== 'none' ? `<p class="flag">Shows a ${esc(tk.ai.spoiler)} spoiler.</p>` : ''}
    <details><summary>Read the clip</summary><p class="muted">The first 3 seconds are highlighted.</p>${scriptHtml(tk)}</details>
    ${EMBED ? '' : `<p class="more"><a href="#/review/${esc(tk.id)}">Watch it play</a> <span class="muted">(optional review)</span></p>`}
  </article>`;
}
function extrasHtml() {
  const list = COV.filter(c => c.cut && c.status !== 'Viewer passed' && c.status !== 'Timing checked');
  if (!list.length) return '';
  return `<section class="group"><div class="group-head"><h2>Cuts for the other episodes</h2><span class="count">${list.length}</span>
    <p>The rules found a timing-checked cut in each of these episodes (20 to 60 seconds, a line in the first 3 seconds, no cut through a spoken line). Most were never judged by an AI, so treat them as material for an editor, not as finished promos.</p></div>
    <div class="table-wrap"><table class="extras"><thead><tr><th>Episode</th><th>Cut</th><th>Opens on</th><th>Ends on</th><th>Status</th></tr></thead><tbody>${list.map(c => `<tr>
      <td>${c.episode}</td><td class="tc">${c.cut.segments.map(s => `${esc(s.start)} to ${esc(s.end)}`).join(' + ')}</td><td>${esc(unq(c.cut.opening))}</td><td>${esc(unq(c.cut.ending))}</td><td>${c.status === 'Rules candidate' ? 'rules pick, not judged' : 'judged, not shortlisted: ' + esc(c.reason || c.status)}</td></tr>`).join('')}</tbody></table></div></section>`;
}
function renderPromos() {
  clearReel();
  const eps = [...new Set(takes.map(t => t.episode))].sort((a, b) => a - b);
  const shown = takes.filter(t => !filter.ep || t.episode === filter.ep);
  const groups = PLAN_ORDER.map(g => ({ g, list: shown.filter(t => t.plan === g) })).filter(x => x.list.length);
  const top = takes.slice(0, 3);
  const warn = (RUN.warnings || []).length ? `<div class="banner" role="status"><b>This run did not finish cleanly.</b><ul>${RUN.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul></div>` : '';
  const head = EMPTY ? 'No promo passed the checks' : NOAI ? `${plural(takes.length, 'candidate cut', 'candidate cuts')} to review` : `${plural(takes.length, 'promo', 'promos')}, ready to post`;
  const lede = EMPTY ? `Nothing from ${esc(D.show.title)} reached the shortlist in this run.`
    : NOAI ? `Found by timing rules with no AI, from ${epsWith} of ${requested} episodes of ${esc(D.show.title)}. They are material for an editor, ordered by a simple word-based score; nobody has judged them as promos.`
    : `Found in ${epsWith} of the ${requested} episodes searched, from ${esc(D.show.title)}. Start with the first, then work down. Each opens on a hook within its first 3 seconds and stops on an unanswered question.`;
  const v = Q.viewer && Q.viewer.ai;
  const proof = [[Q.violations ?? 'n/a', 'rule breaks across all clips'], ...(v && v.viewed ? [[pct(v.passed, v.viewed), 'followed by a first-time viewer']] : []),
    ...(Q.writer && Q.writer.labels ? [[`${Q.writer.hit_last_10s} of ${Q.writer.labels}`, "writers' own cliffhangers found"]] : []), [`${epsWith} of ${requested}`, 'episodes searched have a promo']];
  const stage = EMPTY ? '' : `<div class="reel-stage"><button class="reel ph0" id="reelCard" type="button"><span id="reelLabel"></span></button>
      <div class="reel-dots" role="group" aria-label="Preview another promo">${top.map(t => `<button type="button" aria-label="Preview promo ${t.rank}"></button>`).join('')}</div>
      <p class="reel-note">The top ${top.length}, as they would run: the hook, the cut, then the cliffhanger. Click one to open it.</p></div>`;
  $('#promosPage').innerHTML = `
    <section class="hero-band">
      <div class="hero-copy">
        <h1>${esc(head)}</h1>
        <p class="lede">${lede}</p>
        ${runStrip()}
        <div class="actions"><button class="pill primary" id="dlCsv" type="button"${EMPTY ? ' disabled' : ''}>Download CSV</button><button class="pill" id="dlJson" type="button"${EMPTY ? ' disabled' : ''}>Download JSON</button>${EMBED ? '' : '<a class="pill" href="#/season">See every episode</a>'}</div>
        ${EMPTY ? '' : `<ul class="proof">${proof.map(([a, b]) => `<li><b>${esc(a)}</b><span>${esc(b)}</span></li>`).join('')}</ul>`}
        ${EMBED || EMPTY ? '' : '<p class="opt-note">An optional next step, beyond what the task asks: <a href="#/review">Review</a> plays each promo as it would run, lets you nudge its cut to a clean line break and mark keep, trim or pass, then hands an editor the list.</p>'}
      </div>
      ${stage}
    </section>
    ${warn}
    ${EMPTY || NOAI ? '' : `<details class="how"><summary>How the order was decided</summary><ul>
      <li><b>One strong cut per episode goes first</b>, earliest episodes first, because a new viewer lands on episode 1.</li>
      <li><b>Cuts a stranger could not follow are dropped.</b> A model that sees only the clip has to say what is happening and what it is waiting for.</li>
      <li><b>Big twists are held back</b> so a promo does not spoil the show.</li>
      <li><b>Overlapping cuts become second versions</b> instead of repeating a moment.</li></ul></details>`}
    ${EMPTY || eps.length < 2 ? '' : `<div class="chips" role="group" aria-label="Filter by episode"><button class="chip" type="button" data-ep="0" aria-pressed="${!filter.ep}">All episodes</button>${eps.map(e => `<button class="chip" type="button" data-ep="${e}" aria-pressed="${filter.ep === e}">Episode ${e}</button>`).join('')}</div>`}
    ${groups.map(({ g, list }) => `<section class="group"><div class="group-head"><h2>${PLAN_NAME[g]}</h2><span class="count">${list.length}</span><p>${PLAN_NOTE[g]}</p></div><div class="cards">${list.map(promoHtml).join('')}</div></section>`).join('')}
    ${filter.ep ? '' : extrasHtml()}`;
  $('#dlCsv').addEventListener('click', downloadCsv);
  $('#dlJson').addEventListener('click', downloadJson);
  document.querySelectorAll('#promosPage [data-ep]').forEach(b => b.addEventListener('click', () => { filter.ep = +b.dataset.ep; renderPromos(); }));
  reelI = 0;
  if (top.length && !EMPTY) {
    document.querySelectorAll('#promosPage .reel-dots button').forEach((b, k) => b.addEventListener('click', () => { reelI = k; playReel(top); }));
    const box = $('#promosPage .reel-stage');
    box.addEventListener('mouseenter', () => { if (!reduced) clearReel(); });
    box.addEventListener('mouseleave', () => { if (!reduced && ['', 'promos'].includes(location.hash.replace(/^#\/?/, '').split('/')[0])) { reelI++; playReel(top); } });
    playReel(top);
  }
}

/* ---------- season: one row per episode, the promos drawn where they sit in it ---------- */
const trackSvg = ep => {
  const bars = (ep.pulse || []).map(([p, h, c]) => { const x = (p * 1000).toFixed(1), top = 54 - Math.max(h, c) * 15;
    return `<line x1="${x}" x2="${x}" y1="56" y2="${top.toFixed(1)}" stroke="${h >= c ? '#ff641c' : '#f8c543'}" stroke-width="2.4" stroke-linecap="round" vector-effect="non-scaling-stroke"/>`; }).join('');
  return `<svg class="ep-pulse" viewBox="0 0 1000 60" preserveAspectRatio="none" aria-hidden="true">${bars}</svg>`;
};
function renderSeason() {
  const covered = D.episodes.filter(e => e.takes.length).length;
  const row = ep => {
    const mine = ep.takes.map(id => D.takes.find(t => t.id === id)).filter(Boolean), dur = Math.max(1, ep.duration);
    const brackets = mine.flatMap(tk => tk.segments.filter(sg => sg.episode === ep.n).map(sg => {
      const l = (sg.start / dur * 100).toFixed(2), w = Math.max(1.2, (sg.end - sg.start) / dur * 100).toFixed(2);
      return `<button class="br" type="button" data-take="${esc(tk.id)}" style="left:${l}%;width:${w}%" aria-label="Promo ${tk.rank}, ${mmss(sg.start)} to ${mmss(sg.end)}"><i>${tk.rank}</i></button>`; })).join('');
    const c = COV.find(x => x.episode === ep.n);
    const state = mine.length ? `<span class="tag good">${NOAI ? plural(mine.length, 'candidate', 'candidates') : plural(mine.length, 'promo', 'promos')}</span>`
      : !c ? '<span class="tag">not searched</span>'
      : c.status === 'Rules candidate' ? '<span class="tag">rules pick, not judged</span>'
      : c.status === 'No eligible cut' ? '<span class="tag bad">no eligible cut</span>' : `<span class="tag warn">${esc(c.status.toLowerCase())}</span>`;
    const cand = !mine.length && c && c.cut ? c.cut.segments.map(sg => `<span class="br unjudged" title="A timing-checked cut that was not judged: ${esc(sg.start)} to ${esc(sg.end)}" style="left:${(sg.start_cs / dur * 100).toFixed(2)}%;width:${Math.max(1.2, (sg.end_cs - sg.start_cs) / dur * 100).toFixed(2)}%"></span>`).join('') : '';
    const why = !mine.length && c ? `<p class="ep-why">${esc(c.reason)}${c.cut ? ' The timing-checked cut is drawn dashed.' : ''}</p>` : '';
    return `<li class="eprow ${mine.length ? 'has' : 'gap'}"><div class="ep-id"><b>${String(ep.n).padStart(2, '0')}</b><span>${mmss(ep.duration)}</span></div>
      <div class="ep-body"><p class="ep-log">${esc(ep.logline || 'No logline in the script.')}</p>${why}<div class="ep-track">${ep.scored ? trackSvg(ep) : ''}<span class="ep-base"></span>${brackets}${cand}</div></div>
      <div class="ep-side">${state}${mine[0] ? `<button class="pill" type="button" data-take="${esc(mine[0].id)}">Open</button>` : ''}</div></li>`;
  };
  $('#seasonPage').innerHTML = `
    <section class="hero">
      <h1>Every episode at a glance</h1>
      <p class="lede">Each row is one episode, start to end. The orange and gold lines are where the AI saw a good place to open a clip or end one; the boxes are the promos, placed where they sit in the episode.</p>
      <ul class="facts"><li><b>${covered} of ${D.episodes.length}</b><span>episodes have a promo</span></li><li><b>${D.takes.length}</b><span>promos in total</span></li></ul>
    </section>
    <section class="legend"><span><i class="lg o"></i>Good place to open</span><span><i class="lg g"></i>Good place to end</span><span><i class="lg b"></i>A promo, numbered by rank</span><span><i class="lg d"></i>A cut nobody has judged</span><span class="muted">Taller lines are stronger.</span></section>
    <ol class="eprows">${D.episodes.map(row).join('')}</ol>
    ${EMBED ? '' : '<p class="page-end">Where the tool picks badly, measured: <a href="#/quality">Quality</a></p>'}`;
  document.querySelectorAll('#seasonPage [data-take]').forEach(b => b.addEventListener('click', () => openPromo(b.dataset.take)));
}

/* ---------- quality: a funnel, four checks, the weak spots ---------- */
function renderQuality() {
  const w = Q.writer || {}, cov = Q.coverage || {};
  const rej = Object.entries(Q.rejections || {}), noPair = rej.filter(([k]) => /no legal/i.test(k)).reduce((a, [, c]) => a + c, 0);
  const cuts = rej.filter(([k]) => !/no legal/i.test(k));
  const kept = RUN.shortlisted ?? takes.length, lost = cuts.reduce((a, [, c]) => a + c, 0), total = RUN.candidates ?? kept + lost;
  const segs = [['Kept', kept, 'keep'], ...cuts.map(([k, c]) => [k, c, 'drop'])].filter(s => s[1] > 0);
  const human = (Q.reviews || []).find(r => r.n);
  const covered = cov.episodes ? `${cov.episodes_with_a_promo} of ${cov.episodes}` : `${epsWith} of ${requested}`;
  const check = (name, big, cls, what, cant) => `<div class="check"><h3>${name}</h3><p class="check-n ${cls || ''}">${big}</p><p class="check-t">${what}<em>${cant}</em></p></div>`;
  $('#qualityPage').innerHTML = `
    <section class="hero">
      <h1>Where the tool picks badly</h1>
      <p class="lede">Measured on this run, not promised. Each check says what it tests, what the number is, and what it cannot prove.</p>
    </section>

    ${EMPTY || !segs.length ? '' : `<section class="funnel-band">
      <h2><b>${total}</b> cuts were found. <b>${kept}</b> made the list.</h2>
      <div class="funnel" role="img" aria-label="${kept} kept out of ${total}">${segs.map(([k, c, t]) => `<span class="fseg ${t}" style="flex:${c} 1 0" title="${esc(k)}: ${c}"><b>${c}</b></span>`).join('')}</div>
      <ul class="flegend">${segs.map(([k, c, t]) => `<li class="${t}"><i></i><b>${c}</b> ${esc(k)}</li>`).join('')}</ul>
      <p class="muted">${noPair ? `In ${plural(noPair, 'episode', 'episodes')} no legal opening and ending pair existed at all. ` : ''}Every rejected cut is kept in <code>rejected.json</code> so a person can overrule the tool.</p>
    </section>`}

    <section class="checks" aria-label="The checks">
      ${check('Hard rules', EMPTY ? 'n/a' : `${Q.violations ?? 'n/a'} broken`, Q.violations ? 'bad' : 'good', `Across ${Q.promos ?? takes.length} promos: 20 to 60 seconds, a line in the first 3 seconds, no cut through a spoken line, no opening on half a sentence. Separate code re-checks every promo.`, 'Cannot show a promo is good, only that it is legal.')}
      ${check("The writers' own cliffhangers", w.labels ? `${w.hit_last_10s} of ${w.labels}` : 'n/a', '', "The scripts' continuity notes name some episode-ending cliffhangers. This counts promos that end within 10 seconds of one.", 'Cannot show a viewer would stop scrolling.')}
      ${check('Episodes covered', covered, '', `Episodes searched that ended with at least one promo.${EMBED ? '' : ' <a href="#/season">Season</a> lists the rest with the reason.'}`, 'A search of every episode is not a promo in every episode.')}
      ${check('Posting order', 'Unchecked', '', `The order comes from the tool's own scoring. Nobody has compared it with what an editor would post first${human ? `; one person's blind check of ${human.n} cuts: keep ${human.keep}, trim ${human.trim}, pass ${human.pass}` : ''}.`, 'Treat it as a suggestion.')}
    </section>

    <section class="weak-band">
      <h2>Known weak spots</h2>
      <ul class="weak">
        <li><b>It reads a script, not footage.</b> It cannot see acting, pacing or whether a face makes someone stop. Every time is only as good as the script's timing.</li>
        <li><b>The reasons are written by a model.</b> They read well and are not verified against the clip.</li>
        <li><b>It can judge too strictly, or too kindly.</b> A cut can be rejected for an ending that answers itself when an editor would still use it, and a judge from the same provider as the scorer passes more than an independent one does.</li>
        <li><b>One continuous stretch per promo.</b> Joining moments from several episodes is not built.</li>
      </ul>
      ${EMBED ? '' : '<p class="page-end"><a href="#/season">Every episode, one row: Season</a></p>'}
    </section>`;
}

/* ---------- run it: bring any show, get its promos, all in this tab ---------- */
const R = { cfg: undefined, worker: null, ready: false, runId: 0, active: 0, zip: null, zipName: 'promo-finder-run.zip', startedAt: 0, watchdog: 0 };
const rel = p => (SELF ? SELF.slice(0, SELF.lastIndexOf('/') + 1) : '') + p;
const show = (node, on) => { node.hidden = !on; };
const runSay = t => { const s = $('#runStatus'); s.textContent = t; show(s, !!t); };
function runFail(msg) { const p = document.createElement('p'), b = document.createElement('b'); b.textContent = msg; p.appendChild(b); $('#runError').replaceChildren(p); show($('#runError'), true); runBusy(false); runSay(''); }
function runBusy(on) {
  $('#drop').classList.toggle('busy', on);
  document.querySelectorAll('#v-run input, #v-run textarea, #v-run [data-example], #pasteGo').forEach(el => { el.disabled = on; });
  show($('#runCancel'), on);
}
async function runConfig() {
  if (R.cfg !== undefined) return R.cfg;
  try { const r = await fetch(rel('run/version.json')); R.cfg = r.ok ? await r.json() : null; } catch (e) { R.cfg = null; }
  if (R.cfg && !R.cfg.worker) R.cfg = null;
  return R.cfg;
}
function runBoot() {
  if (R.worker) return;
  R.worker = new Worker(new URL(rel('run/' + R.cfg.worker), location.href), { type: 'module' });
  R.worker.onmessage = onRunMessage;
  R.worker.onerror = e => { e.preventDefault(); runCrashed('The worker stopped (' + (e.message || 'unknown error') + ').'); };
  R.worker.onmessageerror = () => runCrashed('The worker sent a message this page could not read.');
}
function runStop() { clearTimeout(R.watchdog); if (R.worker) { R.worker.terminate(); R.worker = null; R.ready = false; } }
function runCrashed(why) { runStop(); R.active = 0; show($('#runStart'), false); show($('#runResult'), false); show($('#runFallback'), true); $('#runFallbackWhy').textContent = why; }
function onRunMessage(event) {
  const m = event.data;
  if (m.type === 'ready') { R.ready = true; clearTimeout(R.watchdog); return; }
  if (m.type === 'status') { if (!m.id || m.id === R.active) runSay(m.text); return; }
  if (m.id !== R.active) return;                       // a late answer from a run that was cancelled or replaced: ignore it
  if (m.type === 'log') { const line = m.line.trim(); if (/^episode \d+/i.test(line)) runSay('Working on ' + line.replace(/:.*/, '') + '...'); return; }
  if (m.type === 'error') { if (m.kind === 'engine') runCrashed(m.message); else runFail(m.message); return; }
  if (m.type === 'done') runDone(m);
}
function runDone(m) {
  let payload;
  try {
    payload = JSON.parse(m.payload);
    if (!(payload && payload.schema === 1 && Array.isArray(payload.takes) && Array.isArray(payload.episodes) && payload.show && typeof payload.show.title === 'string')) throw new Error('The finder returned an answer this page cannot read.');
  } catch (e) { runFail(e.message); return; }
  R.zip = m.zip;
  R.zipName = payload.show.title.replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '').toLowerCase() + '-promo-finder-run.zip';
  window.__PROMO_PAYLOAD = payload;                    // read by the results frame through its bootstrap, never stored
  const n = payload.takes.length;
  $('#rTitle').textContent = payload.show.title;
  $('#rMeta').textContent = ' ' + (n ? `${plural(n, 'rules candidate', 'rules candidates')} from ${plural(payload.show.episodes, 'episode', 'episodes')}. No AI ran.` : `No candidate passed the checks in ${plural(payload.show.episodes, 'episode', 'episodes')}. No AI ran.`);
  show($('#runStart'), false); show($('#runFallback'), false); show($('#runResult'), true);
  const f = $('#runView'); f.hidden = false; f.src = rel('run/view.html');
  runBusy(false); runSay('');
  $('#runAgain').focus();
}
function runReset() {
  R.active = 0; window.__PROMO_PAYLOAD = null; R.zip = null;
  const f = $('#runView'); f.removeAttribute('src'); f.hidden = true;
  show($('#runResult'), false); show($('#runError'), false); show($('#runFallback'), false); show($('#runStart'), true);
  runBusy(false); runSay('');
  document.querySelectorAll('#v-run input[type=file]').forEach(i => { i.value = ''; });
}
function runStart(name, buffer) {
  show($('#runError'), false);
  if (!buffer.byteLength) return runFail('That file is empty.');
  if (buffer.byteLength > 25_000_000) return runFail(`That is ${(buffer.byteLength / 1e6).toFixed(1)} MB. The in-page runner takes up to 25 MB; use the command line for bigger shows.`);
  runBoot(); runBusy(true);
  R.active = ++R.runId; R.startedAt = performance.now();
  runSay(R.ready ? 'Finding the promos...' : 'Starting the finder (the first run loads about 12 MB)...');
  if (!R.ready) { clearTimeout(R.watchdog); R.watchdog = setTimeout(() => { if (!R.ready) runCrashed('The runtime took longer than 90 seconds to load. Check your connection and try again.'); }, 90000); }
  R.worker.postMessage({ type: 'run', id: String(R.active), name, buffer }, [buffer]);
  R.active = String(R.active);
}

/* a store-only ZIP, so several episode files (or a whole folder) travel to the finder as one input */
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = d => { let c = ~0; for (let i = 0; i < d.length; i++) c = CRC[(c ^ d[i]) & 255] ^ (c >>> 8); return ~c >>> 0; };
function makeZip(files) {
  const enc = new TextEncoder(), parts = [], central = []; let offset = 0;
  for (const f of files) {
    const name = enc.encode(f.name), crc = crc32(f.data), size = f.data.length;
    const h = new DataView(new ArrayBuffer(30));
    h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x0800, true); h.setUint16(12, 0x21, true);
    h.setUint32(14, crc, true); h.setUint32(18, size, true); h.setUint32(22, size, true); h.setUint16(26, name.length, true);
    parts.push(new Uint8Array(h.buffer), name, f.data);
    const c = new DataView(new ArrayBuffer(46));
    c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint16(8, 0x0800, true); c.setUint16(14, 0x21, true);
    c.setUint32(16, crc, true); c.setUint32(20, size, true); c.setUint32(24, size, true); c.setUint16(28, name.length, true); c.setUint32(42, offset, true);
    central.push(new Uint8Array(c.buffer), name);
    offset += 30 + name.length + size;
  }
  const cdSize = central.reduce((a, b) => a + b.length, 0), e = new DataView(new ArrayBuffer(22));
  e.setUint32(0, 0x06054b50, true); e.setUint16(8, files.length, true); e.setUint16(10, files.length, true); e.setUint32(12, cdSize, true); e.setUint32(16, offset, true);
  const all = [...parts, ...central, new Uint8Array(e.buffer)], out = new Uint8Array(all.reduce((a, b) => a + b.length, 0));
  let p = 0; for (const b of all) { out.set(b, p); p += b.length; }
  return out;
}
async function bring(files) {                          // files: File[] from a picker, a folder or a drop
  const ok = files.filter(f => /\.(txt|zip)$/i.test(f.name)), zips = ok.filter(f => /\.zip$/i.test(f.name)), txts = ok.filter(f => /\.txt$/i.test(f.name));
  if (!ok.length) return runFail('Bring .txt episodes, a folder of them, or one .zip. Other formats are not read yet.');
  if (zips.length && (zips.length > 1 || txts.length)) return runFail('Bring either one .zip or several .txt episodes, not both.');
  if (zips.length) return runStart(zips[0].name, await zips[0].arrayBuffer());
  if (txts.length === 1) return runStart(txts[0].name, await txts[0].arrayBuffer());
  if (txts.length > 200) return runFail('That is more than 200 episodes. Use the command line for a bigger show.');
  const seen = new Map(), entries = await Promise.all(txts.map(async f => {
    const n = (seen.get(f.name) || 0) + 1; seen.set(f.name, n);
    return { name: n > 1 ? `${n}-${f.name}` : f.name, data: new Uint8Array(await f.arrayBuffer()) };
  }));
  runStart('episodes.zip', makeZip(entries).buffer);
}
async function filesFromDrop(dt) {                     // a dropped folder arrives as an entry tree; flatten it
  const out = [];
  const walk = async entry => {
    if (entry.isFile) out.push(await new Promise((ok, bad) => entry.file(ok, bad)));
    else if (entry.isDirectory) {
      const reader = entry.createReader();
      for (;;) { const batch = await new Promise((ok, bad) => reader.readEntries(ok, bad)); if (!batch.length) break; for (const e of batch) await walk(e); }
    }
  };
  const items = [...(dt.items || [])].map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (items.length) { for (const e of items) await walk(e); return out; }
  return [...(dt.files || [])];
}
async function initRun() {
  const cfg = await runConfig();
  if (!cfg) { show($('#runStart'), false); show($('#runUnavailable'), true); return; }
  document.querySelectorAll('.run-tabs button').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('.run-tabs button').forEach(x => x.setAttribute('aria-selected', String(x === b)));
    document.querySelectorAll('.run-panel').forEach(p => { p.hidden = p.id !== 'panel-' + b.dataset.panel; });
  }));
  $('#fileIn').addEventListener('change', e => { const f = [...e.target.files]; if (f.length) bring(f); });
  $('#dirIn').addEventListener('change', e => { const f = [...e.target.files]; if (f.length) bring(f); });
  const drop = $('#drop');
  ['dragenter', 'dragover'].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', async e => { e.preventDefault(); const f = await filesFromDrop(e.dataTransfer); if (f.length) bring(f); });
  $('#pasteGo').addEventListener('click', () => {
    const text = $('#pasteIn').value.trim();
    if (!text) return runFail('Paste a script first.');
    runStart('pasted-episode.txt', new TextEncoder().encode(text).buffer);
  });
  document.querySelectorAll('[data-example]').forEach(b => b.addEventListener('click', async () => {
    try { const r = await fetch(rel('run/examples/' + b.dataset.example)); if (!r.ok) throw new Error('The example could not be loaded (' + r.status + ').'); runStart(b.dataset.example, await r.arrayBuffer()); }
    catch (e) { runFail(e.message); }
  }));
  $('#runCancel').addEventListener('click', () => { runStop(); runReset(); runSay('Cancelled. Nothing was kept.'); setTimeout(() => runSay(''), 2500); });
  $('#runAgain').addEventListener('click', runReset);
  $('#runRetry').addEventListener('click', runReset);
  $('#dlZip').addEventListener('click', () => { if (R.zip) download(R.zipName, 'application/zip', R.zip); });
  window.addEventListener('pagehide', () => { window.__PROMO_PAYLOAD = null; });
}

/* ---------- review: loaded the first time its tab opens ---------- */
let reviewLoading = null;
function loadReview() {
  if (window.PromoReview) return Promise.resolve();
  if (!reviewLoading) reviewLoading = new Promise((ok, bad) => {
    const v = SELF && /\?v=\d+/.test(SELF) ? SELF.match(/\?v=\d+/)[0] : '';
    const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = rel('review.css') + v; document.head.appendChild(l);
    const s = document.createElement('script'); s.src = rel('review.js') + v; s.onload = ok; s.onerror = () => bad(new Error('review.js could not load'));
    document.body.appendChild(s);
  });
  return reviewLoading;
}

/* ---------- pages ---------- */
const VIEWS = EMBED ? ['promos', 'season', 'quality'] : ['promos', 'season', 'quality', 'run', 'review'];
const TITLES = { promos: 'Promos', season: 'Season', quality: 'Quality', run: 'Run it', review: 'Review (optional)' };
function route() {
  const parts = location.hash.replace(/^#\/?/, '').split('/'), h = parts[0] || 'promos';
  const v = VIEWS.includes(h) ? h : 'promos';
  VIEWS.forEach(n => { $('#v-' + n).classList.toggle('on', n === v); });
  document.querySelectorAll('#nav a').forEach(a => { const on = a.dataset.nav === v; a.classList.toggle('on', on); if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  if (v === 'review') loadReview().then(() => window.PromoReview.start(parts[1] ? decodeURIComponent(parts[1]) : null)).catch(() => toast('The review studio could not load.'));
  else if (window.PromoReview) window.PromoReview.stop();
  if (v === 'promos') { if (!reelT && $('#reelCard')) playReel(takes.slice(0, 3)); } else clearReel();
  const sc = $('#v-' + v); if (sc && v !== 'review') sc.scrollTop = 0;
  document.title = TITLES[v] + ' · ' + D.show.title + ' · Promo Finder';
}
function init() {
  $('#showTitle').textContent = D.show.title;
  if (D.show.demo) $('#demoPill').hidden = false;
  if (EMBED) { ['run', 'review'].forEach(n => { $('#v-' + n).remove(); const a = document.querySelector(`[data-nav="${n}"]`); if (a) a.remove(); }); }
  renderPromos(); renderSeason(); renderQuality();
  if (!EMBED) initRun();
  window.addEventListener('hashchange', route);
  if (location.hash.length <= 2) history.replaceState(null, '', '#/promos');
  route();
}
init();
})();
