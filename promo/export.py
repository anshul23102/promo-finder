"""Write every output an editor or reviewer needs, from one run, unedited."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from . import plan
from .ai import clip_text, fallback_why
from .cuts import HOOK_WINDOW, following
from .coverage import episode_coverage
from .llm import save_json
from .screenplay import stamp

FPS = 30  # assumed timeline rate for the EDL cut list


def safe_cell(value):
    """Stop a spreadsheet from running a model- or script-supplied cell as a formula."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def opening_text(cut, episodes) -> str:
    """What is on screen in the first 3 seconds (a pure visual opening shows its camera shot)."""
    first = cut.segments[0]
    early = [c for c in episodes[first.episode].cues if c.kind != "sound" and first.start <= c.start < first.start + HOOK_WINDOW]
    spoken = [c for c in early if c.kind in ("dialogue", "action")]
    return " / ".join(c.text for c in (spoken or early))


def promo_row(e: dict, episodes) -> dict:
    cut = e["cut"]
    segs = []
    for s in cut.segments:
        segs.append({**s.as_dict(), "start_cs": s.start, "end_cs": s.end})
    last = cut.segments[-1]
    after = following(episodes[last.episode], last)
    hook_ep, hook_id = cut.hook_ref.lstrip("E").split("-")
    end_ep, end_id = (int(part) for part in cut.end_ref.lstrip("E").split("-"))
    closing = next(c for c in episodes[end_ep].cues if c.id == end_id)
    tail = [c.text for c in episodes[last.episode].cues
            if c.kind in ("dialogue", "action") and closing.end <= c.start < last.end and c.end <= last.end]
    closing_evidence = " / ".join([closing.text, *tail])
    view = e.get("view") or {}
    opening = opening_text(cut, episodes)
    summary_of_hook, question, why = e["hook"], e["open_question"], e["why"]
    hook = opening or summary_of_hook                   # the hook is what is actually on screen in the first 3 seconds
    if cut.source in ("rules", "recovery"):  # the no-AI finder only has raw cue text; use what a stranger actually took from the clip
        question = view.get("open_question") or question
        if e.get("why_source") != "model":
            why = f"A cold viewer read it as: {view['situation']}" if view.get("situation") else why
    if e.get("why_source") != "model" and cut.source not in ("rules", "recovery"):
        why = fallback_why(hook, question)              # the old glued-together template is gone
    e = {**e, "hook": hook, "open_question": question, "why": why}
    return {
        "id": e["id"], "rank": e["rank"], "plan": e["plan"], "score": e["score"], "appeal": e["appeal"],
        "episode": cut.first_episode, "episodes": sorted({s.episode for s in cut.segments}),
        "start": segs[0]["start"], "end": segs[-1]["end"], "segments": segs,
        "duration_s": cut.length / 100, "source": cut.source, "hook_type": e["hook_type"],
        "hook": e["hook"], "hook_summary": summary_of_hook, "cliffhanger": e["open_question"], "why": e["why"],
        "why_source": e.get("why_source", "template"), "spoiler": e["spoiler"],
        "plan_reason": plan.reason(e), "hook_cue": [int(hook_ep), int(hook_id)], "end_cue": cut.end_ref,
        "viewer": view, "cut_notes": cut.notes, "next_beat": " / ".join(c.text for c in after),
        "next_beat_time": stamp(after[0].start) if after else None,
        "script": clip_text(cut, episodes, {}),
        # fields the review page already understands
        "opening_3s": opening, "opening_evidence": opening or e["hook"], "closing_evidence": closing_evidence,
        "method": {"editor": "AI editor + cold viewer", "beats": "AI beat scores + code search + cold viewer",
                   "joined": "Joined across episodes", "rules": "Rules baseline", "recovery": "Alternate cut + cold viewer"}[cut.source],
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
            comment = " ".join(r["hook"].split())[:70]
            lines.append(f"* COMMENT: {r['id']} rank {r['rank']} - {comment}")
            event += 1
            record += length
        record += 500
    return "\n".join(lines) + "\n"


def plan_markdown(rows, summary) -> str:
    assessed = "timing-checked candidates for editorial review" if summary["judge_model"] == "none" else "cuts shortlisted by the cold viewer"
    out = [f"# Posting plan: {summary['show']}", "",
           f"{summary['passed']} {assessed} from {summary['candidates']} candidates. "
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
    cov = ev.get("coverage", {})
    lines = [f"# Quality report: {summary['show']}", "",
             f"- **Coverage:** {cov.get('episodes_with_a_promo')} of {cov.get('episodes')} episodes have a shortlisted cut. See coverage.json for every episode’s outcome.",
             f"- **Hard rules** (20-60 s, hook in first 3 s, no cut through a spoken line, story order): "
             f"{len(ev['rule_violations'])} violations across {summary['passed']} exported promos."]
    for warning in summary.get("warnings", []):
        lines.append(f"- **Run note:** {warning}")
    if w["labels"]:
        lines.append(f"- **Writer cliffhangers:** the scripts' own continuity notes flag {w['labels']} episode-ending "
                     f"cliffhangers. The AI editor proposed a promo ending in the last 10 s of {w['hit_last_10s']} of them.")
    if ref["episodes"]:
        lines.append(f"- **Reference cuts** (chosen blind by an independent reviewer, {ref['episodes']} episodes): "
                     f"mean best overlap with the reference cut: AI finder before any judge {ref.get('mean_best_iou_ai_before_judge')}, "
                     f"AI picks that passed the viewer {ref['mean_best_iou_ai_editor']}, rules {ref['mean_best_iou_rules']}, "
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
    if j.get("note"):
        lines.append(f"- **Ranking:** {j['note']}")
    for h in ev.get("reviews") or ([ev["human_review"]] if ev.get("human_review") else []):
        if not h["all"]["n"]:
            continue
        a, pf = h["all"], h["post_first"]
        label = "Human review"
        queue = ", ".join(f"{d} {r}" for d, r in h.get("mean_queue_rank", {}).items())
        lines.append(f"- **{label}** ({h['reviewer']}): {a['n']} promos judged; kept or trimmed {a['keep_or_trim_rate']:.0%} "
                     f"(keep {a['keep']}, trim {a['trim']}, pass {a['pass']}). Post-first picks: {('%.0f%%' % (100 * pf['keep_or_trim_rate'])) if pf['n'] else 'n/a'} "
                     f"of {pf['n']}. By finder: " + ", ".join(f"{k} {v['keep_or_trim_rate']:.0%} of {v['n']}" for k, v in h["by_finder"].items() if v["n"])
                     + f". Average place in the tool's queue by decision: {queue}.")
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


def write_all(out: Path, summary, notes, ordered, entries, rejected, ranking, raw, episodes, references, evaluate, all_episodes=None):
    out.mkdir(parents=True, exist_ok=True)
    rows = [promo_row(e, episodes) for e in ordered]
    ev = evaluate(entries, rejected, list(episodes.values()), references, ranking, rows, all_episodes)
    from .evaluate import human_review
    ev["reviews"] = [r for r in (human_review(x["path"], rows, x["name"], x["kind"]) for x in summary.get("reviews", [])) if r]
    ev["human_review"] = next((r for r in ev["reviews"] if r["kind"] == "human"), ev["reviews"][0] if ev["reviews"] else None)
    summary = {**summary, "rule_violations": len(ev["rule_violations"])}
    coverage = episode_coverage(episodes, rows, rejected, judged=summary["judge_model"] != "none")
    save_json(out / "coverage.json", coverage)
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
    save_json(out / "run_summary.json", summary)
