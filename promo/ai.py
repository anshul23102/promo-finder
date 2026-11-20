"""The four AI stages. Each one asks a narrow question and gets typed JSON back.

1. guide   - one read of the whole show: who is who, one line per episode, big reveals
2. editor  - per episode: propose promo moments by cue ID (never by timestamp)
3. viewer  - a cold viewer who sees ONLY the clip: what did you understand?
4. ranking - shuffled groups of clips ranked by a scrolling viewer, fused with Bradley-Terry
"""
from __future__ import annotations

from collections import defaultdict
import math
import random

from .cuts import Cut, cues_in
from .llm import INTEGER, Model, array, obj, string
from .screenplay import Episode, render

HOOK_TYPES = ("physical", "reveal", "shocking_line", "threat", "visual_shock", "question")

# ---------------------------------------------------------------- 1. guide
GUIDE_SYSTEM = """You are a story editor preparing a series bible for a promo team.
You will read every episode of a vertical microdrama. Return:
- characters: every recurring character. "aliases" must list EVERY speaker label used for them in the scripts, copied exactly as written in capitals (for example a character first credited as "WOMAN IN RED" and later by name).
- episodes: one plain sentence per episode saying what happens.
- reveals: the twists a promo could spoil (identity reveals, betrayals exposed, deaths, rescues). "major" means knowing it early would spoil the show's main arc.
Only use what is in the scripts."""

GUIDE_SCHEMA = obj(
    characters=array(obj(name=string(), aliases=array(string()), role=string())),
    episodes=array(obj(episode=INTEGER, summary=string())),
    reveals=array(obj(episode=INTEGER, reveal=string(), weight=string("major", "minor"))),
)


def guide(model: Model, episodes: list[Episode]) -> dict:
    text = "\n\n".join(f"=== EPISODE {e.number} ===\n{render(e, ids=False, camera=False)}" for e in episodes)
    record = model.ask("guide", GUIDE_SYSTEM, text, GUIDE_SCHEMA, max_tokens=12000)
    answer = record["answer"]
    labels = {c.speaker.casefold() for e in episodes for c in e.cues if c.kind == "dialogue"}
    names = {}
    for person in answer["characters"]:
        for alias in person["aliases"] + [person["name"]]:
            if alias.casefold() in labels:  # keep only aliases that really occur
                names[alias.casefold()] = person["name"].upper()
    return {**answer, "names": names, "_record": record}


def fallback_guide(episodes: list[Episode]) -> dict:
    """No-model guide: loglines only. Used with small local models or rules mode."""
    return {"characters": [], "episodes": [{"episode": e.number, "summary": e.logline} for e in episodes],
            "reveals": [], "names": {}}


# ---------------------------------------------------------------- 2. editor
EDITOR_SYSTEM = """You are the promo editor at a microdrama app. You pick moments from ONE episode to cut into
20-60 second promos for TikTok, Instagram Reels and YouTube Shorts aimed at people who have never seen the show.
A good promo:
1. OPENS ON A HOOK: the very first cue is something that stops a scrolling thumb within 3 seconds - a slap, a shove,
   a reveal, a shocking or cruel line, a threat. Never open on scenery, a reply, or a line that needs earlier context.
2. ENDS ON A CLIFFHANGER: the last cue leaves a specific question open (will he answer? what is in the letter? who is at
   the door?). Cut BEFORE the answer. Never end on a hug, a thank-you, an explanation or a resolved conflict.
3. MAKES SENSE ON ITS OWN: a stranger can tell who is against whom and what is at stake from inside the clip.
Every episode of a microdrama is built to end on a cliffhanger, so check the episode's final beat first: it is often
the strongest ending, if a clip can lead up to it from a hook within 20-60 seconds.
Choose by cue ID only. PREFER one continuous stretch ("segments" with one item). Give 2-3 segments only when no single
20-60 second stretch works, in order, each at least 5 seconds long and easy for a stranger to follow across the cut. The total must be 20-60 seconds;
check it with the timestamps. Propose up to 3 promos, best first, and propose none if nothing in the episode works.
spoiler: "major" if the clip gives away a big twist listed in the show notes.
Write hook and open_question as a viewer would describe them, in under 20 words each."""

