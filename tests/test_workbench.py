"""The Workbench server: it serves the page with a per-launch token, refuses everything without it, and cannot be walked out of its folder."""
import http.client
import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workbench", ROOT / "ui-claude" / "workbench.py")
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)


class WorkbenchServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        site = Path(cls.tmp.name) / "site"
        site.mkdir()
        (site / "index.html").write_text('<meta name="wb-token" content="__WB_TOKEN__"><p>page</p>', encoding="utf-8")
        (site / "app.js").write_text("// app", encoding="utf-8")
        (Path(cls.tmp.name) / "secret.txt").write_text("outside", encoding="utf-8")
        wb.SITE_DIR = site
        wb.JOBS = Path(cls.tmp.name) / "jobs"
        wb.JOBS.mkdir()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), wb.H)
        cls.port = cls.srv.server_port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def get(self, path, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.putrequest("GET", path, skip_host=True)
        c.putheader("Host", host or f"127.0.0.1:{self.port}")
        for k, v in (headers or {}).items():
            c.putheader(k, v)
        c.endheaders()
        r = c.getresponse()
        return r.status, r.read().decode("utf-8", "replace")

    def test_page_carries_the_token(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(wb.TOKEN, body)
        self.assertNotIn("__WB_TOKEN__", body)

    def test_head_requests_work_and_carry_no_body(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request("HEAD", "/app.js")
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.read(), b"")
        self.assertGreater(int(r.getheader("Content-Length")), 0)

    def test_static_files_are_served_from_the_site_only(self):
        self.assertEqual(self.get("/app.js")[0], 200)
        self.assertEqual(self.get("/../secret.txt")[0], 404)
        self.assertEqual(self.get("/%2e%2e/secret.txt")[0], 404)

    def test_api_needs_the_token_and_the_right_host(self):
        self.assertEqual(self.get("/api/engines")[0], 403)
        self.assertEqual(self.get("/api/engines", {"X-Token": "wrong"})[0], 403)
        status, body = self.get("/api/engines", {"X-Token": wb.TOKEN})
        self.assertEqual(status, 200)
        self.assertIn("rules", json.loads(body))
        self.assertEqual(self.get("/api/engines", {"X-Token": wb.TOKEN}, host="evil.example")[0], 403)
        self.assertEqual(self.get("/", host="evil.example")[0], 403)

    def test_all_means_every_episode(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        h = {"X-Token": wb.TOKEN, "Content-Type": "application/json"}
        c.request("POST", "/api/new", b"", h)
        jid = json.loads(c.getresponse().read())["id"]
        c.request("POST", f"/api/upload?job={jid}&name=episode-001.txt", b"x", h)
        c.getresponse().read()
        started, real = [], wb.run_job
        wb.run_job = lambda *args: started.append(args)       # record the call instead of starting a real run
        try:
            c.request("POST", "/api/run", json.dumps({"job": jid, "engine": "rules", "episodes": "all"}), h)
            r = c.getresponse()
            self.assertEqual(r.status, 200, r.read())
            for _ in range(50):
                if started:
                    break
                threading.Event().wait(0.02)
        finally:
            wb.run_job = real
        self.assertEqual(started[0][2], "")        # all becomes no episode filter
        c.request("POST", "/api/run", json.dumps({"job": jid, "engine": "rules", "episodes": "1; rm"}), h)
        self.assertEqual(c.getresponse().status, 400)


    def test_other_engines_take_a_model_and_a_key_for_one_run(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        h = {"X-Token": wb.TOKEN, "Content-Type": "application/json"}
        c.request("GET", "/api/engines", headers=h)
        engines = json.loads(c.getresponse().read())
        for name in ("openai", "openrouter", "custom"):
            self.assertIn(name, engines)
        c.request("POST", "/api/new", b"", h)
        jid = json.loads(c.getresponse().read())["id"]
        c.request("POST", f"/api/upload?job={jid}&name=episode-001.txt", b"x", h)
        c.getresponse().read()
        started, real = [], wb.run_job
        wb.run_job = lambda *args: started.append(args)
        wb.ENGINES["custom"]["sends"] = "x"
        try:
            def run(body):
                c.request("POST", "/api/run", json.dumps({"job": jid, "confirm": True, **body}), h)
                r = c.getresponse()
                return r.status, json.loads(r.read())
            self.assertEqual(run({"engine": "custom", "api_key": "sk-test-1234567", "base_url": "https://example.com/v1"})[0], 400)       # no model name
            self.assertEqual(run({"engine": "custom", "model": "m", "api_key": "has space 12345", "base_url": "https://example.com/v1"})[0], 400)
            self.assertEqual(run({"engine": "custom", "model": "m", "api_key": "sk-test-1234567", "base_url": "javascript:alert(1)"})[0], 400)
            self.assertEqual(run({"engine": "rules", "model": "m"})[0], 400)        # an engine without a model choice refuses one
            status, _ = run({"engine": "custom", "model": "my-model", "api_key": "sk-test-1234567", "base_url": "https://example.com/v1"})
            self.assertEqual(status, 200)
            for _ in range(50):
                if started:
                    break
                threading.Event().wait(0.02)
            args = started[-1]
            self.assertEqual(args[4], "my-model")
            self.assertEqual(args[5], {"PROMO_API_KEY": "sk-test-1234567", "PROMO_BASE_URL": "https://example.com/v1"})
            self.assertNotIn("sk-test", json.dumps(wb.JOBSTATE))      # the key is never kept in the job record
        finally:
            wb.run_job = real


    def test_a_run_can_be_stopped(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        h = {"X-Token": wb.TOKEN, "Content-Type": "application/json"}
        c.request("POST", "/api/new", b"", h)
        jid = json.loads(c.getresponse().read())["id"]
        c.request("POST", "/api/cancel", json.dumps({"job": jid}), h)
        self.assertEqual(c.getresponse().status, 200)
        self.assertTrue(wb.JOBSTATE[jid]["cancelled"])
        (wb.job_dir(jid) / "in" / "episode-001.txt").write_text("x", encoding="utf-8")
        wb.run_job(jid, "rules", "", "t")               # a stopped job never starts its process
        self.assertEqual(wb.JOBSTATE[jid]["status"], "cancelled")
        c.request("POST", "/api/cancel", json.dumps({"job": "0" * 12}), h)
        self.assertEqual(c.getresponse().status, 400)


if __name__ == "__main__":
    unittest.main()
