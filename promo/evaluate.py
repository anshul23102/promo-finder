"""How we know the output is good, and where it is not.

Everything here is code: no model grades its own homework.
1. hard rules     - every exported promo is re-checked against the source clock
2. writer labels  - 14 continuity notes name the previous episode's cliffhanger;
                    does the editor propose a promo ending on it?
3. reference cuts - five episode intervals chosen blind by an independent reviewer
4. ablation       - same cold viewer, rules-found clips vs AI-editor clips
5. judge health   - order agreement across shuffled rounds and position bias
"""
from __future__ import annotations

from collections import Counter
import re

from .cuts import HOOK_WINDOW, MAX_LEN, MIN_LEN, MIN_SEGMENT, Segment, opens_mid_sentence, overlap
from .screenplay import Episode, clean_edges, stamp

def writer_cliffhangers(episodes: list[Episode]) -> list[dict]:
    """Episodes whose NEXT episode's continuity note says "Episode N's cliffhanger/climax".

    The writers place that moment at the end of episode N (checked by hand on all
    14 notes in the pack), so the label is the episode's final story beat.
    """
    by_number = {e.number: e for e in episodes}
    labels = []
    for ep in episodes:
        found = re.search(r"Episode (\d+)(?:'s)? (?:cliffhanger|climax)", ep.continuity, re.I)
        if not found or int(found[1]) not in by_number:
            continue
        prev = by_number[int(found[1])]
        beats = [c for c in prev.cues if c.kind in ("dialogue", "action")]
        if beats:
            labels.append({"episode": prev.number, "note": ep.continuity, "time": prev.duration,
                           "final_beat": beats[-1].text})
    return labels


def check_rules(promos: list[dict], episodes: dict[int, Episode]) -> list[str]:
    """Return every violation; an empty list means all promos obey the brief."""
    problems = []
    for p in promos:
        segs = [Segment(s["episode"], s["start_cs"], s["end_cs"]) for s in p["segments"]]
        total = sum(s.length for s in segs)
        if not MIN_LEN <= total <= MAX_LEN:
            problems.append(f"{p['id']}: length {total / 100}s")
        for i, s in enumerate(segs):
            ep = episodes.get(s.episode)
            if ep is None or not 0 <= s.start < s.end <= ep.duration:
                problems.append(f"{p['id']}: segment {i + 1} out of bounds")
                continue
            if len(segs) > 1 and s.length < MIN_SEGMENT:
                problems.append(f"{p['id']}: segment {i + 1} shorter than 5 s")
            if opens_mid_sentence(ep, s.start):
                problems.append(f"{p['id']}: segment {i + 1} opens on a dangling line")
            edges = clean_edges(ep)
            if s.start not in edges or s.end not in edges:
                problems.append(f"{p['id']}: segment {i + 1} cuts through a spoken line")
        if [(s.episode, s.start) for s in segs] != sorted((s.episode, s.start) for s in segs):
            problems.append(f"{p['id']}: segments out of story order")
        hook_ep, hook_id = p["hook_cue"]
        hook = next((c for c in episodes[hook_ep].cues if c.id == hook_id), None)
        if hook is None or not segs[0].start <= hook.start <= segs[0].start + HOOK_WINDOW:
            problems.append(f"{p['id']}: hook does not land in the first 3 seconds")
    return problems


def evaluate(entries: list[dict], rejected: list[dict], episodes: list[Episode], references: dict | None,
             ranking: dict, promos: list[dict]) -> dict:
    by_number = {e.number: e for e in episodes}
    editor_cuts = [e for e in entries if e["cut"].source == "editor"]

    labels = writer_cliffhangers(episodes)
    hits = []
    for label in labels:
        ends = [e["cut"].segments[-1].end for e in editor_cuts if e["cut"].segments[-1].episode == label["episode"]]
        near = min((label["time"] - t for t in ends), default=None)
        hits.append({**label, "time": stamp(label["time"]), "seconds_before_end": None if near is None else near / 100,
                     "hit": near is not None and near <= 1000})

    refs = []
    ran = {e.number for e in episodes}
    for item in (references or {}).get("episodes", []):
        if not item.get("eligible_for_blind_comparison") or item["episode"] not in ran:
            continue
        ref = item["intervals"][0]
        from .cuts import Cut
        ref_cut = Cut([Segment(item["episode"], round(ref["start_s"] * 100), round(ref["end_s"] * 100))], "", "", "reference")

        def best(source):
            mine = [e for e in entries if e["cut"].first_episode == item["episode"] and (source is None or e["cut"].source == source)
                    and e.get("passed", True)]
            return round(max((overlap(e["cut"], ref_cut) for e in mine), default=0.0), 3)

        refs.append({"episode": item["episode"], "reference": [ref["start_time"], ref["end_time"]],
                     "best_iou_ai_editor": best("editor"), "best_iou_rules": best("rules"), "best_iou_any": best(None)})

    def mean(key):
        return round(sum(r[key] for r in refs) / len(refs), 3) if refs else None

    def rate(source):
        pool = [e for e in entries if e["cut"].source == source and e.get("view")]
        ok = [e for e in pool if e["passed"]]
        return {"viewed": len(pool), "passed": len(ok), "pass_rate": round(len(ok) / len(pool), 3) if pool else None}

    reasons = Counter((e["why_rejected"] or "").split(" (")[0] for e in rejected)
    return {
        "rule_violations": check_rules(promos, by_number),
        "writer_cliffhangers": {"labels": len(hits), "hit_last_10s": sum(h["hit"] for h in hits), "detail": hits},
        "reference_cuts": {"episodes": len(refs), "mean_best_iou_ai_editor": mean("best_iou_ai_editor"),
                           "mean_best_iou_rules": mean("best_iou_rules"), "mean_best_iou_any": mean("best_iou_any"),
                           "hits_iou_0_5_any": sum(r["best_iou_any"] >= 0.5 for r in refs), "detail": refs},
        "ablation_cold_viewer_pass": {"ai_editor": rate("editor"), "rules": rate("rules"), "joined": rate("joined")},
        "rejections": dict(reasons.most_common()),
        "judge": {"comparisons": ranking.get("comparisons"), "repeat_pair_agreement": ranking.get("agreement"),
                  "average_place_by_slot": ranking.get("position_bias")},
    }
