/* Promo Finder results page: the ranked promos, the quality checks, and how to run it on another show.
   Reads window.PROMO_DATA (written by build_data.py, or handed over from memory by the in-browser runner). */
(() => {
'use strict';
const D = window.PROMO_DATA;
if (!D || !Array.isArray(D.takes) || (D.schema || 1) > 1) {       // a payload this page cannot read: say so instead of half-drawing
  document.body.insertAdjacentHTML('afterbegin', '<p style="padding:24px;font:16px system-ui">This results file was made by a different version of Promo Finder and cannot be shown here. Run the show again with this version.</p>');
  throw new Error('Unreadable PROMO_DATA (schema ' + (D && D.schema) + ')');
}
const $ = (s, root = document) => root.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const unq = s => String(s ?? '').replace(/^["“]|["”]$/g, '');
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const fmt = cs => { const s = Math.max(0, cs) / 100, m = Math.floor(s / 60); return String(m).padStart(2, '0') + ':' + (s - m * 60).toFixed(2).padStart(5, '0'); };

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

function download(name, type, text) {
  const url = URL.createObjectURL(new Blob([text], { type }));
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

/* ---------- promos ---------- */
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
  return `<article class="promo" id="${esc(tk.id)}">
    <header><b class="rank">${tk.rank}</b><span class="where">${esc(segLine(tk))}</span><span class="len">${Math.round(secs(tk))} s</span></header>
    <div class="open"><small>Opens on</small><q>${esc(hook(tk))}</q></div>
    <div class="cut" aria-hidden="true"></div>
    <div class="close"><small>Ends on</small><p>${esc(tk.ai.cliff || '')}</p></div>
    <p class="why"><b>Why it works</b> ${esc(tk.ai.why || 'No reason was written for this cut.')}</p>
    ${tk.ai.spoiler && tk.ai.spoiler !== 'none' ? `<p class="flag">Shows a ${esc(tk.ai.spoiler)} spoiler.</p>` : ''}
    <details><summary>Read the clip</summary><p class="muted">The first 3 seconds are highlighted.</p>${scriptHtml(tk)}</details>
    ${window.PROMO_MEMORY_ONLY ? '' : `<p class="more"><a href="review/#${esc(tk.id)}">Watch it play (optional review)</a></p>`}
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
  const eps = [...new Set(takes.map(t => t.episode))].sort((a, b) => a - b);
  const shown = takes.filter(t => !filter.ep || t.episode === filter.ep);
  const groups = PLAN_ORDER.map(g => ({ g, list: shown.filter(t => t.plan === g) })).filter(x => x.list.length);
  const warn = (RUN.warnings || []).length ? `<div class="banner" role="status"><b>This run did not finish cleanly.</b><ul>${RUN.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul></div>` : '';
  const head = EMPTY ? 'No promo passed the checks' : NOAI ? plural(takes.length, 'candidate cut', 'candidate cuts') : plural(takes.length, 'promo', 'promos');
  const lede = EMPTY ? `Nothing from ${esc(D.show.title)} reached the shortlist in this run.`
    : NOAI ? `Found by timing rules with no AI, from ${epsWith} of ${requested} episodes. They are material for an editor, ordered by a simple word-based score; nobody has judged them as promos.`
    : `Found in ${epsWith} of the ${requested} episodes searched. Each opens on a hook within its first 3 seconds and stops on an unanswered question. They are listed in the order to post them.`;
  const facts = [[`${requested} of ${RUN.pack ?? D.show.episodes}`, 'episodes searched'], [Q.violations ?? 'n/a', 'rule breaks'],
    ...(Q.writer && Q.writer.labels ? [[`${Q.writer.hit_last_10s} of ${Q.writer.labels}`, "writers' cliffhangers found"]] : [])];
  $('#promosPage').innerHTML = `
    <section class="hero">
      <h1>${esc(head)}</h1>
      <p class="lede">${lede}</p>
      <ul class="facts">${facts.map(([a, b]) => `<li><b>${esc(a)}</b><span>${esc(b)}</span></li>`).join('')}</ul>
      ${window.PROMO_MEMORY_ONLY ? '' : '<p class="opt-note">An optional next step, beyond what the task asks: <a href="review/">Review</a> plays each promo as it would run, lets you nudge its cut to a clean line break and mark keep, trim or pass, then hands an editor the list.</p>'}
      <div class="actions"><button class="pill primary" id="dlCsv" type="button"${EMPTY ? ' disabled' : ''}>Download CSV</button><button class="pill" id="dlJson" type="button"${EMPTY ? ' disabled' : ''}>Download JSON</button></div>
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
}


/* ---------- season: one row per episode, the promos drawn where they sit in it ---------- */
const mmss = cs => { const t = Math.round(Math.max(0, cs) / 100); return Math.floor(t / 60) + ':' + String(t % 60).padStart(2, '0'); };
const trackSvg = ep => {
  const bars = (ep.pulse || []).map(([p, h, c]) => { const x = (p * 1000).toFixed(1), top = 54 - Math.max(h, c) * 15;
    return `<line x1="${x}" x2="${x}" y1="56" y2="${top.toFixed(1)}" stroke="${h >= c ? '#ff641c' : '#f8c543'}" stroke-width="2.4" stroke-linecap="round" vector-effect="non-scaling-stroke"/>`; }).join('');
  return `<svg class="ep-pulse" viewBox="0 0 1000 60" preserveAspectRatio="none" aria-hidden="true">${bars}</svg>`;
};
function openPromo(id) {
  filter.ep = 0; location.hash = '#/promos'; renderPromos();
  setTimeout(() => {
    const el = document.getElementById(id); if (!el) return;
    el.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    el.classList.add('flash'); const d = el.querySelector('details'); if (d) d.open = true;
    setTimeout(() => el.classList.remove('flash'), 2200);
  }, 80);
}
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
    <ol class="eprows">${D.episodes.map(row).join('')}</ol>`;
  document.querySelectorAll('#seasonPage [data-take]').forEach(b => b.addEventListener('click', () => openPromo(b.dataset.take)));
}

/* ---------- quality ---------- */
function renderQuality() {
  const w = Q.writer || {}, rej = Object.entries(Q.rejections || {}), cov = Q.coverage || {};
  const mx = Math.max(1, ...rej.map(r => r[1]));
  const human = (Q.reviews || []).find(r => r.n);
  const covered = new Set(takes.map(t => t.episode));
  const epRow = e => {
    const c = COV.find(x => x.episode === e.n), mine = takes.filter(t => t.episode === e.n);
    const state = mine.length ? plural(mine.length, 'promo', 'promos') + ' (rank ' + mine.map(t => t.rank).join(', ') + ')'
      : c && c.status === 'Rules candidate' ? 'rules cut, not judged' : c ? esc(c.status) : 'not searched';
    return `<tr class="${mine.length ? 'has' : ''}"><td>${e.n}</td><td>${state}</td><td>${mine.length ? '' : esc((c && c.reason) || '')}</td></tr>`;
  };
  $('#qualityPage').innerHTML = `
    <section class="hero">
      <h1>Where the tool picks badly</h1>
      <p class="lede">Measured on this run, not promised. Each check says what it tests, what the number is, and what it cannot prove.</p>
    </section>
    <section class="q-grid">
      <article class="qc"><h2>Hard rules</h2>
        <p class="qbig ${Q.violations ? 'bad' : 'good'}">${EMPTY ? 'n/a' : (Q.violations ?? 'n/a') + ' broken'}</p>
        <p>Across ${Q.promos ?? takes.length} promos: 20 to 60 seconds, a line in the first 3 seconds, no cut through a spoken line, no opening on half a sentence. Separate code re-checks every promo.</p>
        <p class="cant">Cannot show a promo is good, only that it is legal.</p></article>
      <article class="qc"><h2>The writers' own cliffhangers</h2>
        <p class="qbig">${w.labels ? `${w.hit_last_10s} of ${w.labels}` : 'n/a'}</p>
        <p>The scripts' continuity notes name some episode-ending cliffhangers. This counts promos that end within 10 seconds of one.</p>
        <p class="cant">Cannot show a viewer would stop scrolling.</p></article>
      <article class="qc"><h2>Episodes covered</h2>
        <p class="qbig">${cov.episodes ? `${cov.episodes_with_a_promo} of ${cov.episodes}` : `${covered.size} of ${requested}`}</p>
        <p>Episodes searched that ended with at least one promo. The rest are listed below with the reason.</p>
        <p class="cant">A search of every episode is not the same as a promo in every episode.</p></article>
      <article class="qc"><h2>Posting order</h2>
        <p class="qbig">Unchecked</p>
        <p>The order comes from the tool's own scoring. Nobody has compared it with what an editor would post first${human ? `; one person's blind check of ${human.n} cuts: keep ${human.keep}, trim ${human.trim}, pass ${human.pass}` : ''}.</p>
        <p class="cant">Treat it as a suggestion.</p></article>
    </section>
    <section class="band">
      <h2>What it threw away, and why</h2>
      ${rej.length ? `<ul class="bars">${rej.map(([k, c]) => `<li><span>${esc(k)}</span><i style="--w:${(c / mx * 100).toFixed(0)}%"></i><b>${c}</b></li>`).join('')}</ul><p class="muted">Every rejected cut is kept in <code>rejected.json</code> so a person can overrule the tool.</p>` : '<p class="muted">Nothing was rejected in this run.</p>'}
    </section>
    <section class="band">
      <h2>Known weak spots</h2>
      <ul class="weak">
        <li><b>It reads a script, not footage.</b> It cannot see acting, pacing or whether a face makes someone stop. Every time is only as good as the script's timing.</li>
        <li><b>The reasons are written by a model.</b> They read well and are not verified against the clip.</li>
        <li><b>It sometimes judges too strictly.</b> A cut can be rejected for an ending that answers its own question when an editor would still use it.</li>
        <li><b>One continuous stretch per promo.</b> Joining moments from several episodes is not built.</li>
      </ul>
    </section>
    <section class="band">
      <h2>Episode by episode</h2>
      <div class="table-wrap"><table class="eps"><thead><tr><th>Episode</th><th>Result</th><th>Why there is none</th></tr></thead><tbody>${D.episodes.map(epRow).join('')}</tbody></table></div>
    </section>`;
}

/* ---------- pages ---------- */
const VIEWS = ['promos', 'season', 'quality', 'run'];
function route() {
  const h = (location.hash.replace(/^#\/?/, '').split('/')[0]) || 'promos';
  const v = VIEWS.includes(h) ? h : 'promos';
  VIEWS.forEach(n => { $('#v-' + n).classList.toggle('on', n === v); });
  document.querySelectorAll('#nav a').forEach(a => { const on = a.dataset.nav === v; a.classList.toggle('on', on); if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  const sc = $('#v-' + v); if (sc) sc.scrollTop = 0;
  document.title = ({ promos: 'Promos', season: 'Season', quality: 'Quality', run: 'Run it' })[v] + ' · ' + D.show.title + ' · Promo Finder';
}
function init() {
  $('#showTitle').textContent = D.show.title;
  if (D.show.demo) $('#demoPill').hidden = false;
  if (window.PROMO_MEMORY_ONLY) { document.querySelector('[data-nav="run"]').remove(); $('#navReview').remove(); $('#v-run').remove(); VIEWS.pop(); }   // inside the runner there is nothing to run from here
  renderPromos(); renderSeason(); renderQuality();
  window.addEventListener('hashchange', route);
  if (location.hash.length <= 2) history.replaceState(null, '', '#/promos');
  route();
}
init();
})();
