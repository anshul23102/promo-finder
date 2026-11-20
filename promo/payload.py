"""Build the review app's data (the PROMO_DATA payload) from a finished run.

One function, `build_payload`, used by BOTH the offline build (ui-claude/build_data.py) and the in-browser runner
(web/worker), so the two always emit the same JSON shape. Pure standard library: runs unchanged in Pyodide.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .screenplay import clean_edges

SCHEMA = 1   # version of the PROMO_DATA shape; the UI refuses a payload it cannot read

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


def build_payload(run: Path, episodes: dict, *, reviews: list | None = None, beats_runs: list | None = None,
                  fill: Path | None = None, demo: bool = False) -> dict:
    """run: a finished run folder. episodes: {number: Episode} for the same input. reviews: parsed reviewer decisions."""
    reviews = reviews or []
    run = Path(run)
    raw = (run / "promos.json").read_bytes()
    data = json.loads(raw)
    summary = data["summary"]
    beat_runs = beats_runs or [run]
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

    ev_path = run / "evaluation.json"
    ev = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.is_file() else {}
    ev_ab = ev.get("ablation_cold_viewer_pass", {})
    quality = {   # numbers only: no script text, safe next to the rest of data.js
        "violations": len(ev.get("rule_violations", [])), "promos": len(takes),
        "writer": {k: ev.get("writer_cliffhangers", {}).get(k) for k in ("labels", "hit_last_10s")},
        "coverage": ev.get("coverage", {}), "rejections": ev.get("rejections", {}),
        "viewer": {"ai": ev_ab.get("ai_editor"), "rules": ev_ab.get("rules")},
        "judge": {k: ev.get("judge", {}).get(k) for k in ("comparisons", "repeat_pair_agreement", "average_place_by_slot")},
        "ratings": (json.loads((run / "ratings_applied.json").read_text(encoding="utf-8")) if (run / "ratings_applied.json").is_file() else None),
        "reviews": [{"id": r["id"], "kind": r["kind"], **{k: (ev_rev.get("all") or {}).get(k) for k in ("n", "keep", "trim", "pass")}}
                    for r in reviews for ev_rev in [next((x for x in ev.get("reviews", []) if x.get("reviewer") == r["name"]), next((x for x in ev.get("reviews", []) if x.get("kind") == r["kind"]), {}))]],
    }
    cov_path = run / "coverage.json"          # the per-episode ledger: the real source of "why does this episode have no promo"
    coverage = []
    for c in (json.loads(cov_path.read_text(encoding="utf-8")) if cov_path.is_file() else []):
        cut = c.get("cut")
        for sg in (cut or {}).get("segments", []):      # review candidates carry mm:ss.xx text only; the page needs centiseconds
            for k in ("start", "end"):
                if sg.get(k + "_cs") is None:
                    m, sec = str(sg[k]).split(":")
                    sg[k + "_cs"] = round((int(m) * 60 + float(sec)) * 100)
        coverage.append({"episode": c["episode"], "status": c.get("status", ""), "reason": c.get("reason", ""),
                         "cut": {"segments": [{k: sg.get(k) for k in ("episode", "start", "end", "start_cs", "end_cs", "duration_s")} for sg in cut["segments"]],
                                 "opening": cut.get("opening", ""), "ending": cut.get("ending", "")} if cut else None})
    filled = 0
    if fill and (fill / "coverage.json").is_file():
        have = {c["episode"] for c in coverage}
        for c in json.loads((fill / "coverage.json").read_text(encoding="utf-8")):
            cut = c.get("cut")
            if c["episode"] in have or not cut:
                continue
            for sg in cut["segments"]:
                for k in ("start", "end"):
                    if sg.get(k + "_cs") is None:
                        m, sec = str(sg[k]).split(":")
                        sg[k + "_cs"] = round((int(m) * 60 + float(sec)) * 100)
            coverage.append({"episode": c["episode"], "status": "Rules candidate",
                             "reason": "Found by word-based rules. No AI judge ran on this episode, so this is material for an editor, not a judged promo.",
                             "cut": {"segments": [{k: sg.get(k) for k in ("episode", "start", "end", "start_cs", "end_cs", "duration_s")} for sg in cut["segments"]],
                                     "opening": cut.get("opening", ""), "ending": cut.get("ending", "")}})
            filled += 1
        coverage.sort(key=lambda c: c["episode"])
    viewed = sum((v or {}).get("viewed", 0) for v in ev_ab.values()) if ev_ab else None
    ai_run = summary.get("editor_model", "rules") != "rules"
    run = {   # what happened in this run, for the header of every page
        "ai": ai_run, "finder": summary.get("finder", ""), "pack": len(episodes), "requested": summary.get("episodes"),
        "scored": len(pulses([run], episodes)) if ai_run and summary.get("finder") == "beats" else None,   # this run's own beat scores only, not older runs shown on the strip
        "candidates": summary.get("candidates"), "judged": viewed if ai_run else None, "shortlisted": summary.get("passed", len(takes)),
        "warnings": list(summary.get("warnings") or []), "filled": filled, "joins": summary.get("joins"), "votes": summary.get("votes"),
    }
    payload = {
        "run": run, "coverage": coverage,
        "quality": quality,
        "id": hashlib.sha256(raw).hexdigest()[:10],
        "show": {"title": summary.get("show", "Untitled show"), "episodes": len(episodes), "cues": summary.get("cues"),
                 "finder": summary.get("finder", ""), "editor": summary.get("editor_model", ""), "judge": summary.get("judge_model", ""),
                 "demo": bool(demo)},
        "reviewers": [{"id": r["id"], "name": r["name"], "kind": r["kind"]} for r in reviews],
        "episodes": eps_out, "takes": takes,
    }
    payload["schema"] = SCHEMA
    return payload
