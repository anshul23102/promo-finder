"""Run the no-AI finder on one uploaded file, entirely in memory-sized steps, for the in-browser runner.

The browser worker (Pyodide) imports this module, hands it the uploaded bytes, and reads the result back from a
temporary folder. The same function runs in native Python, so the browser result can be compared with the command
line result (tests/test_browser.py and tools/check_browser_parity.mjs). Pure standard library; no network.

    result = run_upload("my-show.zip", data, work=Path("/tmp/run-1"))
    result["payload"]   # what the review page reads (window.PROMO_DATA)
    result["files"]     # names written under work/out (promos.csv, promos.json, cutlist.edl ...)

Inputs are checked here, before any parsing: type, size, entry count, decompressed size and path safety.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED

from .contract import build_contract, validate
from .payload import build_payload
from .run import main
from .screenplay import load_episodes

LIMITS = {"input_bytes": 25_000_000, "files": 200, "file_bytes": 5_000_000, "total_bytes": 60_000_000}


class InputError(ValueError):
    """The upload cannot be used. The message says what to change."""


def _wanted(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return PurePosixPath(name).suffix.lower() == ".txt" and not any(p.startswith((".", "__MACOSX")) for p in parts)


def _safe(name: str) -> str:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise InputError(f"Unsafe file path in the ZIP: {name!r}.")
    return path.as_posix()


def read_input(name: str, data: bytes, limits: dict | None = None) -> dict[str, bytes]:
    """Return {relative path: bytes} of the .txt episodes inside an upload, or raise InputError."""
    lim = {**LIMITS, **(limits or {})}
    if not data:
        raise InputError("The file is empty.")
    if len(data) > lim["input_bytes"]:
        raise InputError(f"The file is {len(data) / 1e6:.1f} MB. The browser runner takes at most {lim['input_bytes'] // 1_000_000} MB; use the local command for bigger shows.")
    lower = name.lower()
    if lower.endswith(".txt"):
        if len(data) > lim["file_bytes"]:
            raise InputError(f"{name} is larger than {lim['file_bytes'] // 1_000_000} MB.")
        return {PurePosixPath(name.replace("\\", "/")).name: data}
    if not lower.endswith(".zip"):
        raise InputError("Choose one .txt episode or one .zip of .txt episodes. Other formats (SRT, VTT, DOCX, PDF) are not read yet.")
    try:
        archive = ZipFile(BytesIO(data))
    except BadZipFile as exc:
        raise InputError("This is not a readable ZIP file. Re-create it and try again.") from exc
    out, total = {}, 0
    with archive:
        entries = [e for e in archive.infolist() if not e.is_dir() and _wanted(e.filename)]
        if not entries:
            raise InputError("No .txt screenplays found inside the ZIP.")
        if len(entries) > lim["files"]:
            raise InputError(f"The ZIP holds {len(entries)} episode files. The browser runner takes at most {lim['files']}.")
        for entry in entries:
            if entry.file_size > lim["file_bytes"]:
                raise InputError(f"{entry.filename} is larger than {lim['file_bytes'] // 1_000_000} MB once unpacked.")
            try:
                with archive.open(entry) as fh:
                    raw = fh.read(lim["file_bytes"] + 1)      # read at most one byte past the limit: a header cannot lie its way past this
            except (BadZipFile, NotImplementedError, RuntimeError) as exc:
                raise InputError(f"{entry.filename} cannot be unpacked ({exc}). Encrypted or damaged ZIPs are not supported.") from exc
            if len(raw) > lim["file_bytes"]:
                raise InputError(f"{entry.filename} is larger than {lim['file_bytes'] // 1_000_000} MB once unpacked.")
            total += len(raw)
            if total > lim["total_bytes"]:
                raise InputError(f"The ZIP unpacks to more than {lim['total_bytes'] // 1_000_000} MB in total.")
            out[_safe(entry.filename)] = raw
    return out


def show_title(name: str) -> str:
    stem = re.sub(r"\.(zip|txt)$", "", PurePosixPath(name.replace("\\", "/")).name, flags=re.I).strip()
    words = re.sub(r"[-_]+", " ", stem)[:80].strip()
    return (words[:1].upper() + words[1:]) or "Your show"


def run_upload(name: str, data: bytes, *, work: Path, log_fn=None, limits: dict | None = None) -> dict:
    """Run the rules-only finder on an upload. Everything lives under `work`; the caller deletes it afterwards."""
    work = Path(work)
    files = read_input(name, data, limits)
    inp, out = work / "in", work / "out"
    for rel, raw in files.items():
        target = inp / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    try:
        main([str(inp), "--model", "rules", "--out", str(out), "--cache", str(work / "cache"), "--title", show_title(name), "--no-viewer"],
             log_fn=log_fn)
    except ValueError as exc:                       # malformed timestamps, duplicate episode numbers, no cues ...
        raise InputError(str(exc)) from exc
    episodes = {e.number: e for e in load_episodes(inp)}
    payload = build_payload(out, episodes)
    contract = build_contract(out, episodes, input_name=name, input_sha256=hashlib.sha256(data).hexdigest())
    problems = validate(contract)
    if problems:
        raise RuntimeError("the finder produced a run document it cannot read back: " + "; ".join(problems))
    return {"payload": payload, "contract": contract, "files": sorted(p.name for p in out.iterdir() if p.is_file()), "out": out}


def write_result(result: dict, work: Path) -> None:
    """Write result.json and run.zip next to the run, so the caller (a JS worker or a test) reads plain files."""
    work = Path(work)
    (work / "result.json").write_text(json.dumps(result["payload"], ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    with ZipFile(work / "run.zip", "w", ZIP_DEFLATED) as bundle:
        for name in result["files"]:
            bundle.write(result["out"] / name, name)
        bundle.writestr("contract.json", json.dumps(result["contract"], indent=1, ensure_ascii=False))


def clean(work: Path) -> None:
    shutil.rmtree(work, ignore_errors=True)


def _strip_clock(value):
    """Drop wall-clock fields so two runs of the same input compare equal."""
    if isinstance(value, dict):
        return {k: _strip_clock(v) for k, v in value.items() if k not in ("seconds", "id", "run_id")}
    if isinstance(value, list):
        return [_strip_clock(v) for v in value]
    return value


def fingerprint(result: dict) -> dict:
    """A short, comparable summary of a run: one hash per output file and for the page payload, clock fields removed.

    Used by tools/check_browser_parity.mjs to compare real Pyodide with native Python on the same input."""
    def digest(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()
    files = {}
    for name in result["files"]:
        raw = (result["out"] / name).read_bytes()
        if name.endswith(".json"):
            raw = json.dumps(_strip_clock(json.loads(raw)), sort_keys=True, ensure_ascii=False).encode()
        elif name.endswith(".jsonl"):
            raw = "\n".join(json.dumps(_strip_clock(json.loads(line)), sort_keys=True) for line in raw.decode().splitlines()).encode()
        elif name.endswith((".md", ".html")):
            raw = re.sub(rb"\b\d+(\.\d+)? s\b", b"N s", raw)       # "Done in 0.1 s" style timings
        files[name] = digest(raw)
    canonical = json.dumps(_strip_clock(result["payload"]), sort_keys=True, ensure_ascii=False)
    contract = digest(json.dumps(_strip_clock(result["contract"]), sort_keys=True, ensure_ascii=False).encode())
    return {"payload": digest(canonical.encode()), "contract": contract, "files": files, "takes": len(result["payload"]["takes"]),
            "episodes": result["payload"]["show"]["episodes"]}


if __name__ == "__main__":        # python3 -m promo.browser FILE  ->  fingerprint of the run, for the parity check
    import sys
    import tempfile
    src = Path(sys.argv[1])
    scratch = Path(tempfile.mkdtemp())
    try:
        print(json.dumps(fingerprint(run_upload(src.name, src.read_bytes(), work=scratch / "r", log_fn=lambda _l: None)), sort_keys=True))
    except InputError as exc:
        print(json.dumps({"input_error": str(exc)}))
    finally:
        clean(scratch)
