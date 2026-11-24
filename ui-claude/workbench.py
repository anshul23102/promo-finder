"""The workbench: drop screenplay files in the browser, pick how to find promos, get the results page.

    python3 ui-claude/workbench.py [--port 8770] [--no-open] [--browser Safari]

Runs on 127.0.0.1 only. Your scripts are stored under private/workbench/<job>/ on this computer. With "No AI" nothing
leaves the machine. With an AI engine, the script text is sent to that provider using the key in your .env file; the page
asks you to confirm before it does. The server checks a per-launch token and the Host header on every API call, so another
web page cannot use it.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
JOBS = ROOT / "private" / "workbench"
TOKEN = secrets.token_urlsafe(24)
MAX_FILE = 25_000_000
MAX_FILES = 120
ID = re.compile(r"^[a-f0-9]{12}$")
SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]")
ENGINES = {
    "rules": {"label": "No AI (instant, fully private)", "key": None, "args": ["--model", "rules"], "sends": None},
    "gemini": {"label": "Gemini (free plan)", "key": "GEMINI_API_KEY", "sends": "Google (the unpaid Gemini terms say not to send confidential material)",
               "args": ["--model", "gemini", "--judge", "gemini:gemma-4-26b-a4b-it|gemini-3.1-flash-lite"]},
    "groq": {"label": "Groq (free plan, fast)", "key": "GROQ_API_KEY", "sends": "Groq",
             "args": ["--model", "groq:openai/gpt-oss-120b", "--judge", "groq:qwen/qwen3.8-27b", "--no-guide", "--no-recover", "--rank-top", "12", "--rounds", "3"]},
    # providers where the model name is yours to choose: the same name scores and judges, and a key can be pasted for one run
    "openai": {"label": "OpenAI (your own API key)", "key": "OPENAI_API_KEY", "sends": "OpenAI", "provider": "openai", "hint": "gpt-5-mini",
               "args": ["--rank-top", "12", "--rounds", "3"]},
    "openrouter": {"label": "OpenRouter (one key, many models)", "key": "OPENROUTER_API_KEY", "sends": "OpenRouter", "provider": "openrouter", "hint": "openai/gpt-oss-120b:free",
                   "args": ["--rank-top", "12", "--rounds", "3"]},
    "custom": {"label": "Another endpoint (OpenAI-compatible)", "key": "PROMO_API_KEY", "base": "PROMO_BASE_URL",
               "sends": "the endpoint you enter", "provider": "openai-compatible", "hint": "the model name they give you", "needs_model": True,
               "args": ["--rank-top", "12", "--rounds", "3"]},
    "ollama": {"label": "Local model with Ollama (slow, stays on this computer)", "key": None, "sends": None, "args": ["--model", "ollama:qwen3:4b", "--no-guide"]},
}
MODEL_OK = re.compile(r"^[A-Za-z0-9._:/|-]{1,120}$")
KEY_OK = re.compile(r"^[\x21-\x7e]{8,400}$")
BASE_OK = re.compile(r"^https?://[A-Za-z0-9._:/-]{4,200}$")
JOBSTATE: dict[str, dict] = {}
PROCS: dict[str, subprocess.Popen] = {}     # running jobs, so a run can be stopped
SITE_DIR = ROOT / "site"          # replaced by prepare_site()


def env_has(name):
    if not name:
        return True
    if os.environ.get(name):
        return True
    f = ROOT / ".env"
    if f.is_file():
        return any(l.split("=", 1)[0].strip() == name and l.split("=", 1)[1].strip() for l in f.read_text().splitlines() if "=" in l and not l.lstrip().startswith("#"))
    return False


def job_dir(jid):
    return JOBS / jid


def run_job(jid, engine, episodes, title, model="", env_extra=None):
    d = job_dir(jid)
    st = JOBSTATE[jid]
    inp = d / "in"
    zips = list(inp.glob("*.zip"))
    target = zips[0] if len(zips) == 1 and len(list(inp.iterdir())) == 1 else inp
    out = d / "run"
    e = ENGINES[engine]
    if e.get("provider"):
        spec = e["provider"] + (":" + model if model else "")
        model_args = ["--model", spec, "--judge", spec]
    else:
        model_args = []
    cmd = [sys.executable, "-m", "promo", str(target), *model_args, *e["args"], "--out", str(out), "--title", title or "My show"]
    if episodes:
        cmd += ["--episodes", episodes]
    env = {**os.environ, **(env_extra or {})}      # a pasted key lives only in this process's environment: never written to disk
    log = d / "log.txt"
    try:
        with log.open("w") as fh:
            st.update(status="running", phase="Finding promos")
            if st.get("cancelled"):
                st.update(status="cancelled", message="Stopped.")
                return
            p = subprocess.Popen(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, text=True, env=env)
            PROCS[jid] = p
            while p.poll() is None:
                time.sleep(1)
            code = p.returncode
            PROCS.pop(jid, None)
            if st.get("cancelled"):
                st.update(status="cancelled", message="Stopped.")
                return
        if code != 0 or not (out / "promos.json").is_file():
            tail = log.read_text(errors="replace").strip().splitlines()[-6:]
            st.update(status="error", message="The run stopped: " + " | ".join(tail)[:600])
            return
        st.update(phase="Building the results page")
        b = subprocess.run([sys.executable, str(HERE / "build_data.py"), "--run", str(out), "--pack", str(target), "--beats", str(out), "--out", str(d / "ui")],
                           cwd=ROOT, capture_output=True, text=True)
        if b.returncode != 0:
            st.update(status="error", message="Could not build the results page: " + (b.stderr or b.stdout)[-400:])
            return
        summary = json.loads((out / "run_summary.json").read_text()) if (out / "run_summary.json").is_file() else {}
        st.update(status="done", url=f"/view/{jid}/", warnings=list(summary.get("warnings") or []), promos=summary.get("passed"),
                  candidates=summary.get("candidates"), episodes=summary.get("episodes"))
        (d / "meta.json").write_text(json.dumps({"title": title, "engine": engine, "when": int(time.time()),
                                                 "warnings": len(summary.get("warnings") or []), "promos": summary.get("passed")}))
    except Exception as exc:  # noqa: BLE001 - shown to the user
        st.update(status="error", message=str(exc)[:600])


class H(BaseHTTPRequestHandler):
    server_version = "workbench"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else (json.dumps(body) if not isinstance(body, str) else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":          # a HEAD request (the in-browser runner checks its files this way) gets the headers only
            self.wfile.write(data)

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def _api_ok(self):
        return self._host_ok() and hmac.compare_digest(self.headers.get("X-Token", "").encode(), TOKEN.encode())

    def _static(self, base: Path, rel: str, fallback: Path | None = None, token: bool = False):
        """Serve a file under base. With a fallback folder, a file missing from base is looked up there (a saved run has no copy of the
        in-browser runner, so it borrows the Workbench's). With token, the page's token placeholder is filled in."""
        def locate(root: Path):
            p = (root / rel).resolve()
            if root.resolve() not in p.parents and p != root.resolve():
                return None
            if p.is_dir():
                p = p / "index.html"
            return p if p.is_file() else None
        p = locate(base) or (locate(fallback) if fallback else None)
        if p is None:
            return self._send(404, {"error": "not found"})
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript", ".woff2": "font/woff2",
                 ".json": "application/json", ".wasm": "application/wasm", ".zip": "application/zip", ".svg": "image/svg+xml"}.get(p.suffix, "application/octet-stream")
        data = p.read_bytes()
        if token and p.name == "index.html" and p.parent == base.resolve():
            data = data.replace(b"__WB_TOKEN__", TOKEN.encode())
        self._send(200, data, ctype)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):          # the Promo Finder page itself; the Run it tab finds the AI option through the token
            page = SITE_DIR / "index.html"
            if not page.is_file():
                return self._send(404, {"error": "site not built"})
            return self._send(200, page.read_text(encoding="utf-8").replace("__WB_TOKEN__", TOKEN), "text/html; charset=utf-8")
        if u.path == "/classic":                    # the earlier stand-alone page
            html = (HERE / "workbench.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
            return self._send(200, html, "text/html; charset=utf-8")
        if u.path.startswith("/view/"):
            parts = u.path.split("/", 3)
            if len(parts) >= 3 and ID.match(parts[2]) and (job_dir(parts[2]) / "ui").is_dir():
                return self._static(job_dir(parts[2]) / "ui", parts[3] if len(parts) > 3 else "", fallback=SITE_DIR, token=True)
            return self._send(404, {"error": "not found"})
        if not u.path.startswith("/api/"):
            return self._static(SITE_DIR, u.path.lstrip("/"))     # app.js, data.js, fonts, the in-browser runner
        if not self._api_ok():
            return self._send(403, {"error": "bad token"})
        if u.path == "/api/engines":
            return self._send(200, {k: {"label": v["label"], "ready": env_has(v["key"]) and env_has(v.get("base")), "key": v["key"], "base": v.get("base"),
                                        "sends": v["sends"], "takes_model": bool(v.get("provider")), "needs_model": bool(v.get("needs_model")), "hint": v.get("hint", "")}
                                    for k, v in ENGINES.items()})
        if u.path == "/api/job":
            jid = (q.get("id") or [""])[0]
            st = JOBSTATE.get(jid)
            if not st:
                return self._send(404, {"error": "unknown job"})
            lg = job_dir(jid) / "log.txt"
            tail = lg.read_text(errors="replace").strip().splitlines()[-60:] if lg.is_file() else []
            return self._send(200, {**st, "log": tail})
        if u.path == "/api/jobs":
            out = []
            for m in sorted(JOBS.glob("*/meta.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:12]:
                if ID.match(m.parent.name) and (m.parent / "ui").is_dir():
                    out.append({"id": m.parent.name, **json.loads(m.read_text())})
            return self._send(200, out)
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._api_ok():
            return self._send(403, {"error": "bad token"})
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_FILE:
            return self._send(413, {"error": "file too large"})
        body = self.rfile.read(n)
        if u.path == "/api/new":
            jid = secrets.token_hex(6)
            (job_dir(jid) / "in").mkdir(parents=True)
            JOBSTATE[jid] = {"status": "new"}
            return self._send(200, {"id": jid})
        if u.path == "/api/upload":
            q = parse_qs(u.query)
            jid, name = (q.get("job") or [""])[0], SAFE_NAME.sub("_", Path((q.get("name") or [""])[0]).name)
            if not ID.match(jid) or jid not in JOBSTATE or JOBSTATE[jid]["status"] != "new":
                return self._send(400, {"error": "bad job"})
            if not name.lower().endswith((".txt", ".zip")):
                return self._send(400, {"error": "Only .txt episodes or one .zip are accepted."})
            d = job_dir(jid) / "in"
            if len(list(d.iterdir())) >= MAX_FILES:
                return self._send(400, {"error": f"At most {MAX_FILES} files."})
            (d / name).write_bytes(body)
            return self._send(200, {"ok": True})
        if u.path == "/api/run":
            try:
                req = json.loads(body or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad json"})
            jid, eng = str(req.get("job", "")), str(req.get("engine", ""))
            if not ID.match(jid) or jid not in JOBSTATE or eng not in ENGINES:
                return self._send(400, {"error": "bad request"})
            e = ENGINES[eng]
            model, key, base = (str(req.get(n, "")).strip() for n in ("model", "api_key", "base_url"))
            if model and not (e.get("provider") and MODEL_OK.fullmatch(model)):
                return self._send(400, {"error": "The model name has characters that are not allowed, or this engine does not take one."})
            if e.get("needs_model") and not model:
                return self._send(400, {"error": "Enter the model name for this endpoint."})
            if key and not (e["key"] and KEY_OK.fullmatch(key)):
                return self._send(400, {"error": "That key does not look right: 8 to 400 visible characters, no spaces."})
            if base and not (e.get("base") and BASE_OK.fullmatch(base)):
                return self._send(400, {"error": "The endpoint address should look like https://host/v1."})
            if e["key"] and not (key or env_has(e["key"])):
                return self._send(400, {"error": f"{e['key']} is not set. Paste a key below, or add it to the .env file in the project folder."})
            if e.get("base") and not (base or env_has(e["base"])):
                return self._send(400, {"error": f"Enter the endpoint address, or set {e['base']} in the .env file."})
            if e["sends"] and not req.get("confirm"):
                return self._send(400, {"error": "Please confirm you may send these scripts to the AI provider."})
            eps = str(req.get("episodes", "")).strip()
            if eps.lower() in ("all", "*"):
                eps = ""
            if eps and not re.fullmatch(r"[0-9,\- ]{1,40}", eps):
                return self._send(400, {"error": "Episodes look like 1-10 or 2,7,33."})
            if not any((job_dir(jid) / "in").iterdir()):
                return self._send(400, {"error": "Add at least one file first."})
            JOBSTATE[jid].update(status="queued")
            env_extra = {**({e["key"]: key} if key else {}), **({e["base"]: base} if base else {})}
            threading.Thread(target=run_job, args=(jid, eng, eps.replace(" ", ""), str(req.get("title", ""))[:80], model, env_extra), daemon=True).start()
            return self._send(200, {"ok": True})
        if u.path == "/api/cancel":
            try:
                jid = str(json.loads(body or b"{}").get("job", ""))
            except ValueError:
                return self._send(400, {"error": "bad json"})
            if not ID.match(jid) or jid not in JOBSTATE:
                return self._send(400, {"error": "bad job"})
            JOBSTATE[jid]["cancelled"] = True
            p = PROCS.get(jid)
            if p and p.poll() is None:
                p.terminate()
                threading.Timer(5, lambda: p.poll() is None and p.kill()).start()
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})


def prepare_site(results_run=None, results_pack=None):
    """The page the Workbench serves at /. Built fresh from the made-up demo show when this copy has it (so the page always matches the
    current code); otherwise the published docs/ or site/ folder. With results_run and results_pack it is built from that finished run
    instead (script text stays on this computer), so the results and the AI option sit in one page."""
    global SITE_DIR
    runtime = ROOT / "private" / "pyodide-package"
    if results_run:
        out = JOBS / "_site_results"
        cmd = [sys.executable, str(HERE / "build_data.py"), "--run", str(results_run), "--pack", str(results_pack), "--out", str(out)]
    else:
        out = JOBS / "_site"
        demo, pack = ROOT / "private" / "runs" / "demo-gemini", ROOT / "examples" / "the-last-edition"
        cmd = [sys.executable, str(HERE / "build_data.py"), "--run", str(demo), "--pack", str(pack), "--demo", "--out", str(out)] if demo.is_dir() and pack.is_dir() else None
    if cmd:
        b = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if b.returncode == 0 and (runtime / "package.json").is_file():
            subprocess.run([sys.executable, str(HERE / "build_runner.py"), "--site", str(out), "--runtime", str(runtime), "--release", "workbench"],
                           cwd=ROOT, capture_output=True, text=True)
        if b.returncode == 0:
            SITE_DIR = out
            return
        print("Could not build the page; using a published copy instead.", (b.stderr or "")[-200:])
    for d in (ROOT / "docs", ROOT / "site"):
        if (d / "index.html").is_file():
            SITE_DIR = d
            return


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--browser", default="Safari")
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--results-run", help="A finished run folder to show as the results (with --results-pack)")
    ap.add_argument("--results-pack", help="The scripts zip or folder that run was made from")
    a = ap.parse_args()
    JOBS.mkdir(parents=True, exist_ok=True)
    prepare_site(a.results_run, a.results_pack)
    url = f"http://127.0.0.1:{a.port}/"
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    except OSError:                              # the port is taken: most likely a Workbench that is already running
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                running = r.status == 200 and b"wb-token" in r.read()
        except OSError:
            running = False
        if not running:
            sys.exit(f"Port {a.port} is in use by something else. Close it, or start with --port <another number>.")
        print(f"The Workbench is already running at {url}  (opening it).")
        if not a.no_open:
            subprocess.run(["open", "-a", a.browser, url]) if sys.platform == "darwin" else webbrowser.open(url)
        return
    print(f"Workbench running at {url}  (Ctrl-C to stop). Files are kept in {JOBS}")
    if not a.no_open:
        subprocess.run(["open", "-a", a.browser, url]) if sys.platform == "darwin" else webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
