"""Write every output an editor or reviewer needs, from one run, unedited."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from . import plan
from .ai import clip_text
from .cuts import HOOK_WINDOW, following
from .llm import save_json
from .report import render_report
from .screenplay import stamp

FPS = 30  # assumed timeline rate for the EDL cut list


def safe_cell(value):
    """Stop a spreadsheet from running a model- or script-supplied cell as a formula."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def promo_row(e: dict, episodes) -> dict:
    cut = e["cut"]
    segs = []
    for s in cut.segments:
        segs.append({**s.as_dict(), "start_cs": s.start, "end_cs": s.end})
    last = cut.segments[-1]
    after = following(episodes[last.episode], last)
    hook_ep, hook_id = cut.hook_ref.lstrip("E").split("-")
    view = e.get("view") or {}
    first = cut.segments[0]
    ep0 = episodes[first.episode]
    opening = " / ".join(c.text for c in ep0.cues if c.kind in ("dialogue", "action") and first.start <= c.start < first.start + HOOK_WINDOW)
    hook, question, why = e["hook"], e["open_question"], e["why"]
    if cut.source == "rules":  # the no-AI finder only has raw cue text; use what a stranger actually took from the clip
        hook = opening or hook
        question = view.get("open_question") or question
        why = (f"Found by the no-AI rules. A cold viewer read it as: {view['situation']}" if view.get("situation") else why)
    e = {**e, "hook": hook, "open_question": question, "why": why}
    return {
        "id": e["id"], "rank": e["rank"], "plan": e["plan"], "score": e["score"], "appeal": e["appeal"],
        "episode": cut.first_episode, "episodes": sorted({s.episode for s in cut.segments}),
        "start": segs[0]["start"], "end": segs[-1]["end"], "segments": segs,
        "duration_s": cut.length / 100, "source": cut.source, "hook_type": e["hook_type"],
        "hook": e["hook"], "cliffhanger": e["open_question"], "why": e["why"], "spoiler": e["spoiler"],
        "plan_reason": plan.reason(e), "hook_cue": [int(hook_ep), int(hook_id)], "end_cue": cut.end_ref,
        "viewer": view, "cut_notes": cut.notes, "next_beat": " / ".join(c.text for c in after),
        "next_beat_time": stamp(after[0].start) if after else None,
        "script": clip_text(cut, episodes, {}),
        # fields the review page already understands
        "opening_3s": opening, "opening_evidence": opening or e["hook"], "closing_evidence": view.get("open_question", e["open_question"]),
        "method": {"editor": "AI editor + cold viewer", "joined": "Joined across episodes", "rules": "Rules baseline"}[cut.source],
    }


def timecode(cs: int) -> str:
    frames = round(cs * FPS / 100)
    h, rem = divmod(frames, 3600 * FPS)
    m, rem = divmod(rem, 60 * FPS)
    s, f = divmod(rem, FPS)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def edl(rows: list[dict], title: str) -> str:
    """CMX3600 cut list: each promo's segments laid end to end; reel = episode."""
    lines = [f"TITLE: {title[:60]} promos", "FCM: NON-DROP FRAME", ""]
    event, record = 1, 3600 * 100  # promos start at 01:00:00:00, 5 s gap between promos
    for r in rows:
        if r["plan"] != "post_first":
            continue
        for s in r["segments"]:
            length = s["end_cs"] - s["start_cs"]
            lines.append(f"{event:03d}  EP{s['episode']:03d}   V     C        {timecode(s['start_cs'])} {timecode(s['end_cs'])} "
                         f"{timecode(record)} {timecode(record + length)}")
            lines.append(f"* FROM CLIP NAME: episode-{s['episode']:03d}")
            lines.append(f"* COMMENT: {r['id']} rank {r['rank']} - {r['hook'][:70]}")
            event += 1
            record += length
        record += 500
    return "\n".join(lines) + "\n"


def plan_markdown(rows, summary) -> str:
    out = [f"# Posting plan: {summary['show']}", "",
           f"{summary['passed']} promos passed the rule checks and the cold viewer, out of {summary['candidates']} candidates. "
           f"Editor model `{summary['editor_model']}`, judge `{summary['judge_model']}`.", "",
           "## Post first", "", "| # | Promo | Cut (episode, in-out) | Hook | Cliffhanger | Why it works | Why this slot |",
           "|---|---|---|---|---|---|---|"]
    def cell(x):
        return str(x).replace("|", "/").replace("\n", " ")
    for r in rows:
        if r["plan"] == "post_first":
            segs = "; ".join(f"E{s['episode']} {s['start']}-{s['end']}" for s in r["segments"])
            out.append(f"| {r['rank']} | {r['id']} ({r['duration_s']:.1f}s) | {segs} | {cell(r['hook'])} | "
                       f"{cell(r['cliffhanger'])} | {cell(r['why'])} | {cell(r['plan_reason'])} |")
    for title, key in (("Library (good, post later)", "library"), ("Held back: big spoilers", "hold_back"),
                       ("Alternates (overlap a higher pick)", "alternate")):
        group = [r for r in rows if r["plan"] == key]
        if group:
            out += ["", f"## {title}", ""]
            out += [f"- **{r['id']}** E{r['episode']} {r['start']}-{r['end']} ({r['duration_s']:.1f}s): {r['hook']}" for r in group]
    return "\n".join(out) + "\n"


