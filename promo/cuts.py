"""Turn "this cue opens, that cue closes" into legal promo cuts.

Models only ever name cue IDs. This module owns every timestamp and enforces
the brief's hard rules: 20-60 seconds in total, the hook lands inside the first
3 seconds, no cut splits a spoken line, and segments stay in story order.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .screenplay import Cue, Episode, clean_edges, cue_ref, stamp

MIN_LEN, MAX_LEN, HOOK_WINDOW, MIN_SEGMENT = 2000, 6000, 300, 500  # centiseconds


@dataclass(frozen=True)
class Segment:
    episode: int
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start

    def as_dict(self) -> dict:
        return {"episode": self.episode, "start": stamp(self.start), "end": stamp(self.end),
                "duration_s": self.length / 100}


@dataclass
class Cut:
    segments: list[Segment]
    hook_ref: str
    end_ref: str
    source: str  # "editor", "rules" or "joined"
    notes: dict = field(default_factory=dict)

    @property
    def length(self) -> int:
        return sum(s.length for s in self.segments)

    @property
    def key(self) -> str:
        return "+".join(f"E{s.episode:02d}@{s.start}-{s.end}" for s in self.segments)

    @property
    def first_episode(self) -> int:
        return self.segments[0].episode


def opens_mid_sentence(ep: Episode, start: int) -> bool:
    """True when the first spoken line of a clip continues a sentence ("...and it isn't you")."""
    first = next((c for c in ep.cues if c.kind == "dialogue" and c.start >= start), None)
    return bool(first) and first.text.lstrip(' "\u201c\u2018\'').startswith(("...", "\u2026"))


def _shot_start(ep: Episode, t: int, edges: set[int]) -> int | None:
    """Latest legal start at or before t, but no more than 3 s before it."""
    options = [c.start for c in ep.cues if c.start in edges and t - HOOK_WINDOW <= c.start <= t]
    camera = [c.start for c in ep.cues if c.kind == "camera" and c.start in edges and t - HOOK_WINDOW <= c.start <= t]
    if camera:  # cut on the shot the hook happens in
        return max(camera)
    if t in edges:
        return t
    return max(options) if options else None


def _shot_end(ep: Episode, t: int, edges: set[int], limit: int) -> int | None:
    """Earliest legal end at or after t: finish the shot the last cue sits in."""
    candidates = sorted(c.end for c in ep.cues if c.end >= t and c.end in edges and c.end <= limit)
    if not candidates:
        return None
    # Prefer the end of the camera shot that contains t (an editor cuts on a shot),
    # but never run more than 2.5 s past the closing cue, which could reveal the answer.
    shot_ends = [c.end for c in ep.cues if c.kind == "camera" and c.start < t <= c.end and c.end in edges]
    for end in sorted(shot_ends):
        if end - t <= 250 and end <= limit:
            return end
    return candidates[0]


def build(ep: Episode, hook: Cue, closing: Cue, source: str) -> tuple[Cut | None, str]:
    """One continuous cut from the hook cue to the closing cue, or the reason it fails."""
    if closing.end <= hook.start:
        return None, "closing cue comes before the hook"
    edges = clean_edges(ep)
    start = _shot_start(ep, hook.start, edges)
    if start is None:
        return None, "no clean cut point within 3 s before the hook"
    end = _shot_end(ep, closing.end, edges, start + MAX_LEN)
    if end is None:
        earliest = next((c for c in ep.cues if c.kind in ("dialogue", "action") and c.start >= closing.end - MAX_LEN + 100), None)
        hint = f"; to fit, first_cue must be {cue_ref(ep, earliest)} or later" if earliest else ""
        return None, f"longer than 60 s ({(closing.end - start) / 100:.1f} s to the closing line){hint}"
    notes = {}
    if end - start < MIN_LEN:
        # Repair: run on to the first clean cut that reaches 20 s. The cold viewer
        # still decides whether the longer ending gives the answer away.
        later = sorted(t for t in edges if start + MIN_LEN <= t <= start + MAX_LEN
                       and any(c.end == t and c.kind == "camera" for c in ep.cues))
        if not later:
            return None, f"shorter than 20 s ({(end - start) / 100:.1f} s)"
        notes["extended_from_s"] = (end - start) / 100
        end = later[0]
    if opens_mid_sentence(ep, start):
        return None, "opens on a line that continues an earlier sentence"
    cut = Cut([Segment(ep.number, start, end)], cue_ref(ep, hook), cue_ref(ep, closing), source, notes)
    return cut, "ok"


def join(parts: list[tuple[Episode, Cue, Cue]], source: str = "joined") -> tuple[Cut | None, str]:
    """Join 2-3 moments in story order into one promo. Each part is a legal sub-clip."""
    if not 2 <= len(parts) <= 3:
        return None, "a joined promo needs 2 or 3 moments"
    segments = []
    for i, (ep, first, last) in enumerate(parts):
        edges = clean_edges(ep)
        start = _shot_start(ep, first.start, edges)
        if start is None:
            return None, f"moment {i + 1}: no clean start"
        end = _shot_end(ep, last.end, edges, start + MAX_LEN)
        if end is None or end <= start:
            return None, f"moment {i + 1}: no clean end"
        if end - start < MIN_SEGMENT:
            return None, f"moment {i + 1} is only {(end - start) / 100:.1f} s; each moment needs at least 5 s"
        if opens_mid_sentence(ep, start):
            return None, f"moment {i + 1} opens on a line that continues an earlier sentence"
        segments.append(Segment(ep.number, start, end))
    order = [(s.episode, s.start) for s in segments]
    if order != sorted(order) or any(a.episode == b.episode and a.end > b.start for a, b in zip(segments, segments[1:])):
        return None, "moments must be in story order without overlapping"
    total = sum(s.length for s in segments)
    if not MIN_LEN <= total <= MAX_LEN:
        return None, f"joined length {total / 100:.1f} s is outside 20-60 s"
    first_ep, first_cue = parts[0][0], parts[0][1]
    last_ep, last_cue = parts[-1][0], parts[-1][2]
    return Cut(segments, cue_ref(first_ep, first_cue), cue_ref(last_ep, last_cue), source), "ok"


def overlap(a: Cut, b: Cut) -> float:
    """Temporal IoU across all segments (0 when they share no footage)."""
    inter = 0
    for x in a.segments:
        for y in b.segments:
            if x.episode == y.episode:
                inter += max(0, min(x.end, y.end) - max(x.start, y.start))
    union = a.length + b.length - inter
    return inter / union if union else 0.0


def cues_in(ep: Episode, seg: Segment) -> list[Cue]:
    return [c for c in ep.cues if c.start >= seg.start and c.end <= seg.end]


def following(ep: Episode, seg: Segment, count: int = 3) -> list[Cue]:
    """What a viewer would see next if the clip kept running (dialogue/action first)."""
    later = [c for c in ep.cues if c.start >= seg.end and c.kind in ("dialogue", "action")]
    return later[:count]
