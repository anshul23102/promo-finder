"""Account for every episode and keep review candidates out of the posting plan."""
from __future__ import annotations

from .cuts import build, following
from .screenplay import propose


def best_review_candidate(episode):
    """Find a structurally valid fallback, retaining its real opening and ending."""
    for window in propose(episode, limit=24):
        cut, _ = build(episode, window.hook, window.closing, "recovery", preserve_ending=True)
        if cut:
            next_cues = following(episode, cut.segments[-1], count=1)
            return {
                "segments": [segment.as_dict() for segment in cut.segments],
                "opening": window.hook.text,
                "ending": window.closing.text,
                "next_beat": next_cues[0].text if next_cues else "",
            }
    return None


def episode_coverage(episodes, promos, rejected=(), *, judged=True):
    """One outcome per input episode, with a timing-checked cut when available."""
    ranked = {}
    for promo in promos:
        for segment in promo["segments"]:
            ranked.setdefault(segment["episode"], promo)
    rejects_by_episode = {}
    for entry in rejected:
        cut = entry.get("cut")
        episode = cut.first_episode if cut else entry.get("episode")
        reason = entry.get("why_rejected")
        if episode is not None and reason:
            rejects_by_episode.setdefault(episode, set()).add(reason)

    results = []
    for episode in episodes.values():
        number = episode.number
        promo = ranked.get(number)
        if promo:
            review = {"segments": [segment for segment in promo["segments"] if segment["episode"] == number],
                      "opening": promo.get("opening_evidence", promo.get("hook", "")),
                      "ending": promo.get("closing_evidence", ""),
                      "next_beat": promo.get("next_beat", "")}
            status = promo.get("coverage_status", "Viewer passed" if judged else "Timing checked")
            reason = "Rank " + str(promo["rank"])
            if provenance := promo.get("coverage_source"):
                reason = provenance
        else:
            review = best_review_candidate(episode)
            status = "Review needed" if review else "No eligible cut"
            reasons = sorted(rejects_by_episode.get(number, ()))
            reason = ". ".join(reasons) if reasons else "No cut passed the viewer gate"
            if not review:
                reason += ". No valid alternate found in the candidate search."
        results.append({"episode": number, "status": status, "reason": reason, "cut": review})
    return results