def eval_markdown(ev, summary) -> str:
    w, ref, ab, j = ev["writer_cliffhangers"], ev["reference_cuts"], ev["ablation_cold_viewer_pass"], ev["judge"]
    lines = [f"# Quality report: {summary['show']}", "",
             f"- **Hard rules** (20-60 s, hook in first 3 s, no cut through a spoken line, story order): "
             f"{len(ev['rule_violations'])} violations across {summary['passed']} exported promos."]
    if w["labels"]:
        lines.append(f"- **Writer cliffhangers:** the scripts' own continuity notes flag {w['labels']} episode-ending "
                     f"cliffhangers. The AI editor proposed a promo ending in the last 10 s of {w['hit_last_10s']} of them.")
    if ref["episodes"]:
        lines.append(f"- **Reference cuts** (chosen blind by an independent reviewer, {ref['episodes']} episodes): "
                     f"mean best overlap with the reference cut: AI editor {ref['mean_best_iou_ai_editor']}, rules {ref['mean_best_iou_rules']}, "
                     f"any passing promo {ref['mean_best_iou_any']}; {ref['hits_iou_0_5_any']} of {ref['episodes']} episodes reach 0.5 or more.")
    viewed = {k: v for k, v in ab.items() if v["viewed"]}
    if viewed and summary.get("judge_model") != "none":
        lines.append("- **Ablation, same cold viewer:** " + ", ".join(
            f"{k.replace('_', ' ')} clips {v['passed']}/{v['viewed']} passed" for k, v in viewed.items()) + ".")
    if j["comparisons"]:
        agree = "n/a" if j["repeat_pair_agreement"] is None else f"{j['repeat_pair_agreement']:.0%}"
        lines.append(f"- **Judge consistency:** {j['comparisons']} ranking calls. Pairs seen more than once were ordered "
                     f"the same way {agree} of the time. Average place by slot in the shuffled list (0 = best, 0.5 = no "
                     f"bias): {j['average_place_by_slot']}.")
    lines += ["", "## Why candidates were rejected", ""]
    lines += [f"- {reason}: {count}" for reason, count in ev["rejections"].items()] or ["- none"]
    if w["detail"]:
        lines += ["", "## Writer cliffhanger detail", ""]
        lines += [f"- E{d['episode']}: {'hit' if d['hit'] else 'miss'}"
                  + ("" if d["seconds_before_end"] is None else f" (closest promo ends {d['seconds_before_end']} s before the episode end)")
                  + f". Final beat: {d['final_beat'][:90]}" for d in w["detail"]]
    if ev["rule_violations"]:
        lines += ["", "## Rule violations", ""] + [f"- {v}" for v in ev["rule_violations"]]
    return "\n".join(lines) + "\n"


def write_all(out: Path, summary, notes, ordered, entries, rejected, ranking, raw, episodes, references, evaluate):
    out.mkdir(parents=True, exist_ok=True)
    rows = [promo_row(e, episodes) for e in ordered]
    ev = evaluate(entries, rejected, list(episodes.values()), references, ranking, rows)
    summary = {**summary, "rule_violations": len(ev["rule_violations"])}
    save_json(out / "promos.json", {"summary": summary, "promos": rows})
    save_json(out / "evaluation.json", ev)
    save_json(out / "show_guide.json", {k: v for k, v in notes.items() if k != "_record"})
    save_json(out / "rejected.json", [{k: v for k, v in r.items() if k != "cut"} | (
        {"segments": [s.as_dict() for s in r["cut"].segments]} if "cut" in r else {}) for r in rejected])
    save_json(out / "ranking.json", {k: v for k, v in ranking.items()})
    with (out / "model_calls.jsonl").open("w", encoding="utf-8") as fh:
        for record in raw:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    fields = ["rank", "plan", "id", "episode", "start", "end", "duration_s", "segments", "hook", "cliffhanger", "why",
              "hook_type", "spoiler", "source", "score", "plan_reason"]
    with (out / "promos.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            row = {**r, "segments": "; ".join(f"E{s['episode']} {s['start']}-{s['end']}" for s in r["segments"])}
            writer.writerow({k: safe_cell(v) for k, v in row.items()})
    (out / "posting_plan.md").write_text(plan_markdown(rows, summary), encoding="utf-8")
    (out / "evaluation.md").write_text(eval_markdown(ev, summary), encoding="utf-8")
    (out / "cutlist.edl").write_text(edl(rows, summary["show"]), encoding="utf-8")
    report = {"show": summary["show"], "summary": {"episodes": summary["episodes"], "cues": summary["cues"],
              "model": f"{summary['editor_model']} / judge {summary['judge_model']}", "model_success": summary["passed"]},
              "promos": rows}
    (out / "index.html").write_text(render_report(report), encoding="utf-8")
    save_json(out / "run_summary.json", summary)
