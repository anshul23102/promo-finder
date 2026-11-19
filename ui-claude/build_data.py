"""Build the Cutting Room app: copy the static UI and write data.js from a finished run.

    python3 ui-claude/build_data.py --run private/runs/v5-eval-final --pack <scripts.zip or folder> \
        --beats private/runs/v4-full --beats private/runs/v5-eval-final \
        --review "applicant|You (blind page)|human|private/reviews/applicant-blind-b969062d.csv" \
        --review "codex|Codex (second AI)|ai|private/reviews/v5-codex/codex-decisions.csv" \
        --out private/ui-claude

The output contains script text: keep it under private/ and do not publish it. The UI code itself
(index.html, app.css, app.js, fonts) holds no show content and is safe to publish.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from promo.screenplay import clean_edges, load_episodes, stamp  # noqa: E402

BEFORE, AFTER = 1200, 1500           # centiseconds of context kept around a cut (12 s before, 15 s after)
KIND = {"dialogue": "d", "action": "a", "camera": "c", "sound": "s"}


def segment_key(segments) -> str:
    return " | ".join(f"Ep {s['episode']} [{s['start']} – {s['end']}]" for s in segments)


def window(ep, seg, edges):
    lo, hi = max(0, seg["start_cs"] - BEFORE), min(ep.duration, seg["end_cs"] + AFTER)
    cues = [{"id": c.id, "k": KIND[c.kind], "who": c.speaker.title() if c.kind == "dialogue" else "",
             "text": c.text.strip().strip('"“”'), "s": c.start, "e": c.end}
            for c in ep.cues if c.end > lo and c.start < hi]
    shots = sorted({c.start for c in ep.cues if c.kind == "camera" and lo <= c.start <= hi and c.start in edges})
    return {"episode": ep.number, "start": seg["start_cs"], "end": seg["end_cs"], "lo": lo, "hi": hi,
            "duration": ep.duration, "cues": cues, "edges": sorted(t for t in edges if lo <= t <= hi), "shots": shots}


def pulses(runs: list[Path], episodes) -> dict:
    """Per episode: [[position 0..1, hook score, cliff score], ...] from the models' beat scores (later runs override)."""
    out = {}
    for run in runs:
        path = run / "model_calls.jsonl"
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            stage = rec.get("stage", "")
            if not stage.startswith("beats-e"):
                continue
            n = int(stage[7:9])
            ep = episodes.get(n)
            if ep is None:
                continue
            by_id = {c.id: c for c in ep.cues}
            points = []
            for b in rec["answer"]["beats"]:
                m = re.search(r"E\d+-(\d+)", str(b["cue"]))   # models sometimes echo the whole script line, not just the ID
                cue = by_id.get(int(m.group(1))) if m else None
                if cue and (b["hook"] or b["cliff"]):
                    points.append([round(cue.start / max(1, ep.duration), 4), int(b["hook"]), int(b["cliff"])])
            out[n] = {"scored_by": rec.get("model", ""), "points": points}
    return out


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
    ap.add_argument("--demo", action="store_true", help="Mark the data as a made-up demo show (the UI shows a banner)")
    args = ap.parse_args()

    episodes = {e.number: e for e in load_episodes(args.pack)}
    raw = (args.run / "promos.json").read_bytes()
    data = json.loads(raw)
    summary = data["summary"]
    reviews = [read_review(s) for s in args.review]
    beat_runs = args.beats or [args.run]
    pulse = pulses(beat_runs, episodes)

    takes = []
    for p in data["promos"]:
        segs, edges_cache = [], {}
        for s in p["segments"]:
            ep = episodes[s["episode"]]
            edges = edges_cache.setdefault(ep.number, clean_edges(ep))
            segs.append(window(ep, s, edges))
        key = segment_key(p["segments"])
        v = p.get("viewer") or {}
        takes.append({
            "id": p["id"], "rank": p["rank"], "plan": p["plan"], "source": p["source"], "episode": p["episode"],
            "duration": p["duration_s"], "key": key, "segments": segs,
            "ai": {"hook": p["hook"], "hookType": p.get("hook_type", ""), "cliff": p["cliffhanger"], "why": p["why"],
                   "spoiler": p.get("spoiler", "none"), "planReason": p.get("plan_reason", ""),
                   "opening": p.get("opening_3s", ""), "viewer": {k: v.get(k, "") for k in
                   ("who", "situation", "open_question", "first_3s", "makes_sense", "ending", "confusing")}},
            "next": p.get("next_beat", ""),
            "reviews": {r["id"]: r["decisions"].get(key) for r in reviews if r["decisions"].get(key)},
            "suggest": {r["id"]: r["suggestions"][key] for r in reviews if key in r["suggestions"]},
        })

    by_ep = {}
    for t in takes:
        by_ep.setdefault(t["episode"], []).append(t["id"])
    eps_out = [{"n": n, "duration": e.duration, "logline": e.logline, "takes": by_ep.get(n, []),
                "pulse": pulse.get(n, {}).get("points", []), "scored": n in pulse}
               for n, e in sorted(episodes.items())]

    ev_path = args.run / "evaluation.json"
    ev = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.is_file() else {}
    ev_ab = ev.get("ablation_cold_viewer_pass", {})
    quality = {   # numbers only: no script text, safe next to the rest of data.js
        "violations": len(ev.get("rule_violations", [])), "promos": len(takes),
        "writer": {k: ev.get("writer_cliffhangers", {}).get(k) for k in ("labels", "hit_last_10s")},
        "coverage": ev.get("coverage", {}), "rejections": ev.get("rejections", {}),
        "viewer": {"ai": ev_ab.get("ai_editor"), "rules": ev_ab.get("rules")},
        "judge": {k: ev.get("judge", {}).get(k) for k in ("comparisons", "repeat_pair_agreement", "average_place_by_slot")},
        "agreement": ev.get("review_agreement"),
        "reviews": [{"id": r["id"], "kind": r["kind"], **{k: (ev_rev.get("all") or {}).get(k) for k in ("n", "keep", "trim", "pass")}}
                    for r in reviews for ev_rev in [next((x for x in ev.get("reviews", []) if x.get("reviewer") == r["name"]), {})]],
    }
    payload = {
        "quality": quality,
        "id": hashlib.sha256(raw).hexdigest()[:10],
        "show": {"title": summary.get("show", "Untitled show"), "episodes": len(episodes), "cues": summary.get("cues"),
                 "finder": summary.get("finder", ""), "editor": summary.get("editor_model", ""), "judge": summary.get("judge_model", ""),
                 "demo": bool(args.demo)},
        "reviewers": [{"id": r["id"], "name": r["name"], "kind": r["kind"]} for r in reviews],
        "episodes": eps_out, "takes": takes,
    }
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    stamp_id = str(int(time.time()))          # a new query string on every build, so browsers never serve a stale copy
    for name in ("app.css", "app.js"):
        shutil.copy2(HERE / name, out / name)
    html = (HERE / "index.html").read_text(encoding="utf-8")
    for ref in ("fonts.css", "app.css", "data.js", "app.js"):
        html = html.replace(f'"{ref}"', f'"{ref}?v={stamp_id}"')
    (out / "index.html").write_text(html, encoding="utf-8")
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
