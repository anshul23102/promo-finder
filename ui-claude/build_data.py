"""Build the Cutting Room app: copy the static UI and write data.js from a finished run.

    python3 ui-claude/build_data.py --run private/runs/v5-eval-final --pack <scripts.zip or folder> \
        --beats private/runs/v4-full --beats private/runs/v5-eval-final \
        --review "applicant|You (blind page)|human|private/reviews/applicant-blind-b969062d.csv" \
        --out private/ui-claude

The output contains script text: keep it under private/ and do not publish it. The UI code itself
(index.html, app.css, app.js, fonts) holds no show content and is safe to publish.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from promo.payload import build_payload  # noqa: E402
from promo.screenplay import load_episodes  # noqa: E402


def read_review(spec: str):
    rid, name, kind, path = (spec.split("|") + [""] * 4)[:4]
    decisions, suggestions = {}, {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            key = (row.get("segments_in_order") or "").strip()
            if key and row.get("decision") in ("keep", "trim", "pass"):
                decisions[key] = row["decision"]
                if row.get("suggested_in") or row.get("suggested_out"):
                    suggestions[key] = [row.get("suggested_in", ""), row.get("suggested_out", "")]
    return {"id": rid, "name": name, "kind": kind or "human", "decisions": decisions, "suggestions": suggestions}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--pack", type=Path, required=True)
    ap.add_argument("--beats", type=Path, action="append", default=[])
    ap.add_argument("--review", action="append", default=[], help="id|name|kind|csv (repeatable)")
    ap.add_argument("--out", type=Path, default=Path("private/ui-claude"))
    ap.add_argument("--fill", type=Path, help="A no-AI run over the whole pack. Its cuts for episodes the main run did not cover are added as rules candidates (never as judged promos)")
    ap.add_argument("--demo", action="store_true", help="Mark the data as a made-up demo show (the UI shows a banner)")
    args = ap.parse_args()

    episodes = {e.number: e for e in load_episodes(args.pack)}
    reviews = [read_review(spec) for spec in args.review]
    payload = build_payload(args.run, episodes, reviews=reviews, beats_runs=args.beats, fill=args.fill, demo=args.demo)
    takes, eps_out = payload["takes"], payload["episodes"]
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    stamp_id = str(int(time.time()))          # a new query string on every build, so browsers never serve a stale copy
    for name in ("app.css", "app.js"):
        shutil.copy2(HERE / name, out / name)
    html = (HERE / "index.html").read_text(encoding="utf-8")
    for ref in ("fonts.css", "app.css", "data.js", "app.js"):
        html = html.replace(f'"{ref}"', f'"{ref}?v={stamp_id}"')
    (out / "index.html").write_text(html, encoding="utf-8")
    rv = out / "review"                       # the optional review studio, its own page next to the results page
    rv.mkdir(exist_ok=True)
    for name in ("review.css", "review.js"):
        shutil.copy2(HERE / "review" / name, rv / name)
    rhtml = (HERE / "review" / "index.html").read_text(encoding="utf-8")
    for ref in ("../fonts.css", "review.css", "../data.js", "review.js"):
        rhtml = rhtml.replace(f'"{ref}"', f'"{ref}?v={stamp_id}"')
    (rv / "index.html").write_text(rhtml, encoding="utf-8")
    shutil.copy2(HERE / "fonts" / "fonts.css", out / "fonts.css")
    (out / "fonts").mkdir(exist_ok=True)
    for f in (HERE / "fonts").glob("*.woff2"):
        shutil.copy2(f, out / "fonts" / f.name)
    (out / "data.js").write_text("window.PROMO_DATA = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    kb = (out / "data.js").stat().st_size // 1024
    print(f"built {out}: {len(takes)} takes, {len(eps_out)} episodes ({sum(e['scored'] for e in eps_out)} with beat pulses), "
          f"{len(reviews)} reviewers, data.js {kb} KB")


if __name__ == "__main__":
    main()
