"""Write the results page next to a run's files, so the run's index.html opens offline and is the same page as the live demo.

The page is the static app in ui-claude/ plus a data.js built from the run's own files. Nothing is fetched and nothing is uploaded.
Only the command-line path calls this; the in-browser runner has no ui-claude folder and writes none of it.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .payload import build_payload

UI = Path(__file__).resolve().parent.parent / "ui-claude"
STATIC = ("app.css", "app.js", "review.css", "review.js")


def write_viewer(out: Path, episodes: dict) -> bool:
    """out: a finished run folder. Returns False if the app files are not next to this package."""
    if not (UI / "app.js").is_file():
        return False
    payload = build_payload(out, episodes, beats_runs=[out])
    for name in STATIC:
        shutil.copy2(UI / name, out / name)
    shutil.copy2(UI / "index.html", out / "index.html")
    shutil.copy2(UI / "fonts" / "fonts.css", out / "fonts.css")
    (out / "fonts").mkdir(exist_ok=True)
    for f in (UI / "fonts").glob("*.woff2"):
        shutil.copy2(f, out / "fonts" / f.name)
    (out / "data.js").write_text("window.PROMO_DATA = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    return True