EDITOR_SCHEMA = obj(promos=array(obj(
    segments=array(obj(first_cue=string(), last_cue=string())),
    hook_type=string(*HOOK_TYPES),
    hook=string(),
    open_question=string(),
    spoiler=string("none", "minor", "major"),
    why=string(),
)))


def editor(model: Model, ep: Episode, notes: dict, feedback: list[str] | None = None) -> dict:
    cast = "\n".join(f"- {c['name']}: {c['role']}" for c in notes.get("characters", []))
    before = [x["summary"] for x in notes.get("episodes", []) if x["episode"] == ep.number - 1]
    reveals = [f"ep {r['episode']}: {r['reveal']} ({r['weight']})" for r in notes.get("reveals", [])]
    user = (f"SHOW NOTES\nCast:\n{cast or '(not available)'}\nPreviously: {before[0] if before else '(first episode)'}\n"
            f"Twists to protect:\n" + ("\n".join(reveals) or "(not available)") +
            f"\n\nEPISODE {ep.number} SCRIPT (cue ID, start-end, who/what, text)\n" + render(ep, names=notes.get("names")))
    if feedback:
        user += ("\n\nREVISION: a checker rejected some of your earlier proposals:\n" + "\n".join(f"- {f}" for f in feedback)
                 + "\nPropose replacements that fix this. Check the clock: each promo must total 20-60 seconds.")
    return model.ask(f"editor-e{ep.number:02d}{'-rev' if feedback else ''}", EDITOR_SYSTEM, user, EDITOR_SCHEMA, max_tokens=3000)


# ---------------------------------------------------------------- 3. cold viewer
VIEWER_SYSTEM = """You are scrolling TikTok and have NEVER seen this show. Below is the complete text of one short clip:
every camera shot, action and spoken line, with seconds from the start of the clip. You know nothing else.
Answer from the clip alone. A speaker saying "I" or "my" refers to that speaker. Track who did or said each important thing before summarizing. Use speaker labels where identity is uncertain. Avoid guessing relationships from a glance, proximity or a name.
Separate deliberate suspense from missing context. If a stranger knows who wants what and why it matters, an unexplained event can still be clear. Only assess comprehension of the events inside the cut.
Be a tough viewer. Most clips do NOT stop your thumb: you scroll past anything that opens on a quiet look, a name you do not
know, a line that needs earlier context, or talk without a concrete shock. Say "stop" only if the first 3 seconds contain a
specific physical act, reveal, threat or cruel line you can understand with no context; otherwise "maybe" or "scroll_past".
Say "resolved" if the last lines answer the question the clip raised, even partly or with a reaction.
- who / situation: who these people are to each other and what is going on, as you understood it.
- open_question: the question you are left with at the last second, or "none" if nothing is left open.
- first_3s: would the first 3 seconds make you stop scrolling? (stop / maybe / scroll_past)
- makes_sense: could you follow it? (yes / mostly / no)
- ending: is the question at the end still open (unresolved), half-answered (softened) or answered (resolved)?
- confusing: the one thing that confused you, or "nothing"."""

VIEWER_SCHEMA = obj(
    who=string(), situation=string(), open_question=string(),
    first_3s=string("stop", "maybe", "scroll_past"),
    makes_sense=string("yes", "mostly", "no"),
    ending=string("unresolved", "softened", "resolved"),
    confusing=string(),
)


def clip_text(cut: Cut, episodes: dict[int, Episode], names: dict) -> str:
    """What a viewer would get: the clip only, clip-relative seconds, consistent names, no IDs."""
    parts, offset = [], 0
    for i, seg in enumerate(cut.segments):
        ep = episodes[seg.episode]
        if i:
            parts.append("--- CUT TO ---")
        lines = render(ep, cues_in(ep, seg), ids=False, names=names, origin=seg.start - offset).splitlines()
        parts.extend(lines)
        offset += seg.length
    return "\n".join(parts)


SKEPTIC_SYSTEM = VIEWER_SYSTEM + """

You are the SECOND reader. The first reader was easily impressed and a model from the same family wrote the clip's score, so
be the bored, skeptical scroller who has seen thousands of these. Say "stop" only for a concrete shock you could understand
with no context. Say "softened" or "resolved" if the clip gives any answer, reaction or comfort at the end. If you needed
anything explained, answer "mostly" or "no". When unsure between two answers, pick the weaker one."""


