// Same input, two engines: real Pyodide (the files in a built site's run/ folder) and native Python.
// Compares one hash per output file and for the page payload (clock fields removed). Exit 1 on any difference.
//
//   node tools/check_browser_parity.mjs --site <built site> FILE [FILE ...]
//
// FILE is a .txt, a .zip, or a deliberately broken file: both engines must then agree on the input error too.
import { readFileSync, readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { basename, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const args = process.argv.slice(2);
const at = args.indexOf('--site');
if (at < 0 || args.length < at + 3) { console.error('usage: node check_browser_parity.mjs --site <site> FILE...'); process.exit(2); }
const site = resolve(args[at + 1]);
const files = args.filter((_, i) => i !== at && i !== at + 1).map((f) => resolve(f));
const root = resolve(new URL('..', import.meta.url).pathname);

const version = JSON.parse(readFileSync(join(site, 'run', 'version.json'), 'utf8'));
const runtime = join(site, 'run', 'runtime', `pyodide-${version.pyodide}`);
const { loadPyodide } = await import(pathToFileURL(join(runtime, 'pyodide.mjs')).href);
const pyodide = await loadPyodide({ indexURL: runtime + '/' });
const engine = readFileSync(join(site, 'run', version.engine));
pyodide.unpackArchive(engine.buffer.slice(engine.byteOffset, engine.byteOffset + engine.byteLength), 'zip', { extractDir: '/engine' });
pyodide.runPython(`
import sys, json
sys.path.insert(0, '/engine')
from pathlib import Path
from promo.browser import run_upload, fingerprint, clean, InputError
def check(name):
    work = Path('/work/run')
    clean(work)
    try:
        data = Path('/in/upload.bin').read_bytes()
        return json.dumps(fingerprint(run_upload(name, data, work=work, log_fn=lambda l: None)), sort_keys=True)
    except InputError as exc:
        return json.dumps({'input_error': str(exc)})
    finally:
        clean(work)
`);
pyodide.FS.mkdirTree('/in');

let bad = 0;
console.log(`Pyodide ${version.pyodide} (Python ${pyodide.runPython('import sys; sys.version.split()[0]')}) vs native Python, engine ${version.engine}`);
for (const file of files) {
  const raw = readFileSync(file);
  pyodide.FS.writeFile('/in/upload.bin', new Uint8Array(raw));
  const web = JSON.parse(pyodide.globals.get('check')(basename(file)));
  const run = spawnSync('python3', ['-m', 'promo.browser', file], { cwd: root, encoding: 'utf8' });
  if (run.status !== 0) { console.log(`FAIL ${basename(file)}: native Python crashed\n${run.stderr.slice(-400)}`); bad++; continue; }
  const native = JSON.parse(run.stdout.trim().split('\n').pop());
  const diffs = [];
  if (web.input_error || native.input_error) {
    if (web.input_error !== native.input_error) diffs.push(`input error differs: web=${JSON.stringify(web.input_error)} native=${JSON.stringify(native.input_error)}`);
  } else {
    if (web.payload !== native.payload) diffs.push('page payload');
    for (const name of new Set([...Object.keys(web.files), ...Object.keys(native.files)])) if (web.files[name] !== native.files[name]) diffs.push(name);
  }
  const what = web.input_error ? `rejected the same way ("${web.input_error.slice(0, 60)}")` : `${web.takes} cuts from ${web.episodes} episodes, ${Object.keys(web.files).length} files`;
  if (diffs.length) { bad++; console.log(`FAIL ${basename(file)}: differs in ${diffs.join(', ')}`); } else console.log(`ok   ${basename(file)}: identical, ${what}`);
}
process.exit(bad ? 1 : 0);
