"""Find, check and rank promos in a folder or ZIP of timestamped screenplays.

    python -m promo SCRIPTS.zip --model gemini --judge gemini:gemini-flash-lite-latest
    python -m promo SCRIPTS.zip --model ollama:qwen3:4b          # offline, slower, weaker
    python -m promo SCRIPTS.zip --model rules                     # no AI at all (baseline)

Every model answer is cached, so a re-run after a crash or a rate limit resumes where it stopped.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

from . import ai, plan
from .cuts import Cut, build, join, overlap
from .evaluate import evaluate
from .export import write_all
from .llm import Model, ModelError, load_dotenv
from .screenplay import Episode, load_episodes, propose


def arguments(argv=None):
    p = argparse.ArgumentParser(prog="python -m promo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path, help="A ZIP, a folder of .txt episodes, or one .txt episode")
    p.add_argument("--model", default="gemini", help="Editor model: provider[:model] or 'rules' (default gemini)")
    p.add_argument("--judge", help="Cold-viewer and ranking model (default: same as --model)")
    p.add_argument("--out", type=Path, help="Output folder (default private/runs/<time>)")
    p.add_argument("--cache", type=Path, default=Path("private/cache"))
    p.add_argument("--references", type=Path, help="Blind reference cuts for THIS show (JSON), for evaluation only")
    p.add_argument("--episodes", help="Only these episodes, e.g. 1-10 or 2,7,33")
    p.add_argument("--rank-top", type=int, default=40, help="How many passing clips enter the ranking tournament")
    p.add_argument("--rounds", type=int, default=4, help="Shuffled ranking rounds")
    p.add_argument("--no-rules-check", action="store_true", help="Skip the rules-vs-AI ablation (saves calls)")
    p.add_argument("--no-joins", action="store_true", help="Skip cross-episode joined promos")
    p.add_argument("--title", help="Show name for the report")
    return p.parse_args(argv)


def pick(episodes: list[Episode], spec: str | None) -> list[Episode]:
    if not spec:
        return episodes
    wanted = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        wanted.update(range(int(a), int(b or a) + 1))
    return [e for e in episodes if e.number in wanted]


def resolve(ep: Episode, ref: str):
    try:
        number, cue_id = ref.strip().upper().lstrip("E").split("-")
        if int(number) != ep.number:
            return None
        return next((c for c in ep.cues if c.id == int(cue_id)), None)
    except ValueError:
        return None


def _say(message: str) -> None:
    print(message, flush=True)


def editor_cuts(model, ep, notes, raw):
    """Ask the editor, let code build (or reject, with a reason) every proposal, and give the
    editor one revision round with the checker's concrete reasons for any proposal that failed."""
    out, failed, feedback = [], [], []
    for attempt in range(2):
        record = ai.editor(model, ep, notes, feedback if attempt else None)
        raw.append(record)
        feedback = []
        for i, p in enumerate(record["answer"]["promos"][:3]):
            pairs = [(resolve(ep, s["first_cue"]), resolve(ep, s["last_cue"])) for s in p["segments"][:3]]
            meta = {k: p[k] for k in ("hook_type", "hook", "open_question", "spoiler", "why")}
            meta["spoiler"] = spoiler_level(meta["spoiler"], ep.number, notes)
            cues = ", ".join(f"{s['first_cue']}..{s['last_cue']}" for s in p["segments"][:3])
            if not pairs or any(a is None or b is None for a, b in pairs):
                why, cut = "cites a cue that is not in this episode", None
            elif len(pairs) == 1:
                cut, why = build(ep, pairs[0][0], pairs[0][1], "editor")
            else:
                cut, why = join([(ep, a, b) for a, b in pairs], "editor")
            if cut is not None:
                if not any(overlap(cut, m["cut"]) > 0.6 for m in out):
                    out.append({"cut": cut, **meta, "revised": bool(attempt)})
            else:
                failed.append({"episode": ep.number, "proposal": i + 1, "attempt": attempt + 1,
                               "why_rejected": "rule: " + why, **meta})
                feedback.append(f"Cues {cues} were rejected: {why}.")
        if not feedback:
            break
    return out, failed