def viewer(model: Model, cut: Cut, episodes, skeptic: bool = False) -> dict:
    # Full-show aliases can reveal information that was hidden inside this clip.
    return model.ask("viewer-skeptic" if skeptic else "viewer", SKEPTIC_SYSTEM if skeptic else VIEWER_SYSTEM,
                     clip_text(cut, episodes, {}), VIEWER_SCHEMA, max_tokens=800)


def passes(view: dict) -> tuple[bool, str]:
    if view["first_3s"] == "scroll_past":
        return False, "weak first 3 seconds"
    if view["makes_sense"] == "no":
        return False, "a stranger could not follow it"
    if view["ending"] == "resolved" or view["open_question"].strip().casefold().rstrip(".") in ("none", "nothing", ""):
        return False, "the ending answers its own question"
    return True, "passed"


WHY_SYSTEM = """You are a short-form video editor. In ONE sentence you tell a colleague why this clip is worth posting.
You get the first 3 seconds, the whole clip, and what a stranger understood from it. Write at most 30 words in plain words:
what in the first 3 seconds would stop a scrolling stranger, and what they are left needing to know at the end.
Describe the clip's events and the open question. Use only what the clip shows. Never mention viewers, the audience, a hook,
a cliffhanger, scores or rules."""
WHY_SCHEMA = obj(why=string())


def explain(model: Model, cut: Cut, episodes, opening: str, view: dict | None) -> dict:
    """One sentence on why the clip works, written from the clip itself (not a template)."""
    view = view or {}
    user = (f"FIRST 3 SECONDS:\n{opening}\n\nWHAT A STRANGER UNDERSTOOD: {view.get('situation', 'not recorded')}\n"
            f"LEFT WONDERING: {view.get('open_question', 'not recorded')}\n\nCLIP:\n{clip_text(cut, episodes, {})}")
    return model.ask("why", WHY_SYSTEM, user, WHY_SCHEMA, max_tokens=900)


def usable_why(text: str) -> str | None:
    """The sentence if it is a real one-liner, else None (the caller then uses the plain fallback)."""
    text = " ".join(str(text or "").split())
    return text if 4 <= len(text.split()) <= 45 else None


def fallback_why(opening: str, question: str) -> str:
    """No model needed: quote what opens the clip and what is still open at the end."""
    first = " ".join(str(opening or "").split()).split(" / ")[0].strip(' "')
    first = first if len(first) <= 90 else first[:89].rsplit(" ", 1)[0] + "..."
    ask = " ".join(str(question or "").split()).rstrip(".")
    ask += "" if ask.endswith(("?", "!")) else "."
    return f'Opens on "{first}" and cuts with this still open: {ask}' if first and ask else (f'Opens on "{first}".' if first else "No summary was written for this cut.")


# ---------------------------------------------------------------- 4. ranking
RANK_SYSTEM = """You are a TikTok viewer in the US who has never seen this show. Below are several short clips
(full text of each). Rank them by which one you would be most likely to stop for in the first 3 seconds AND then
tap through to watch the next episode. Judge only what is in each clip. Clip length is not a factor.
Return every clip letter exactly once, best first, and one short reason for your top pick."""


