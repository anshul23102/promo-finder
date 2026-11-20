"""Model-swap smoke test against a local stand-in for an OpenAI-compatible endpoint. No key, no network, no real model.

    python3 tools/swap_smoke_test.py

Proves, on the made-up show, with the exact command a real endpoint would use (--model openai-compatible:<name> plus
PROMO_BASE_URL and PROMO_API_KEY):
  1. structured answers arrive, are validated, and the run says which model made them;
  2. the same run again under a NEW output folder is replayed from the cache: zero new calls;
  3. a wrong key is refused, and the run reports the problem instead of presenting itself as a full AI run;
  4. an endpoint that fails with HTTP 500 does the same, and the result stays usable (rules fallback).
The stand-in answers from the request's own JSON schema, so it checks the contract, not model quality.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = "test-key-not-a-secret"


def fake(schema: dict, prompt: str, path=()):
    """A value that satisfies `schema`, using cue ids and letters found in the prompt where the schema cannot say."""
    kind = schema.get("type")
    if "enum" in schema:
        return schema["enum"][0]
    if kind == "object":
        return {k: fake(v, prompt, path + (k,)) for k, v in schema.get("properties", {}).items()}
    if kind == "array":
        item = schema["items"]
        if "enum" in item:
            return list(item["enum"])                       # a ranking ballot: every letter once
        cues = re.findall(r"\bE\d+-\d+\b", prompt)
        if path and path[-1] == "beats":                    # score every 6th line as a strong opening and every 5th as a strong ending
            return [{"cue": c, "hook": 4 if i % 6 == 0 else 0, "cliff": 4 if i % 5 == 2 else 0, "question": "What happens next?"} for i, c in enumerate(cues)]
        return [fake(item, prompt, path + ("[]",)) for _ in range(1)]
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return True
    return "A short answer from the stand-in model."


class Handler(BaseHTTPRequestHandler):
    mode = "ok"
    hits = 0
    seen_keys: list[str] = []

    def do_POST(self):
        type(self).hits += 1
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        type(self).seen_keys.append(self.headers.get("Authorization", ""))
        if self.mode == "500":
            return self.reply(500, {"error": {"message": "stand-in server failure"}})
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            return self.reply(401, {"error": {"message": "bad key"}})
        schema = body["response_format"]["json_schema"]["schema"]
        prompt = "\n".join(m["content"] for m in body["messages"])
        answer = fake(schema, prompt)
        self.reply(200, {"choices": [{"message": {"content": json.dumps(answer)}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    def reply(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_):
        pass


def run(args: list[str], port: int, key: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PROMO_BASE_URL": f"http://127.0.0.1:{port}/v1", "PROMO_API_KEY": key}
    return subprocess.run([sys.executable, "-m", "promo", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    tmp = Path(tempfile.mkdtemp())
    show = ROOT / "examples" / "last-edition"
    common = ["--model", "openai-compatible:stand-in", "--no-guide", "--rounds", "1", "--no-rules-check", "--cache", str(tmp / "cache")]
    failures = []

    def check(ok: bool, what: str):
        print(("ok   " if ok else "FAIL ") + what)
        if not ok:
            failures.append(what)

    # 1. structured answers and provenance
    Handler.mode, Handler.hits = "ok", 0
    first = run([str(show), *common, "--out", str(tmp / "run1")], port, KEY)
    check(first.returncode == 0, f"first run exits cleanly ({first.stderr.strip()[-160:] or 'no stderr'})")
    summary = json.loads((tmp / "run1" / "run_summary.json").read_text(encoding="utf-8"))
    calls = Handler.hits
    check(calls > 0, f"the endpoint was called ({calls} requests)")
    check(summary["editor_model"] == "openai-compatible:stand-in", f"provenance names the model (editor_model={summary['editor_model']!r})")
    answers = [json.loads(line) for line in (tmp / "run1" / "model_calls.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    check(len(answers) > 0 and all("answer" in a for a in answers), f"every saved model reply carries a validated answer ({len(answers)} saved)")
    check(set(Handler.seen_keys) == {f"Bearer {KEY}"}, "the key was sent as a bearer token from the environment, nowhere else")
    check(not any(KEY in p.read_text(encoding="utf-8", errors="ignore") for p in (tmp / "run1").rglob("*") if p.is_file()), "the key does not appear in any output file")

    # 2. replay from cache under a new output folder
    before = Handler.hits
    second = run([str(show), *common, "--out", str(tmp / "run2")], port, KEY)
    summary2 = json.loads((tmp / "run2" / "run_summary.json").read_text(encoding="utf-8"))
    check(second.returncode == 0 and Handler.hits == before, f"re-run under a new folder made no new calls ({Handler.hits - before} new)")
    check(sum(u.get("cache_hits", 0) for u in summary2["usage"]) > 0, "usage reports cache hits")

    # 3. wrong key
    Handler.hits = 0
    bad = run([str(show), "--model", "openai-compatible:stand-in", "--no-guide", "--rounds", "1", "--cache", str(tmp / "cache-bad"), "--out", str(tmp / "run3")], port, "wrong-key")
    text = (tmp / "run3" / "run_summary.json").read_text(encoding="utf-8") if (tmp / "run3" / "run_summary.json").is_file() else ""
    refused = "401" in bad.stdout + bad.stderr + text
    check(refused, "a wrong key is refused and the problem is reported")
    if text:
        s3 = json.loads(text)
        check(bool(s3.get("warnings")), "the result carries a warning instead of passing as a full AI run")

    # 4. endpoint failure
    Handler.mode = "500"
    down = run([str(show), "--model", "openai-compatible:stand-in", "--no-guide", "--rounds", "1", "--cache", str(tmp / "cache-down"), "--out", str(tmp / "run4")], port, KEY)
    s4p = tmp / "run4" / "run_summary.json"
    if s4p.is_file():
        s4 = json.loads(s4p.read_text(encoding="utf-8"))
        check(bool(s4.get("warnings")) and any("500" in w or "stopped" in w.lower() or "unavailable" in w.lower() for w in s4["warnings"]),
              "an HTTP 500 is reported in the run's warnings, not hidden")
        check(s4.get("candidates", 0) > 0, f"the result is still usable: {s4.get('candidates')} timing-based candidates (rules fallback)")
    else:
        check("500" in down.stdout + down.stderr and down.returncode != 0, "an HTTP 500 stops the run with a plain message")

    server.shutdown()
    print("\nAll model-path checks passed." if not failures else f"\n{len(failures)} check(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
