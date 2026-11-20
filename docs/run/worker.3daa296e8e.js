/* Runs the real Python finder (the same promo/ package the command line uses) inside the browser, in a module worker.
   Loaded only when someone presses "Run". Takes no keys and makes no network calls once the runtime is loaded:
   the uploaded bytes are written to this worker's in-memory file system, read, and deleted again in a finally block.
   runtime/pyodide-0.29.5/, engine.4b3261ea0d.zip and 4b3261ea0d926086aa20cf15cba7972f198fd3c752557df713b6d20933662358 are filled in by ui-claude/build_runner.py. */
const RUNTIME = 'runtime/pyodide-0.29.5/';          // folder of the pinned Pyodide files, relative to this worker
const ENGINE = 'engine.4b3261ea0d.zip';            // content-hashed zip of the promo/ package
const ENGINE_SHA = '4b3261ea0d926086aa20cf15cba7972f198fd3c752557df713b6d20933662358';

const base = new URL('.', self.location.href);
const say = (m) => self.postMessage(m);
let booting = null;
let pyodide = null;

async function sha256(buffer) {
  const h = await crypto.subtle.digest('SHA-256', buffer);
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function boot() {
  say({ type: 'status', text: 'Loading the Python runtime (first time only, about 12 MB)...' });
  for (const file of ['pyodide.mjs', 'pyodide.asm.js', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json']) {   // fail fast and say which file, instead of hanging
    let status = 0;
    try { status = (await fetch(new URL(RUNTIME + file, base).href, { method: 'HEAD' })).status; } catch (e) { /* offline or blocked */ }
    if (status !== 200) throw new Error(`A runtime file is missing or blocked (${file}${status ? ', status ' + status : ''}).`);
  }
  const { loadPyodide } = await import(new URL(RUNTIME + 'pyodide.mjs', base).href);
  pyodide = await loadPyodide({ indexURL: new URL(RUNTIME, base).href });
  say({ type: 'status', text: 'Loading the finder...' });
  const res = await fetch(new URL(ENGINE, base).href);
  if (!res.ok) throw new Error('The finder package could not be loaded (' + res.status + ').');
  const zip = await res.arrayBuffer();
  if (ENGINE_SHA.indexOf('__') !== 0 && (await sha256(zip)) !== ENGINE_SHA) throw new Error('The finder package does not match this page (a cached copy from another version). Reload the page.');
  pyodide.unpackArchive(zip, 'zip', { extractDir: '/engine' });
  pyodide.runPython(`
import sys, json
sys.path.insert(0, '/engine')
from pathlib import Path
import js
from pyodide.ffi import to_js
from promo.browser import run_upload, write_result, clean, InputError

def _log(line, _id=[None]):
    js.postMessage(to_js({'type': 'log', 'id': _id[0], 'line': str(line)}, dict_converter=js.Object.fromEntries))

def go(req_id, name):
    work = Path('/work') / req_id
    try:
        data = (work / 'upload.bin').read_bytes()
        (work / 'upload.bin').unlink()                       # the raw upload is not needed after this read
        _log.__defaults__[0][0] = req_id
        result = run_upload(name, data, work=work / 'job', log_fn=_log)
        write_result(result, work / 'job')
        return ''
    except InputError as exc:
        return 'input:' + str(exc)

def sweep(req_id):
    clean(Path('/work') / req_id)
`);
  // After this point nothing in this worker should reach the network: remove the ways to do it.
  const refuse = () => { throw new Error('Network access is switched off in the runner.'); };
  self.fetch = refuse; self.XMLHttpRequest = refuse; self.WebSocket = refuse; self.EventSource = refuse;
  say({ type: 'ready', python: pyodide.runPython('import sys; sys.version.split()[0]') });
}

self.onmessage = async (event) => {
  const m = event.data;
  if (m.type !== 'run') return;
  const id = m.id;
  const dir = '/work/' + id;
  try {
    booting = booting || boot();
    await booting;
    say({ type: 'status', id, text: 'Reading the script...' });
    pyodide.FS.mkdirTree(dir);
    pyodide.FS.writeFile(dir + '/upload.bin', new Uint8Array(m.buffer));
    const outcome = pyodide.globals.get('go')(id, m.name);
    if (outcome) {
      say({ type: 'error', id, kind: 'input', message: outcome.slice(6) });
      return;
    }
    const payload = pyodide.FS.readFile(dir + '/job/result.json', { encoding: 'utf8' });
    const zip = pyodide.FS.readFile(dir + '/job/run.zip');
    const buffer = zip.buffer.slice(zip.byteOffset, zip.byteOffset + zip.byteLength);
    self.postMessage({ type: 'done', id, payload, zip: buffer }, [buffer]);
  } catch (error) {
    say({ type: 'error', id, kind: 'engine', message: String((error && error.message) || error) });
  } finally {
    try { if (pyodide) pyodide.globals.get('sweep')(id); } catch (e) { /* nothing left to clean */ }
  }
};
