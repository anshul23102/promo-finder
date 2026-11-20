"""Version 1 of the run contract: one JSON document another system can consume without our UI.

    python3 -m promo.contract RUN_FOLDER INPUT --out contract.json

The document describes WHAT was asked (input identity, mode), WHAT came back (ordered segments with evidence and status),
HOW the run went (state, counts, warnings, models) and enough to check it (hashes, an idempotency key). It never says a cut
is approved: a person decides that, in `review`, and the editor handoff is a separate document (see apply_review).
Pure standard library. Readers must reject a `schema` they do not know (validate() does).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .screenplay import load_episodes

SCHEMA = "promo-finder.run/1"
HANDOFF_SCHEMA = "promo-finder.handoff/1"
STATES = ("queued", "running", "partial", "succeeded", "failed", "cancelled")
SUGGESTION_STATUS = ("timing_checked", "judge_shortlisted", "human_approved")   # this file only ever writes the first two
DECISIONS = ("keep", "trim", "pass")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def engine_sha256() -> str:
    """Hash of the finder's own source files, so a result says exactly which code made it."""
    return _sha(b"".join(p.name.encode() + b"\0" + p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py"))))


def _slug(text: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")
    return "-".join(part for part in out.split("-") if part) or "show"


def build_contract(run: Path, episodes: dict, *, input_name: str, input_sha256: str, source_revision: str | None = None,
                   locale: str | None = None, audience: str | None = None, engine_version: str = "1") -> dict:
    """run: a finished run folder (promos.json, coverage.json, run_summary.json ...). episodes: {number: Episode}."""
    run = Path(run)
    data = json.loads((run / "promos.json").read_bytes())
    summary = data["summary"]
    model = summary.get("editor_model", "rules")
    mode = "rules" if model == "rules" else "ai"
    config = {"mode": mode, "editor_model": model, "judge_model": summary.get("judge_model", "none"), "finder": summary.get("finder", "rules"),
              "duration_s": [20, 60], "hook_window_s": 3}
    config_sha = _sha(json.dumps(config, sort_keys=True).encode())
    engine = engine_sha256()
    key = _sha(f"{input_sha256}|{config_sha}|{engine}".encode())[:24]
    warnings = list(summary.get("warnings") or [])
    state = "partial" if warnings else "succeeded"
    ep_id = lambda n: f"E{n:03d}"            # noqa: E731

    suggestions = []
    for p in data["promos"]:
        judged = p.get("source") not in ("rules", "recovery") or bool(p.get("viewer"))
        suggestions.append({
            "id": p["id"], "rank": p["rank"], "post_slot": p["plan"],
            "status": "judge_shortlisted" if judged else "timing_checked",
            "segments": [{"episode_id": ep_id(s["episode"]), "episode": s["episode"], "start_cs": s["start_cs"], "end_cs": s["end_cs"],
                          "duration_cs": s["end_cs"] - s["start_cs"]} for s in p["segments"]],
            "duration_cs": round(p["duration_s"] * 100),
            "opening": {"cue_ids": [f"E{p['hook_cue'][0]:02d}-{p['hook_cue'][1]:03d}"] if p.get("hook_cue") else [], "text": p.get("hook", "")},
            "closing": {"cue_ids": [p["end_cue"]] if p.get("end_cue") else [], "text": p.get("cliffhanger", "")},
            "rationale": p.get("why", ""), "rationale_source": p.get("why_source", "template"),
            "spoiler": p.get("spoiler", "none"),
            "provenance": {"found_by": p.get("source", "rules"), "scored_by": model if mode == "ai" else None,
                           "judged_by": summary.get("judge_model") if judged and mode == "ai" else None},
        })

    outputs = {f.name: _sha(f.read_bytes()) for f in sorted(run.iterdir()) if f.is_file() and f.suffix in (".csv", ".md", ".edl")}
    return {
        "schema": SCHEMA,
        "run_id": "run-" + key,
        "engine": {"name": "promo-finder", "version": engine_version, "sha256": engine,
                   "rules_version": "rules-1" if mode == "rules" else None},
        "input": {
            "show_id": _slug(summary.get("show", "show")), "title": summary.get("show", ""), "mode": mode,
            "locale": locale, "target_audience": audience,
            "source": {"name": input_name, "sha256": input_sha256, "revision": source_revision, "kind": "txt" if input_name.lower().endswith(".txt") else "zip"},
            "episodes": [{"episode_id": ep_id(n), "number": n, "cues": len(e.cues), "duration_cs": e.duration} for n, e in sorted(episodes.items())],
        },
        "timeline": {"unit": "centisecond", "range": "start inclusive, end exclusive", "times_are": "relative to the start of each episode, in the user's source timebase",
                     "media_timebase": None, "reference_edl_fps": 30,
                     "note": "Frame rates are not in the scripts. Cutlist.edl is a 30 fps non-drop reference until footage conforms."},
        "status": {
            "state": state, "episodes_requested": summary.get("episodes"), "episodes_parsed": len(episodes),
            "candidates": summary.get("candidates"), "shortlisted": summary.get("passed"),
            "fallbacks": [w for w in warnings if "timing-based" in w or "unavailable" in w],
            "warnings": warnings, "models": {"editor": model, "judge": summary.get("judge_model", "none")}, "usage": summary.get("usage") or [],
        },
        "suggestions": suggestions,
        "review": {"decisions": [], "ready_requires_human_decision": True,
                   "note": "Nothing here is approved. A person marks a cut ready; the approved cut list is the separate handoff document."},
        "invariants": {"input_sha256": input_sha256, "config_sha256": config_sha, "config": config, "idempotency_key": key, "outputs_sha256": outputs},
    }


def validate(doc: dict) -> list[str]:
    """Problems with a run document, empty if it is readable. Rejects a schema version it does not know."""
    if not isinstance(doc, dict):
        return ["not an object"]
    if doc.get("schema") != SCHEMA:
        return [f"unknown schema {doc.get('schema')!r}: this reader understands {SCHEMA!r} only"]
    problems = []
    for key in ("run_id", "engine", "input", "timeline", "status", "suggestions", "review", "invariants"):
        if key not in doc:
            problems.append(f"missing {key}")
    if problems:
        return problems
    if doc["status"].get("state") not in STATES:
        problems.append(f"status.state must be one of {STATES}")
    seen = set()
    for i, s in enumerate(doc["suggestions"]):
        where = f"suggestions[{i}]"
        if s.get("id") in seen:
            problems.append(f"{where}: duplicate id {s.get('id')}")
        seen.add(s.get("id"))
        if s.get("status") not in SUGGESTION_STATUS:
            problems.append(f"{where}: unknown status {s.get('status')!r}")
        if s.get("status") == "human_approved":
            problems.append(f"{where}: a run document must not contain approved cuts")
        segs = s.get("segments") or []
        if not segs:
            problems.append(f"{where}: no segments")
        for g in segs:
            if not (isinstance(g.get("start_cs"), int) and isinstance(g.get("end_cs"), int) and 0 <= g["start_cs"] < g["end_cs"]):
                problems.append(f"{where}: segment times must be integer centiseconds with start < end")
        if sum(g.get("end_cs", 0) - g.get("start_cs", 0) for g in segs) != s.get("duration_cs"):
            problems.append(f"{where}: duration_cs does not equal the sum of its segments")
    return problems


def apply_review(doc: dict, decisions: list[dict]) -> dict:
    """Turn a run document plus a person's decisions into the editor handoff. Only an explicit human 'keep'/'trim' enters `ready`.

    decision: {"id": suggestion id, "decision": keep|trim|pass, "reviewer": str, "reviewed_at": str|None,
               "proposed": [{"start_cs": int, "end_cs": int}] (optional trimmed first segment)}.
    A trim that breaks the 20-60 s rule, or any change after the descriptions were written, flags the cut for re-review.
    """
    problems = validate(doc)
    if problems:
        raise ValueError("cannot hand off an unreadable run: " + "; ".join(problems))
    by_id = {s["id"]: s for s in doc["suggestions"]}
    ready, left_out = [], []
    for d in decisions:
        s = by_id.get(d.get("id"))
        if s is None:
            raise ValueError(f"decision for unknown suggestion {d.get('id')!r}")
        if d.get("decision") not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}")
        if not d.get("reviewer"):
            raise ValueError("every decision needs a named reviewer")
        if d["decision"] == "pass":
            left_out.append({"id": s["id"], "reason": "reviewer passed"})
            continue
        segs = [dict(g) for g in s["segments"]]
        proposed = d.get("proposed")
        status, needs_rereview = "original_boundaries", False
        if proposed:
            first = segs[0]
            first["start_cs"], first["end_cs"] = proposed[0]["start_cs"], proposed[0]["end_cs"]
            total = sum(g["end_cs"] - g["start_cs"] for g in segs)
            if first["end_cs"] <= first["start_cs"] or not 2000 <= total <= 6000:
                left_out.append({"id": s["id"], "reason": "trim breaks the 20-60 second rule; original boundaries kept for re-review"})
                continue
            first["duration_cs"] = first["end_cs"] - first["start_cs"]
            status, needs_rereview = "trimmed_by_reviewer", True
        ready.append({"id": s["id"], "rank": s["rank"], "segments": segs, "duration_cs": sum(g["duration_cs"] for g in segs), "boundary_status": status,
                      "opening": s["opening"], "closing": s["closing"], "rationale": s["rationale"],
                      "needs_rereview": needs_rereview,
                      "note": "Hook, closing and rationale were written for the original cut." if needs_rereview else "",
                      "decision": d["decision"], "reviewer": d["reviewer"], "reviewed_at": d.get("reviewed_at")})
    return {"schema": HANDOFF_SCHEMA, "run_id": doc["run_id"], "source_sha256": doc["input"]["source"]["sha256"],
            "source_revision": doc["input"]["source"]["revision"], "timeline": doc["timeline"], "ready": ready, "left_out": left_out}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("input", type=Path, help="The same ZIP, folder or .txt the run read")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    episodes = {e.number: e for e in load_episodes(args.input)}
    raw = args.input.read_bytes() if args.input.is_file() else _sha(b"".join(p.read_bytes() for p in sorted(args.input.rglob("*.txt")))).encode()
    doc = build_contract(args.run, episodes, input_name=args.input.name, input_sha256=_sha(raw))
    bad = validate(doc)
    if bad:
        raise SystemExit("contract invalid: " + "; ".join(bad))
    out = args.out or args.run / "contract.json"
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out} ({len(doc['suggestions'])} suggestions, {doc['status']['state']})")


if __name__ == "__main__":
    main()
