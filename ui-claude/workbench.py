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
    "groq": {"label": "Groq (free plan, fast)", "key": "GROQ_API_KEY", "sends": "Groq",
             "args": ["--model", "groq:openai/gpt-oss-120b", "--judge", "groq:qwen/qwen3.8-27b", "--no-guide", "--no-recover", "--rank-top", "12", "--rounds", "3"]},
    "gemini": {"label": "Gemini (free plan)", "key": "GEMINI_API_KEY", "sends": "Google (the unpaid Gemini terms say not to send confidential material)",
               "args": ["--model", "gemini", "--judge", "gemini:gemma-4-26b-a4b-it|gemini-3.1-flash-lite"]},
    "ollama": {"label": "Local model with Ollama (slow, stays on this computer)", "key": None, "sends": None, "args": ["--model", "ollama:qwen3:4b", "--no-guide"]},
}
JOBSTATE: dict[str, dict] = {}


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


def run_job(jid, engine, episodes, title):
    d = job_dir(jid)
    st = JOBSTATE[jid]
    inp = d / "in"
    zips = list(inp.glob("*.zip"))
    target = zips[0] if len(zips) == 1 and len(list(inp.iterdir())) == 1 else inp
    out = d / "run"
    cmd = [sys.executable, "-m", "promo", str(target), *ENGINES[engine]["args"], "--out", str(out), "--title", title or "My show"]
    if episodes:
        cmd += ["--episodes", episodes]
    log = d / "log.txt"
    try:
        with log.open("w") as fh:
            st.update(status="running", phase="Finding promos")
            p = subprocess.Popen(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, text=True)
            while p.poll() is None:
                time.sleep(1)
            code = p.returncode
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
        st.update(status="done", url=f"/view/{jid}/")
        (d / "meta.json").write_text(json.dumps({"title": title, "engine": engine, "when": int(time.time())}))
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
        self.wfile.write(data)

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def _api_ok(self):
        return self._host_ok() and hmac.compare_digest(self.headers.get("X-Token", "").encode(), TOKEN.encode())

    def _static(self, base: Path, rel: str):
        p = (base / rel).resolve()
        if base.resolve() not in p.parents and p != base.resolve():
            return self._send(404, {"error": "not found"})
        if p.is_dir():
            p = p / "index.html"
        if not p.is_file():
            return self._send(404, {"error": "not found"})
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".woff2": "font/woff2", ".json": "application/json"}.get(p.suffix, "application/octet-stream")
        self._send(200, p.read_bytes(), ctype)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            html = (HERE / "workbench.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
            return self._send(200, html, "text/html; charset=utf-8")
        if u.path in ("/app.css", "/fonts.css") or u.path.startswith("/fonts/"):
            base = HERE if u.path == "/app.css" else HERE / "fonts"
            return self._static(base, u.path.rsplit("/", 1)[-1] if u.path != "/app.css" else "app.css")
        if u.path.startswith("/view/"):
            parts = u.path.split("/", 3)
            if len(parts) >= 3 and ID.match(parts[2]) and (job_dir(parts[2]) / "ui").is_dir():
                return self._static(job_dir(parts[2]) / "ui", parts[3] if len(parts) > 3 else "")
            return self._send(404, {"error": "not found"})
        if not u.path.startswith("/api/"):
            return self._send(404, {"error": "not found"})
        if not self._api_ok():
            return self._send(403, {"error": "bad token"})
        if u.path == "/api/engines":
            return self._send(200, {k: {"label": v["label"], "ready": env_has(v["key"]), "key": v["key"], "sends": v["sends"]} for k, v in ENGINES.items()})
        if u.path == "/api/job":
            jid = (q.get("id") or [""])[0]
            st = JOBSTATE.get(jid)
            if not st:
                return self._send(404, {"error": "unknown job"})
            lg = job_dir(jid) / "log.txt"
            tail = lg.read_text(errors="replace").strip().splitlines()[-8:] if lg.is_file() else []
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
            if not env_has(e["key"]):
                return self._send(400, {"error": f"{e['key']} is not set. Add it to the .env file in the project folder."})
            if e["sends"] and not req.get("confirm"):
                return self._send(400, {"error": "Please confirm you may send these scripts to the AI provider."})
            eps = str(req.get("episodes", "")).strip()
            if eps and not re.fullmatch(r"[0-9,\- ]{1,40}", eps):
                return self._send(400, {"error": "Episodes look like 1-10 or 2,7,33."})
            if not any((job_dir(jid) / "in").iterdir()):
                return self._send(400, {"error": "Add at least one file first."})
            JOBSTATE[jid].update(status="queued")
            threading.Thread(target=run_job, args=(jid, eng, eps.replace(" ", ""), str(req.get("title", ""))[:80]), daemon=True).start()
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--browser", default="Safari")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    JOBS.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"Workbench running at {url}  (Ctrl-C to stop). Files are kept in {JOBS}")
    if not a.no_open:
        subprocess.run(["open", "-a", a.browser, url]) if sys.platform == "darwin" else webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
