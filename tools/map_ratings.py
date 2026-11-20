"""Apply a person's keep / trim / pass ratings to a newer run: a rated cut counts for the new answer when the new answer
contains the same moment (the same episode and an overlap of at least half, by intersection over union).

    python3 tools/map_ratings.py RATED_RUN RATINGS.csv NEW_RUN [--out applied.csv]

Prints how many rated cuts reappear, what the person said about them, how many of the cuts they KEPT the new answer found,
and whether the new answer's rank order agrees with the ratings on the matched cuts. Nothing is invented: an unmatched cut
is simply not evidence about the new answer.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

TIMES = re.compile(r"Ep\s*(\d+)\D{1,12}?(\d+:\d\d(?:\.\d+)?)\D{1,12}?(\d+:\d\d(?:\.\d+)?)")


def cs(text: str) -> int:
    m, s = text.split(":")
    return round((int(m) * 60 + float(s)) * 100)


def iou(a, b) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union else 0.0


def key(promo: dict) -> tuple:
    return tuple((str(s["episode"]), s["start"], s["end"]) for s in promo["segments"])


def apply(rated_run: Path, ratings: Path, new_run: Path) -> dict:
    old = json.loads((rated_run / "promos.json").read_text(encoding="utf-8"))["promos"]
    new = json.loads((new_run / "promos.json").read_text(encoding="utf-8"))["promos"]
    said = {}
    with open(ratings, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            found = tuple(TIMES.findall(row.get("segments_in_order", "")))
            if found and row.get("decision") in ("keep", "trim", "pass"):
                said[found] = row["decision"]
    matched, unmatched = [], []
    for p in old:
        decision = said.get(tuple((str(s["episode"]), s["start"], s["end"]) for s in p["segments"]))
        if not decision:
            continue
        s0 = p["segments"][0]
        best, hit = 0.0, None
        for q in new:
            for t in q["segments"]:
                if t["episode"] == s0["episode"]:
                    v = iou((s0["start_cs"], s0["end_cs"]), (t["start_cs"], t["end_cs"]))
                    if v > best:
                        best, hit = v, q
        row = {"episode": s0["episode"], "decision": decision, "overlap": round(best, 2)}
        (matched if best >= 0.5 and hit else unmatched).append({**row, "new_rank": hit["rank"] if hit and best >= 0.5 else None,
                                                                "new_id": hit["id"] if hit and best >= 0.5 else None, "new_plan": hit["plan"] if hit and best >= 0.5 else None})
    count = lambda rows, d: sum(r["decision"] == d for r in rows)
    kept_total = count(matched, "keep") + count(unmatched, "keep")
    ranks = {d: [r["new_rank"] for r in matched if r["decision"] == d] for d in ("keep", "trim", "pass")}
    mean = lambda v: round(sum(v) / len(v), 1) if v else None
    return {"rated": len(matched) + len(unmatched), "matched": len(matched), "unmatched": len(unmatched),
            "matched_keep": count(matched, "keep"), "matched_trim": count(matched, "trim"), "matched_pass": count(matched, "pass"),
            "kept_in_total": kept_total, "kept_found": count(matched, "keep"),
            "mean_new_rank": {d: mean(v) for d, v in ranks.items()}, "rows": matched + unmatched}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rated_run", type=Path)
    ap.add_argument("ratings", type=Path)
    ap.add_argument("new_run", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = apply(a.rated_run, a.ratings, a.new_run)
    print({k: v for k, v in r.items() if k != "rows"})
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, ["episode", "decision", "overlap", "new_id", "new_rank", "new_plan"])
            w.writeheader()
            w.writerows({k: row.get(k) for k in w.fieldnames} for row in r["rows"])


if __name__ == "__main__":
    main()
