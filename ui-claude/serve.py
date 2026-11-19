"""Build the cutting room from a finished run, serve it on localhost only, and open it in a browser.

    python3 ui-claude/serve.py --run <run folder> --pack <scripts zip or folder> [--beats <run>] [--review "id|name|kind|csv"] \
        [--out private/ui-claude] [--port 8766] [--browser Safari] [--no-open]

Everything else is passed to build_data.py. The server binds 127.0.0.1 only and never caches, so a rebuild shows at once.
The built folder contains script text: keep it private.
"""
import argparse
import functools
import http.server
import subprocess
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser(add_help=False)
ap.add_argument("--port", type=int, default=8766)
ap.add_argument("--browser", default="Safari")
ap.add_argument("--no-open", action="store_true")
ap.add_argument("--out", default="private/ui-claude")
own, rest = ap.parse_known_args()

subprocess.run([sys.executable, str(HERE / "build_data.py"), "--out", own.out, *rest], check=True)


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):  # quiet
        pass


url = f"http://127.0.0.1:{own.port}/"
server = http.server.ThreadingHTTPServer(("127.0.0.1", own.port), functools.partial(Handler, directory=own.out))
print(f"Cutting room running at {url}  (Ctrl-C to stop)")
if not own.no_open:
    if sys.platform == "darwin":
        subprocess.run(["open", "-a", own.browser, url])
    else:
        webbrowser.open(url)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
