"""Finder v4: score beats, let code search.

The brief defines a promo by three properties that live in different places:
the HOOK lives in the first 3 seconds, the CLIFFHANGER lives in the last beat,
and "makes sense on its own" belongs to the whole clip. So one model call per
episode scores every line for the first two, and code searches every legal
opening x ending pair (20-60 s, shot boundaries, no split lines). The cold
viewer still judges the whole clip. The model never does clock arithmetic.
"""
from __future__ import annotations

from .cuts import Cut, build, overlap
from .llm import INTEGER, Model, array, obj, string
from .screenplay import Episode, render

BEATS_SYSTEM = """You score lines of ONE episode of a vertical microdrama for promo editing. A promo is a 20-60 second clip
posted on TikTok/Reels/Shorts to people who have never seen the show. Score EVERY cue below (dialogue, action and
camera; skip only SOUND), one entry per cue ID, in order:
- hook (0-3): if the clip STARTED on this cue, would a stranger stop scrolling within 3 seconds? 3 = a concrete shock
  understandable with no context (a slap, shove, grab, reveal, threat, cruel or shocking line). 2 = clearly tense.
  0-1 = quiet, scenery, a reply, or a line that needs earlier context.
- cliff (0-3): if the clip ENDED right after this cue, how sharp is the question left open? 3 = a specific unanswered
  question with stakes (will he answer? is she caught? who is at the door?) that this cue does NOT answer. 0-1 = calm,
  resolved, or answered.
- question: for cliff 2-3, the exact question left open; for hook 2-3, the hook in a few words; otherwise "".
Score honestly: in most episodes only a handful of cues deserve a 3."""

BEATS_SCHEMA = obj(beats=array(obj(cue=string(), hook=INTEGER, cliff=INTEGER, question=string())))


def score_beats(model: Model, ep: Episode, names: dict) -> dict:
    user = f"EPISODE {ep.number} (cue ID, start-end, who/what, text)\n" + render(ep, names=names)
    return model.ask(f"beats-e{ep.number:02d}-all", BEATS_SYSTEM, user, BEATS_SCHEMA, max_tokens=8000)


def spoiler_from_guide(episode: int, notes: dict) -> str:
    """A clip from the episode where the guide places a big twist may show it. The first tenth of a show (at least
    3 episodes) is the premise that every promo sells, so it never counts as a spoiler."""
    premise = max(3, round(len(notes.get("episodes", [])) * 0.1))
    weights = [r["weight"] for r in notes.get("reveals", []) if r["episode"] == episode and episode > premise]
    return "major" if "major" in weights else ("minor" if weights else "none")


def search(ep: Episode, beats: list[dict], per_episode: int = 3, notes: dict | None = None) -> tuple[list[dict], dict]:
    """Pair scored hooks and endings, preferring cuts that preserve their closing beat."""
    by_id = {f"E{ep.number:02d}-{c.id:03d}": c for c in ep.cues}
    scored = []
    for b in beats:
        cue = by_id.get(b["cue"].strip().upper())
        if cue is not None and cue.kind != "sound":
            scored.append((cue, max(0, min(3, b["hook"])), max(0, min(3, b["cliff"])), b["question"] or cue.text))

    def best(index):  # the strong ones, or this episode's best few if it has no 2-3 at all
        strong = [s for s in scored if s[index] >= 2]
        return strong if len(strong) >= 3 else sorted((s for s in scored if s[index] >= 1), key=lambda s: -s[index])[:6] or strong

    hooks, cliffs = best(1), best(2)
    options, tried = [], 0
    for h, hs, _, hq in hooks:
        for c, _, cs, cq in cliffs:
            if c.end <= h.start:
                continue
            tried += 1
            cut, _ = build(ep, h, c, "beats", preserve_ending=True)
            if cut is None:
                cut, _ = build(ep, h, c, "beats")
            if cut is None:
                continue
            length = cut.length / 100
            # Prefer the strongest pair; among equals, a punchier clip (closest to 40 s) wins.
            score = hs + cs - abs(length - 40) / 100
            options.append((score, cut, hs, cs, hq, cq))
    options.sort(key=lambda o: -o[0])
    picked = []
    for score, cut, hs, cs, hq, cq in options:
        if any(overlap(cut, p["cut"]) > 0.3 for p in picked):
            continue
        hook_type = "shocking_line" if by_id[cut.hook_ref].kind == "dialogue" else "physical"
        picked.append({"cut": cut, "hook_type": hook_type, "hook": hq or by_id[cut.hook_ref].text, "open_question": cq,
                       "spoiler": spoiler_from_guide(ep.number, notes or {}), "why": f"Opens on {hq.rstrip('.')} and cuts while asking: {cq}",
                       "beat_scores": [hs, cs]})
        if len(picked) == per_episode:
            break
    return picked, {"beats": len(scored), "hooks": len(hooks), "cliffs": len(cliffs), "pairs_tried": tried, "legal": len(options)}
