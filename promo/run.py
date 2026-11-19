"""Find, check and rank promos in a folder or ZIP of timestamped screenplays.

    python -m promo SCRIPTS.zip                                   # no AI, nothing leaves this computer (the default)
    python -m promo SCRIPTS.zip --model gemini --judge gemini:gemini-flash-lite-latest
    python -m promo SCRIPTS.zip --model ollama:qwen3:4b          # offline, slower, weaker
    python -m promo SCRIPTS.zip --model rules                     # no AI at all (baseline)

Every model answer is cached, so a re-run after a crash or a rate limit resumes where it stopped.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

from . import ai, beats, plan
from .evaluate import AI_SOURCES
from .cuts import Cut, build, join, overlap
from .evaluate import evaluate
from .export import opening_text, write_all
from .llm import Model, ModelError, load_dotenv
from .screenplay import Episode, load_episodes, propose


def arguments(argv=None):
    p = argparse.ArgumentParser(prog="python -m promo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path, help="A ZIP, a folder of .txt episodes, or one .txt episode")
    p.add_argument("--model", default="rules", help="Editor model: provider[:model] or 'rules' (default: rules, no AI, nothing leaves this computer)")
    p.add_argument("--judge", help="Cold-viewer and ranking model (default: same as --model)")
    p.add_argument("--out", type=Path, help="Output folder (default private/runs/<time>)")
    p.add_argument("--cache", type=Path, default=Path("private/cache"))
    p.add_argument("--references", type=Path, help="Blind reference cuts for THIS show (JSON), for evaluation only")
    p.add_argument("--episodes", help="Only these episodes, e.g. 1-10 or 2,7,33")
    p.add_argument("--rank-top", type=int, default=40, help="How many passing clips enter the ranking tournament")
    p.add_argument("--rounds", type=int, default=4, help="Shuffled ranking rounds")
    p.add_argument("--no-rules-check", action="store_true", help="Skip the rules-vs-AI ablation (saves calls)")
    p.add_argument("--finder", choices=["beats", "editor"], default="beats",
                   help="beats (default): score every line as an opening/ending and let code search all legal pairs; "
                        "editor: the model proposes whole promos (v3)")
    p.add_argument("--recover", action=argparse.BooleanOptionalAction, default=True,
                   help="Try unseen alternate cuts for uncovered episodes (default on)")
    p.add_argument("--why", action=argparse.BooleanOptionalAction, default=True,
                   help="Ask the judge model for a one-sentence reason per shortlisted clip (default on; off = quote the clip instead)")
    p.add_argument("--why-model", help="A different model to write the one-line reasons (default: the judge model)")
    p.add_argument("--no-guide", action="store_true", help="Skip the whole-show read (needed when the provider caps a request below ~50k tokens, e.g. Groq free)")
    p.add_argument("--joins", action="store_true", help="Also try cross-episode joined promos (off: 0 survived in testing)")
    p.add_argument("--title", help="Show name for the report")
    p.add_argument("--review", action="append", default=[], metavar="CSV|KIND|NAME",
                   help="A reviewer's exported ratings, e.g. 'me.csv|human|The applicant'. Repeat for more reviewers; KIND is human or ai")
    p.add_argument("--reviewer-name", help="Who made the --decisions ratings (default: the applicant)")
    p.add_argument("--reviewer-kind", choices=["human", "ai"], default="human",
                   help="Say 'ai' when the decisions came from a model, so the report never calls them a human review")
    p.add_argument("--decisions", type=Path, help="CSV exported from the review page (keep / trim / pass) to score against a person")
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


def rules_cuts(ep, limit=1, source="rules"):
    """The no-AI baseline: lexical hook and cliffhanger signals (kept for the ablation)."""
    out = []
    for w in propose(ep, limit=limit):
        cut, _ = build(ep, w.hook, w.closing, source, preserve_ending=source == "recovery")
        if cut:
            out.append({"cut": cut, "hook_type": "shocking_line", "hook": w.hook.text, "spoiler": "none",
                        "open_question": w.closing.text, "why": "Picked by word-based rules, not judged by a model: a strong opening line and an unresolved closing line.",
                        "rules_score": w.score})
    return out


def recovery_cuts(ep, tried, limit=5):
    """Try unseen windows with a preference for different openings."""
    candidates = []
    for entry in rules_cuts(ep, limit=24, source="recovery"):
        cut = entry["cut"]
        if cut.key in tried or any(cut.hook_ref == row["cut"].hook_ref for row in candidates):
            continue
        candidates.append(entry)
        if len(candidates) == limit:
            break
    return candidates


def main(argv=None, *, key=None, base_url=None, log_fn=None):
    """key, base_url and log_fn are per-call so a shared web server never mixes visitors up."""
    log = log_fn or _say
    args = arguments(argv)
    load_dotenv()
    started = time.monotonic()
    all_episodes = load_episodes(args.input)
    episodes = pick(all_episodes, args.episodes)
    if not episodes:
        raise ValueError("The episode selection matches no input files.")
    by_number = {e.number: e for e in episodes}
    last = max(e.number for e in all_episodes)
    out = args.out or Path("private/runs") / datetime.now().strftime("%Y%m%d-%H%M%S")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError(f"Output path already contains a run: {out}. Choose a new folder.")
    log(f"Read {len(episodes)} episodes, {sum(len(e.cues) for e in episodes)} timed cues.")

    rules_only = args.model == "rules"
    def make(spec):
        same = spec.partition(":")[0] == args.model.partition(":")[0]
        return Model(spec, args.cache, key=key if same else None, base_url=base_url if same else None)

    editor_model = None if rules_only else make(args.model)
    judge = None if rules_only else (make(args.judge) if args.judge else editor_model)
    raw: list[dict] = []
    warnings: list[str] = []

    def warn(message: str) -> None:
        warnings.append(message)
        log(message)

    # 1. guide -------------------------------------------------------------------------------
    notes = ai.fallback_guide(episodes)
    if editor_model and not editor_model.local and not args.no_guide:
        log(f"Reading the whole show once with {editor_model.label} ...")
        try:
            notes = ai.guide(editor_model, episodes)
            raw.append(notes.pop("_record"))
        except ModelError as exc:
            warn(f"Show guide unavailable ({str(exc)[:140]}). Using source labels without inferred spoilers.")
    names = notes.get("names", {})

    # 2. candidates --------------------------------------------------------------------------
    entries, rejected = [], []
    finder_available = bool(editor_model)
    for ep in episodes:
        mine = []
        try:
            if finder_available and args.finder == "beats":
                record = beats.score_beats(editor_model, ep, names)
                raw.append(record)
                found, stats = beats.search(ep, record["answer"]["beats"], notes=notes)
                if not found:
                    rejected.append({"episode": ep.number, "why_rejected": "no legal hook x cliffhanger pair", **stats})
                mine += found
            elif finder_available:
                found, failed = editor_cuts(editor_model, ep, notes, raw)
                mine += found
                rejected += failed
        except ModelError as exc:
            finder_available = False
            warn(f"AI finder stopped at episode {ep.number:02d} ({str(exc)[:140]}). Remaining episodes use timing-based discovery.")
        if not finder_available or not args.no_rules_check:
            for r in rules_cuts(ep):  # skip a rules clip that duplicates an editor clip
                if not any(overlap(r["cut"], m["cut"]) > 0.6 for m in mine):
                    mine.append(r)
        entries += mine
        log(f"  episode {ep.number:02d}: {sum(m['cut'].source in AI_SOURCES for m in mine)} AI picks")
    for i, e in enumerate(entries, 1):
        e["id"] = f"P{i:03d}"

    # 3. cold viewer -------------------------------------------------------------------------
    judge_available = bool(judge)

    def view(pool):
        nonlocal judge_available
        kept = []
        for e in pool:
            if judge is None:
                e.update(view=None, passed=True, why_rejected=None)
                kept.append(e)
                continue
            if judge_available:
                try:
                    record = ai.viewer(judge, e["cut"], by_number)
                except ModelError as exc:
                    judge_available = False
                    warn(f"Cold viewer unavailable ({str(exc)[:140]}). Remaining candidates require editor review.")
            if not judge_available:
                e.update(view=None, passed=False, why_rejected="viewer unavailable")
                rejected.append(e)
                continue
            raw.append(record)
            ok, why = ai.passes(record["answer"])
            if ok and e["cut"].source == "recovery":
                verdict = record["answer"]
                if (verdict["first_3s"], verdict["makes_sense"], verdict["ending"]) != ("stop", "yes", "unresolved"):
                    ok, why = False, "alternate needs editor review: opening, clarity or suspense was borderline"

            e.update(view=record["answer"], passed=ok, why_rejected=None if ok else why)
            (kept if ok else rejected).append(e)
        return kept

    if judge:
        log(f"Cold viewer ({judge.label}) is watching {len(entries)} clips with no context ...")
    passing = view(entries)

    if judge_available and args.recover:
        covered = {entry["cut"].first_episode for entry in passing}
        tried = {entry["cut"].key for entry in entries}
        for ep in episodes:
            if ep.number in covered:
                continue
            candidates = recovery_cuts(ep, tried)
            log(f"  episode {ep.number:02d}: checking {len(candidates)} alternate cuts")
            for alternate in candidates:
                alternate["id"] = f"P{len(entries) + 1:03d}"
                accepted = view([alternate])
                entries.append(alternate)
                if accepted:
                    passing.extend(accepted)
                    break
                if not judge_available:
                    break
            if not judge_available:
                break

    # 4. joined promos -----------------------------------------------------------------------
    if finder_available and judge_available and not editor_model.local and args.joins:
        firsts, seen = [], set()
        for e in passing:
            if e["cut"].source in AI_SOURCES and len(e["cut"].segments) == 1 and e["cut"].first_episode not in seen:
                seen.add(e["cut"].first_episode)
                firsts.append(e["cut"])
        if len(firsts) >= 2:
            log(f"Looking for stronger promos that join moments across episodes ({len(firsts)} candidates) ...")
            joined = []
            try:
                record = ai.joins(editor_model, firsts[:50], by_number, notes)
                raw.append(record)
                joined = record["answer"]["joins"][:4]
            except ModelError as exc:
                warn(f"Join suggestions unavailable ({str(exc)[:140]}). Exporting the continuous cuts.")
            new = []
            for j in joined:
                parts = []
                for m in j["moments"][:3]:
                    ep_no, separator, _ = m["first_cue"].strip().upper().lstrip("E").partition("-")
                    ep = by_number.get(int(ep_no)) if separator and ep_no.isdecimal() else None
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
        e["pre"] = sum(grade[v[k]] for k in ("first_3s", "makes_sense", "ending")) if v else e.get("rules_score", 1.0)
    pool = sorted(passing, key=lambda e: (-e["pre"], e["cut"].first_episode))[: args.rank_top]
    ranking = None
    ranking_note = None
    if judge_available and args.rounds > 0 and len(pool) > 1:
        log(f"Ranking {len(pool)} clips in {args.rounds} shuffled rounds ...")
        try:
            ranking = ai.rank(judge, [e["cut"] for e in pool], by_number, rounds=args.rounds, raw=raw)
        except ModelError as exc:
            ranking_note = f"Tournament model unavailable ({str(exc)[:140]}). Posting order uses the viewer rubric."
            warn(ranking_note)
    if ranking and ranking["comparisons"]:
        for entry, strength in zip(pool, ranking["strength"]):
            entry["strength"] = strength
    else:
        if ranking:
            ranking_note = "Tournament returned no complete ballots. Posting order uses the viewer rubric."
        ranking = ranking or {"strength": [], "comparisons": 0, "rounds": []}
        if ranking_note:
            ranking["note"] = ranking_note
        for entry in pool:
            entry["strength"] = max(0.01, entry["pre"])
    for e in passing:
        if e not in pool:
            e["strength"] = min((x["strength"] for x in pool), default=1.0) * 0.5
    ordered = plan.order(passing, last)

    # 5b. one real sentence on why each shortlisted clip works (falls back to quoting the clip if no model answers) ------
    if args.why and (judge_available or finder_available) and (judge or editor_model):
        writer = make(args.why_model) if args.why_model else (judge if judge_available else editor_model)
        log(f"Writing one line on why each of {len(ordered)} clips works ({writer.label}) ...")
        for e in ordered:
            try:
                record = ai.explain(writer, e["cut"], by_number, opening_text(e["cut"], by_number), e.get("view"))
                raw.append(record)
                line = ai.usable_why(record["answer"]["why"])
                if line:
                    e["why"], e["why_source"] = line, "model"
            except ModelError as exc:
                warn(f"The one-line explanations stopped ({str(exc)[:140]}). The rest quote the clip instead.")
                break

    # 6. evaluate and export -------------------------------------------------------------------
    usage = [m.usage() for m in {id(m): m for m in (editor_model, judge) if m}.values()]
    summary = {"show": args.title or args.input.stem, "episodes": len(episodes),
               "cues": sum(len(e.cues) for e in episodes), "editor_model": editor_model.label if editor_model else "rules",
               "judge_model": judge.label if judge else "none", "finder": args.finder if editor_model else "rules", "candidates": len(entries), "passed": len(passing),
               "post_first": sum(e["plan"] == "post_first" for e in ordered), "usage": usage,
               "seconds": round(time.monotonic() - started, 1)}
    references = json.loads(args.references.read_text()) if args.references else None
    summary["decisions_file"] = str(args.decisions) if args.decisions else None
    summary["reviewer_name"], summary["reviewer_kind"] = args.reviewer_name, args.reviewer_kind
    summary["reviews"] = []
    for spec in ([f"{args.decisions}|{args.reviewer_kind}|{args.reviewer_name or 'the applicant'}"] if args.decisions else []) + args.review:
        path, kind, name = (spec.split("|") + ["human", "reviewer"])[:3]
        if kind not in ("human", "ai"):
            raise ValueError(f"--review kind must be human or ai, got {kind!r}")
        summary["reviews"].append({"path": path, "kind": kind, "name": name})
    summary["warnings"] = warnings
    out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=out.parent, prefix=".promo-") as temporary:
        staging = Path(temporary) / "run"
        write_all(staging, summary, notes, ordered, entries, rejected, ranking, raw, by_number, references, evaluate, all_episodes)
        os.rename(staging, out)
    outcome = "viewer-shortlisted cuts" if judge else "timing-checked review candidates"
    log(f"\nDone in {summary['seconds']} s. {len(passing)} {outcome}.\nOpen {(out / 'index.html').resolve()}")
    return out


if __name__ == "__main__":
    try:
        main()
    except (ModelError, ValueError, OSError) as exc:
        sys.exit(f"Stopped: {exc}\nFinished model answers are cached; run the same command again to resume.")