def spoiler_level(said: str, episode: int, notes: dict) -> str:
    """Trust a spoiler label only when the show guide lists a twist the clip could reveal.

    The premise (episodes 1-2) is what every promo sells, so it is never a spoiler.
    Without a guide (local models, rules mode) there is no evidence, so labels are dropped.
    """
    reveals = [r for r in notes.get("reveals", []) if 2 < r["episode"] <= episode]
    if episode <= 2 or not reveals:
        return "none"
    if said == "major" and not any(r["weight"] == "major" for r in reveals):
        return "minor"
    return said


def rules_cuts(ep):
    """The no-AI baseline: lexical hook and cliffhanger signals (kept for the ablation)."""
    out = []
    for w in propose(ep, limit=1):
        cut, _ = build(ep, w.hook, w.closing, "rules")
        if cut:
            out.append({"cut": cut, "hook_type": "shocking_line", "hook": w.hook.text, "spoiler": "none",
                        "open_question": w.closing.text, "why": "Rules: strongest lexical hook and open ending."})
    return out


def main(argv=None, *, key=None, base_url=None, log_fn=None):
    """key, base_url and log_fn are per-call so a shared web server never mixes visitors up."""
    log = log_fn or _say
    args = arguments(argv)
    load_dotenv()
    started = time.monotonic()
    episodes = pick(load_episodes(args.input), args.episodes)
    by_number = {e.number: e for e in episodes}
    last = max(e.number for e in load_episodes(args.input))
    out = args.out or Path("private/runs") / datetime.now().strftime("%Y%m%d-%H%M%S")
    log(f"Read {len(episodes)} episodes, {sum(len(e.cues) for e in episodes)} timed cues.")

    rules_only = args.model == "rules"
    def make(spec):
        same = spec.partition(":")[0] == args.model.partition(":")[0]
        return Model(spec, args.cache, key=key if same else None, base_url=base_url if same else None)

    editor_model = None if rules_only else make(args.model)
    judge = None if rules_only else (make(args.judge) if args.judge else editor_model)
    raw: list[dict] = []

    # 1. guide -------------------------------------------------------------------------------
    if editor_model and not editor_model.local:
        log(f"Reading the whole show once with {editor_model.label} ...")
        notes = ai.guide(editor_model, episodes)
        raw.append(notes.pop("_record"))
    else:
        notes = ai.fallback_guide(episodes)
    names = notes.get("names", {})

    # 2. candidates --------------------------------------------------------------------------
    entries, rejected = [], []
    for ep in episodes:
        mine = []
        if editor_model:
            found, failed = editor_cuts(editor_model, ep, notes, raw)
            mine += found
            rejected += failed
        if rules_only or not args.no_rules_check:
            for r in rules_cuts(ep):  # skip a rules clip that duplicates an editor clip
                if not any(overlap(r["cut"], m["cut"]) > 0.6 for m in mine):
                    mine.append(r)
        entries += mine
        log(f"  episode {ep.number:02d}: {sum(m['cut'].source == 'editor' for m in mine)} editor picks")
    for i, e in enumerate(entries, 1):
        e["id"] = f"P{i:03d}"

    # 3. cold viewer -------------------------------------------------------------------------
    def view(pool):
        kept = []
        for e in pool:
            if judge is None:
                e.update(view=None, passed=True, why_rejected=None)
                kept.append(e)
                continue
            record = ai.viewer(judge, e["cut"], by_number, names)
            raw.append(record)
            ok, why = ai.passes(record["answer"])
            e.update(view=record["answer"], passed=ok, why_rejected=None if ok else why)
            (kept if ok else rejected).append(e)
        return kept

    if judge:
        log(f"Cold viewer ({judge.label}) is watching {len(entries)} clips with no context ...")
    passing = view(entries)

    # 4. joined promos -----------------------------------------------------------------------
    if editor_model and not editor_model.local and not args.no_joins:
        firsts, seen = [], set()
        for e in passing:
            if e["cut"].source == "editor" and len(e["cut"].segments) == 1 and e["cut"].first_episode not in seen:
                seen.add(e["cut"].first_episode)
                firsts.append(e["cut"])
        if len(firsts) >= 2:
            log(f"Looking for stronger promos that join moments across episodes ({len(firsts)} candidates) ...")
            record = ai.joins(editor_model, firsts[:50], by_number, notes)
            raw.append(record)
            new = []
            for j in record["answer"]["joins"][:4]:
                parts = []
                for m in j["moments"][:3]:
                    ep_no = int(m["first_cue"].strip().upper().lstrip("E").split("-")[0]) if "-" in m["first_cue"] else -1
                    ep = by_number.get(ep_no)
                    a, b = (resolve(ep, m["first_cue"]), resolve(ep, m["last_cue"])) if ep else (None, None)
                    parts.append((ep, a, b))
                meta = {"hook_type": "reveal", "hook": j["hook"], "open_question": j["open_question"],
                        "spoiler": j["spoiler"], "why": j["why"]}
                if any(None in part for part in parts):
                    rejected.append({"episode": None, "why_rejected": "join cites an unknown cue", **meta})
                    continue
                cut, why = join(parts, "joined")
                if cut is None:
                    rejected.append({"episode": parts[0][0].number, "why_rejected": "rule: " + why, **meta})
                else:
                    new.append({"cut": cut, "id": f"J{len(new) + 1:02d}", **meta})
            passing += view(new)
            entries += new

    # 5. ranking tournament --------------------------------------------------------------------
    grade = {"stop": 2, "maybe": 1, "scroll_past": 0, "yes": 2, "mostly": 1, "no": 0,
             "unresolved": 2, "softened": 1, "resolved": 0}
    for e in passing:
        v = e.get("view")
        e["pre"] = sum(grade[v[k]] for k in ("first_3s", "makes_sense", "ending")) if v else e["cut"].length
    pool = sorted(passing, key=lambda e: (-e["pre"], e["cut"].first_episode))[: args.rank_top]
    if judge and len(pool) > 1:
        log(f"Ranking {len(pool)} clips in {args.rounds} shuffled rounds ...")
        ranking = ai.rank(judge, [e["cut"] for e in pool], by_number, names, rounds=args.rounds)
        for e, s in zip(pool, ranking["strength"]):
            e["strength"] = s
    else:
        ranking = {"strength": [], "comparisons": 0, "rounds": []}
        for e in pool:
            e["strength"] = max(0.01, e["pre"])
    for e in passing:
        if e not in pool:
            e["strength"] = min((x["strength"] for x in pool), default=1.0) * 0.5
    ordered = plan.order(passing, last)

    # 6. evaluate and export -------------------------------------------------------------------
    usage = [m.usage() for m in {id(m): m for m in (editor_model, judge) if m}.values()]
    summary = {"show": args.title or args.input.stem, "episodes": len(episodes),
               "cues": sum(len(e.cues) for e in episodes), "editor_model": editor_model.label if editor_model else "rules",
               "judge_model": judge.label if judge else "none", "candidates": len(entries), "passed": len(passing),
               "post_first": sum(e["plan"] == "post_first" for e in ordered), "usage": usage,
               "seconds": round(time.monotonic() - started, 1)}
    references = json.loads(args.references.read_text()) if args.references else None
    write_all(out, summary, notes, ordered, entries, rejected, ranking, raw, by_number, references, evaluate)
    log(f"\nDone in {summary['seconds']} s. {len(passing)} promos passed, "
        f"{summary['post_first']} marked post-first.\nOpen {(out / 'index.html').resolve()}")
    return out


if __name__ == "__main__":
    try:
        main()
    except (ModelError, ValueError, OSError) as exc:
        sys.exit(f"Stopped: {exc}\nFinished model answers are cached; run the same command again to resume.")