def rank(model: Model, cuts: list[Cut], episodes, rounds: int = 4, group: int = 5, seed: int = 11, *, raw: list[dict] | None = None) -> dict:
    """Shuffled listwise rounds -> pairwise wins -> Bradley-Terry strengths."""
    n = len(cuts)
    if n < 2:
        return {"strength": [1.0] * n, "comparisons": 0, "rounds": [], "position_bias": None, "agreement": None}
    rng = random.Random(seed)
    wins = defaultdict(float)
    seen_pairs = defaultdict(list)
    slot_ranks = defaultdict(list)
    log = []
    texts = [clip_text(c, episodes, {}) for c in cuts]
    for r in range(rounds):
        order = list(range(n))
        rng.shuffle(order)
        groups = [order[i:i + group] for i in range(0, n, group)]
        if len(groups) > 1 and len(groups[-1]) < 2:
            groups[-2].extend(groups.pop())
        for members in groups:
            if len(members) < 2:
                continue
            letters = [chr(65 + i) for i in range(len(members))]
            user = "\n\n".join(f"CLIP {letter}\n{texts[m]}" for letter, m in zip(letters, members))
            schema = obj(order=array(string(*letters)), reason=string())
            record = model.ask(f"rank-r{r}", RANK_SYSTEM, user, schema, max_tokens=600)
            if raw is not None:
                raw.append(record)
            got = record["answer"]["order"]
            if len(got) != len(letters) or set(got) != set(letters):
                log.append({"round": r, "members": [cuts[m].key for m in members],
                            "order": got, "model": record["model"], "excluded": "incomplete ballot"})
                continue
            ranked = [members[letters.index(x)] for x in got]
            for place, m in enumerate(ranked):
                slot_ranks[members.index(m)].append(place / (len(members) - 1))
            for i, a in enumerate(ranked):
                for b in ranked[i + 1:]:
                    wins[(a, b)] += 1
                    seen_pairs[frozenset((a, b))].append(a)
            log.append({"round": r, "members": [cuts[m].key for m in members], "order": got,
                        "reason": record["answer"]["reason"], "model": record["model"]})
    strength = bradley_terry(n, wins)
    repeated = [v for v in seen_pairs.values() if len(v) > 1]
    agreement = (sum(max(v.count(x) for x in set(v)) / len(v) for v in repeated) / len(repeated)) if repeated else None
    bias = {slot: round(sum(v) / len(v), 3) for slot, v in sorted(slot_ranks.items())}
    return {"strength": strength, "comparisons": sum("excluded" not in ballot for ballot in log), "rounds": log,
            "position_bias": bias, "agreement": agreement}


def bradley_terry(n: int, wins: dict, iterations: int = 200, prior: float = 0.5) -> list[float]:
    """Minorization-maximization fit; a small prior keeps unbeaten clips finite."""
    p = [1.0] * n
    total = defaultdict(float)
    for (a, b), w in wins.items():
        total[a] += w
    games = defaultdict(float)
    for (a, b), w in wins.items():
        games[(a, b)] += w
        games[(b, a)] += w
    for _ in range(iterations):
        new = []
        for i in range(n):
            denom = sum(g / (p[i] + p[j]) for (x, j), g in games.items() if x == i) + 2 * prior / (p[i] + 1.0)
            new.append((total[i] + prior) / denom if denom else p[i])
        scale = math.exp(sum(math.log(v) for v in new) / n)
        p = [v / scale for v in new]
    return p


# ---------------------------------------------------------------- cross-episode joins
JOIN_SYSTEM = """You are the promo editor. Below are promo candidates from different episodes of one show, each with its
cue IDs. Propose up to 4 promos that JOIN two moments in story order, where the join is stronger than either clip
alone: e.g. a shocking opening moment from one clip, then the cliffhanger ending from a later clip that pays it off
or raises the stakes. Each moment is first_cue..last_cue taken from inside one candidate. The total must be 20-60
seconds; the first moment must open on a hook. Only propose a join a stranger could follow. Propose none if no join
is better than the originals."""

JOIN_SCHEMA = obj(joins=array(obj(
    moments=array(obj(first_cue=string(), last_cue=string())),
    hook=string(), open_question=string(), why=string(),
    spoiler=string("none", "minor", "major"))))


def joins(model: Model, shortlist: list[Cut], episodes, notes) -> dict:
    blocks = []
    for i, cut in enumerate(shortlist, 1):
        seg = cut.segments[0]
        ep = episodes[seg.episode]
        blocks.append(f"CANDIDATE {i} (episode {seg.episode}, {seg.length / 100:.1f}s)\n"
                      + render(ep, cues_in(ep, seg), names=notes.get("names"), camera=False))
    cast = "\n".join(f"- {c['name']}: {c['role']}" for c in notes.get("characters", []))
    return model.ask("joins", JOIN_SYSTEM, f"Cast:\n{cast}\n\n" + "\n\n".join(blocks), JOIN_SCHEMA, max_tokens=3000)
