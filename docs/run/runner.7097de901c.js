/* The "Run on a script" page: file in, Rules candidates out, all inside this tab.
   The Python finder runs in a module worker (worker.js). This file only moves bytes, shows progress, validates the
   answer's shape, and hands it to the existing review page (view.html) in memory. */
(() => {
'use strict';
const WORKER = 'worker.2c32ac09c6.js';
const MAX_BYTES = 25_000_000;
const $ = (id) => document.getElementById(id);
const el = { start: $('start'), fallback: $('fallback'), result: $('result'), file: $('file'), drop: $('drop'), status: $('status'),
  error: $('error'), cancel: $('cancel'), view: $('view'), where: $('where'), h1: $('h1') };

let watchdog = 0, worker = null, runId = 0, active = 0, zipBuffer = null, zipName = 'promo-finder-run.zip', startedAt = 0, ready = false, runtimeMs = 0, view = null;
const stats = window.__runnerStats = {};

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const show = (node, on) => { node.hidden = !on; };

function say(text) { el.status.textContent = text; show(el.status, !!text); }
function fail(message) {
  const p = document.createElement('p'), b = document.createElement('b');
  b.textContent = message; p.appendChild(b); el.error.replaceChildren(p);
  show(el.error, true); busy(false); say('');
}
function busy(on) {
  el.drop.classList.toggle('busy', on);
  el.file.disabled = on;
  document.querySelectorAll('[data-example]').forEach((b) => { b.disabled = on; });
  show(el.cancel, on);
}

function boot() {
  if (worker) return;
  worker = new Worker(new URL(WORKER, location.href), { type: 'module' });
  worker.onmessage = onMessage;
  worker.onerror = (e) => { e.preventDefault(); crashed('The worker stopped (' + (e.message || 'unknown error') + ').'); };
  worker.onmessageerror = () => crashed('The worker sent a message this page could not read.');
}

function crashed(why) {
  stop();
  active = 0;
  show(el.start, false); show(el.result, false); show(el.fallback, true);
  $('fallbackWhy').textContent = why;
}

function stop() { clearTimeout(watchdog); if (worker) { worker.terminate(); worker = null; ready = false; } }

function onMessage(event) {
  const m = event.data;
  if (m.type === 'ready') { ready = true; clearTimeout(watchdog); runtimeMs = Math.round(performance.now() - startedAt); stats.runtimeMs = runtimeMs; stats.python = m.python; return; }
  if (m.type === 'status') { if (!m.id || m.id === active) say(m.text); return; }
  if (m.id !== active) return;                         // a late answer from a run that was cancelled or replaced: ignore it
  if (m.type === 'log') { const line = m.line.trim(); if (/^episode \d+/i.test(line)) say('Working on ' + line.replace(/:.*/, '') + '...'); return; }
  if (m.type === 'error') {
    if (m.kind === 'engine') { crashed(m.message); return; }
    fail(m.message); return;
  }
  if (m.type === 'done') done(m);
}

function validate(payload) {
  const ok = payload && payload.schema === 1 && Array.isArray(payload.takes) && Array.isArray(payload.episodes)
    && payload.show && typeof payload.show.title === 'string' && payload.run && typeof payload.run === 'object';
  if (!ok) throw new Error('The finder returned an answer this page cannot read.');
  return payload;
}

function done(m) {
  let payload;
  try { payload = validate(JSON.parse(m.payload)); } catch (e) { fail(e.message); return; }
  stats.runMs = Math.round(performance.now() - startedAt) - (stats.runtimeMs || 0);
  zipBuffer = m.zip;
  zipName = payload.show.title.replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '').toLowerCase() + '-promo-finder-run.zip';
  mount(payload);
  busy(false); say('');
}

function mount(payload) {
  window.__PROMO_PAYLOAD = payload;                      // read by view.html through its bootstrap, never stored
  const n = payload.takes.length;
  $('rTitle').textContent = payload.show.title;
  $('rMeta').textContent = ' ' + (n ? `${n} rules candidate${n === 1 ? '' : 's'} from ${payload.show.episodes} episode${payload.show.episodes === 1 ? '' : 's'}. No AI ran.` : `No candidate passed the checks in ${payload.show.episodes} episode${payload.show.episodes === 1 ? '' : 's'}. No AI ran.`);
  el.where.textContent = payload.show.title;
  $('textBody').innerHTML = textList(payload);
  show(el.start, false); show(el.fallback, false); show(el.result, true);
  document.body.classList.add('has-result');
  el.view.hidden = false;
  el.view.src = 'view.html';
  document.title = payload.show.title + ' · Run on a script · Promo Finder';
  $('again').focus();
}

function textList(p) {
  if (!p.takes.length) return '<p>Nothing passed the timing checks. Try a longer episode or a script with more dialogue.</p>';
  const rows = p.takes.slice().sort((a, b) => a.rank - b.rank).map((t) => {
    const segs = t.segments.map((s) => `episode ${s.episode} from ${fmt(s.start)} to ${fmt(s.end)}`).join(', then ');
    return `<li><b>#${t.rank}</b> ${esc(segs)} (${Math.round(t.duration)} s). Opens: ${esc(t.ai.opening || t.ai.hook)} Ends: ${esc(t.ai.cliff)}</li>`;
  }).join('');
  return `<ol>${rows}</ol>`;
}
const fmt = (cs) => { const s = Math.max(0, cs) / 100, m = Math.floor(s / 60); return String(m).padStart(2, '0') + ':' + (s - m * 60).toFixed(2).padStart(5, '0'); };

function run(name, buffer) {
  show(el.error, false);
  if (!/\.(txt|zip)$/i.test(name)) return fail('Choose one .txt episode or one .zip of .txt episodes. Other formats are not read yet.');
  if (!buffer.byteLength) return fail('That file is empty.');
  if (buffer.byteLength > MAX_BYTES) return fail(`That file is ${(buffer.byteLength / 1e6).toFixed(1)} MB. The browser runner takes up to 25 MB; use the local command for bigger shows.`);
  reset(false);
  boot();
  busy(true);
  active = ++runId;
  startedAt = performance.now();
  say(ready ? 'Finding candidates...' : 'Starting...');
  if (!ready) { clearTimeout(watchdog); watchdog = setTimeout(() => { if (!ready) crashed('The runtime took longer than 90 seconds to load. Check your connection and try again.'); }, 90000); }
  worker.postMessage({ type: 'run', id: String(active), name, buffer }, [buffer]);
  active = String(active);
}

function reset(full) {
  active = 0;
  window.__PROMO_PAYLOAD = null;
  zipBuffer = null;
  el.view.removeAttribute('src'); el.view.hidden = true;
  show(el.result, false); show(el.error, false);
  document.body.classList.remove('has-result');
  if (full) {
    stop();
    show(el.fallback, false); show(el.start, true);
    el.where.textContent = 'Run on a script';
    document.title = 'Run on a script · Promo Finder';
    el.file.value = '';
    busy(false); say('');
  }
}

el.file.addEventListener('change', async () => {
  const f = el.file.files[0];
  if (!f) return;
  run(f.name, await f.arrayBuffer());
  el.file.value = '';                                    // choosing the same file again must run again
});
['dragenter', 'dragover'].forEach((t) => el.drop.addEventListener(t, (e) => { e.preventDefault(); el.drop.classList.add('over'); }));
['dragleave', 'drop'].forEach((t) => el.drop.addEventListener(t, (e) => { e.preventDefault(); el.drop.classList.remove('over'); }));
el.drop.addEventListener('drop', async (e) => {
  const files = [...(e.dataTransfer.files || [])];
  if (files.length !== 1) return fail('Drop one .txt episode or one .zip.');
  run(files[0].name, await files[0].arrayBuffer());
});
document.querySelectorAll('[data-example]').forEach((b) => b.addEventListener('click', async () => {
  try {
    const r = await fetch('examples/' + b.dataset.example);
    if (!r.ok) throw new Error('The example could not be loaded (' + r.status + ').');
    run(b.dataset.example, await r.arrayBuffer());
  } catch (e) { fail(e.message); }
}));
el.cancel.addEventListener('click', () => { stop(); reset(true); say('Cancelled. Nothing was kept.'); setTimeout(() => say(''), 2500); });
$('again').addEventListener('click', () => reset(true));
$('retry').addEventListener('click', () => reset(true));
$('dlZip').addEventListener('click', () => {
  if (!zipBuffer) return;
  const url = URL.createObjectURL(new Blob([zipBuffer], { type: 'application/zip' }));
  const a = Object.assign(document.createElement('a'), { href: url, download: zipName });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
});
window.addEventListener('pagehide', () => { window.__PROMO_PAYLOAD = null; });
})();
