"""Turn ranked promos into a posting order an editor can act on.

The ranking says which clips a cold viewer prefers. Posting order adds two
business rules that a viewer judge cannot see:
- earlier episodes first (weight 1.0 at episode 1 down to 0.45 at the last): a new viewer who taps through lands on episode 1,
  so a promo from episode 3 pays off in minutes, one from episode 45 in hours,
- hold back big spoilers, vary the hook type, post at most one promo per episode first, and prefer a continuous
  stretch to a stitched one.
"""
from __future__ import annotations

from .cuts import overlap

SPOILER = {"none": 1.0, "minor": 0.9, "major": 0.6}


def funnel(episode: int, last: int) -> float:
    return 1.0 - 0.55 * (episode - 1) / max(1, last - 1)


CLARITY = {"yes": 1.0, "mostly": 0.85, "no": 0.5}


def order(entries: list[dict], last_episode: int, post_first: int = 10) -> list[dict]:
    """entries carry 'cut', 'strength', 'spoiler', 'hook_type'; adds rank, score and plan fields."""
    if not entries:
        return []
    top = max(e["strength"] for e in entries)
    for e in entries:
        e["appeal"] = round(e["strength"] / top, 4)
        clarity = CLARITY.get((e.get("view") or {}).get("makes_sense", "yes"), 1.0)
        continuous = 1.0 if len(e["cut"].segments) == 1 else 0.9  # the brief: "usually one continuous stretch"
        e["score"] = round(e["appeal"] * funnel(e["cut"].first_episode, last_episode) * SPOILER[e["spoiler"]]
                           * clarity * continuous, 4)
    remaining = sorted(entries, key=lambda e: (-e["score"], e["cut"].first_episode))
    plan, previous_type = [], None
    while remaining:
        best = remaining[0]
        if len(plan) < post_first:
            # Prefer a different hook type from the last post when it costs under 10% of score.
            for e in remaining[1:]:
                if e["score"] < best["score"] * 0.9:
                    break
                if best["hook_type"] == previous_type and e["hook_type"] != previous_type:
                    best = e
                    break
        remaining.remove(best)
        best["duplicate_of"] = next((p["id"] for p in plan if overlap(p["cut"], best["cut"]) > 0.3), None)
        held = best["spoiler"] == "major"
        if best["duplicate_of"]:
            best["plan"] = "alternate"
        elif held:
            best["plan"] = "hold_back"
        elif sum(p["plan"] == "post_first" for p in plan) < post_first and not any(
                p["plan"] == "post_first" and p["cut"].first_episode == best["cut"].first_episode for p in plan):
            best["plan"] = "post_first"
            previous_type = best["hook_type"]
        else:
            best["plan"] = "library"
        plan.append(best)
    group = {"post_first": 0, "library": 1, "hold_back": 2, "alternate": 3}
    plan.sort(key=lambda e: (group[e["plan"]], -e["score"]))
    for rank, e in enumerate(plan, 1):
        e["rank"] = rank
    return plan


def reason(e: dict) -> str:
    bits = [f"cold-viewer appeal {e['appeal']:.2f}"]
    if e["cut"].first_episode <= 5:
        bits.append(f"opens in episode {e['cut'].first_episode}, so a new viewer reaches the payoff fast")
    if (e.get("view") or {}).get("makes_sense") == "mostly":
        bits.append("a stranger only mostly followed it")
    if len(e["cut"].segments) > 1:
        bits.append(f"joins {len(e['cut'].segments)} moments")
    if e["spoiler"] != "none":
        bits.append(f"{e['spoiler']} spoiler")
    if e.get("duplicate_of"):
        bits.append(f"overlaps {e['duplicate_of']}")
    return "; ".join(bits)
