"""Add the in-browser runner to a built site (the folder build_data.py wrote).

    python3 ui-claude/build_runner.py --site <built site> --runtime <unpacked pyodide npm package> --release <short commit>

Writes <site>/run/: a module worker (the Run it tab of the page drives it), the pinned Pyodide runtime (unmodified), the promo/ package as one
content-hashed zip, a bundled synthetic example or two, view.html (the same review page, fed from memory) and version.json.
Every file the page loads carries a content hash in its name, so a cached page can never mix versions.
Deterministic: the same inputs give byte-identical output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUNTIME_FILES = ["pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]
DATE = (1980, 1, 1, 0, 0, 0)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_zip(path: Path, files: list[tuple[str, bytes]]) -> bytes:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, raw in sorted(files):
            info = zipfile.ZipInfo(name, DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, raw)
    return path.read_bytes()


def hashed(out: Path, name: str, data: bytes) -> str:
    stem, dot, ext = name.rpartition(".")
    final = f"{stem}.{sha(data)[:10]}.{ext}"
    (out / final).write_bytes(data)
    return final


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", type=Path, required=True)
    ap.add_argument("--runtime", type=Path, required=True, help="Folder of the unpacked pyodide npm package")
    ap.add_argument("--release", default="dev", help="Short commit shown on the page")
    ap.add_argument("--examples", type=Path, default=ROOT / "examples")
    args = ap.parse_args()

    pkg = json.loads((args.runtime / "package.json").read_text(encoding="utf-8"))
    version = pkg["version"]
    lock = json.loads((args.runtime / "pyodide-lock.json").read_text(encoding="utf-8"))
    python = lock.get("info", {}).get("python", "unknown")
    out = args.site / "run"
    if out.exists():
        shutil.rmtree(out)
    runtime_dir = out / "runtime" / f"pyodide-{version}"
    runtime_dir.mkdir(parents=True)
    (out / "examples").mkdir()

    lock = json.loads((HERE / "runtime.lock.json").read_text(encoding="utf-8"))
    if lock["pyodide"] != version:
        sys.exit(f"runtime.lock.json pins Pyodide {lock['pyodide']}, but {args.runtime} is {version}. Refusing to mix versions.")
    for name in RUNTIME_FILES:
        if sha((args.runtime / name).read_bytes()) != lock["files"][name]:
            sys.exit(f"{name} does not match the hash pinned in ui-claude/runtime.lock.json. Re-download pyodide@{version} from npm; do not edit the lock.")
        shutil.copy2(args.runtime / name, runtime_dir / name)
    (runtime_dir / "NOTICE.txt").write_text(
        f"Pyodide {version} (Python {python}), unmodified, copied from the npm package 'pyodide@{version}'.\n"
        "Pyodide is licensed under the Mozilla Public License 2.0: https://www.mozilla.org/MPL/2.0/\n"
        "Source: https://github.com/pyodide/pyodide  Python standard library (python_stdlib.zip): PSF License.\n"
        "These files are served as they were released; nothing in them was changed.\n", encoding="utf-8")

    engine = write_zip(out / "engine.zip", [("promo/" + p.name, p.read_bytes()) for p in sorted((ROOT / "promo").glob("*.py"))])
    (out / "engine.zip").unlink()
    engine_name = hashed(out, "engine.zip", engine)

    worker = (HERE / "runner" / "worker.js").read_text(encoding="utf-8")
    worker = (worker.replace("__RUNTIME__", f"runtime/pyodide-{version}/").replace("__ENGINE__", engine_name).replace("__ENGINE_SHA__", sha(engine)))
    worker_name = hashed(out, "worker.js", worker.encode())
    boot_name = hashed(out, "bootstrap.js", (HERE / "runner" / "bootstrap.js").read_bytes())

    # old links to run/ land on the Run it tab of the single page
    (out / "index.html").write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=../#/run"><title>Run it</title><a href="../#/run">Run it</a>', encoding="utf-8")

    app_hash = sha((HERE / "app.js").read_bytes())[:10]
    css_hash = sha((HERE / "app.css").read_bytes())[:10]
    view = (HERE / "index.html").read_text(encoding="utf-8")
    csp = ('<meta http-equiv="Content-Security-Policy" content="default-src \'self\'; script-src \'self\'; style-src \'self\' \'unsafe-inline\'; '
           'img-src \'self\' data: blob:; font-src \'self\'; connect-src \'none\'; base-uri \'none\'">')
    view = view.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n' + csp, 1)
    view = view.replace('href="fonts.css"', 'href="../fonts.css"').replace('href="app.css"', f'href="../app.css?v={css_hash}"')
    view = view.replace('<script src="data.js"></script>', f'<script src="{boot_name}"></script>')
    view = view.replace('<script src="app.js"></script>', f'<script src="../app.js?v={app_hash}"></script>')
    assert "data.js" not in view and boot_name in view, "view.html was not rewritten"
    (out / "view.html").write_text(view, encoding="utf-8")

    examples = []
    for folder in sorted(p for p in args.examples.iterdir() if p.is_dir()):
        files = [(p.name, p.read_bytes()) for p in sorted(folder.glob("*.txt"))]
        if files:
            write_zip(out / "examples" / f"{folder.name}.zip", files)
            examples.append(f"{folder.name}.zip")

    listing = {str(p.relative_to(out)): {"bytes": p.stat().st_size, "sha256": sha(p.read_bytes())} for p in sorted(out.rglob("*")) if p.is_file()}
    (out / "version.json").write_text(json.dumps({
        "release": args.release, "worker": worker_name, "pyodide": version, "python": python, "engine": engine_name, "engine_sha256": sha(engine),
        "formats": [".txt", ".zip of .txt"], "limits": {"input_mb": 25, "episodes": 200, "episode_mb": 5, "unpacked_mb": 60},
        "examples": examples, "files": listing}, indent=1), encoding="utf-8")
    total = sum(v["bytes"] for v in listing.values())
    print(f"runner built in {out}: {len(listing)} files, {total / 1e6:.1f} MB, engine {engine_name}, Pyodide {version} (Python {python})")


if __name__ == "__main__":
    main()
