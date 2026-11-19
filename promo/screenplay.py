"""Read timestamped screenplays and propose source-grounded continuous cuts.

Times are integer centiseconds. Cue IDs are assigned in source order, before
sorting by time, so coincident dialogue, camera and action retain stable IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path, PurePosixPath
import re
from zipfile import ZipFile


@dataclass(frozen=True)
class Cue:
    id: int
    start: int
    end: int
    kind: str
    speaker: str
    text: str
    scene: int = 0


@dataclass
class Episode:
    number: int
    cues: list[Cue]
    logline: str = ""
    continuity: str = ""

    @property
    def duration(self) -> int:
        return max((cue.end for cue in self.cues), default=0)


@dataclass(frozen=True)
class Window:
    start: int
    end: int
    hook: Cue
    closing: Cue
    score: float


_CLOCK = r"(?:\d+:)?\d{1,3}:\d{2}(?:[.,]\d{1,3})?"
_TIMES = re.compile(
    rf"^\s*Start\s*:\s*\(?\s*({_CLOCK})\s*\)?\s*(?:\||;)\s*"
    rf"End\s*:\s*\(?\s*({_CLOCK})\s*\)?\s*$", re.I,
)
_NUMBER = re.compile(r"^\s*(?:\*\*)?Episode(?:\s+number\s*:\s*(?:Episode\s*)?|\s*[:#-]?\s+)(\d+)\b", re.I | re.M)
_FILE_NUMBER = re.compile(r"(?:episode|ep)[-_ .]*(\d+)(?!\d)", re.I)
_SCENE = re.compile(r"^\s*\*{0,2}scene\s+(\d+)\b", re.I)
_META = re.compile(r"^(?:---|scene\s+(?:\d|heading|start|end)|actions\s+and\s+dialogue|episode\s+(?:number|logline)|continuity\s+notes)", re.I)
_KINDS = {"camera": "camera", "shot": "camera", "action": "action", "visual": "action",
          "sound fx": "sound", "sound effect": "sound", "sound effects": "sound",
          "sfx": "sound", "music": "sound", "sound": "sound"}


def stamp(t: int) -> str:
    minutes, rest = divmod(t, 6000)
    seconds, cs = divmod(rest, 100)
    return f"{minutes:02}:{seconds:02}.{cs:02}"


def _centis(raw: str) -> int:
    parts = raw.replace(",", ".").split(":")
    seconds = Decimal(parts[-1])
    mins = int(parts[-2])
    if seconds >= 60 or (len(parts) == 3 and mins >= 60):
        raise ValueError(f"Invalid clock time {raw}")
    hours = int(parts[0]) if len(parts) == 3 else 0
    return (hours * 3600 + mins * 60) * 100 + int((seconds * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _parse(name: str, content: bytes, single: bool) -> Episode:
    try:
        script = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{name}: screenplay must be UTF-8 text") from exc
    header = _NUMBER.search(script)
    filename = _FILE_NUMBER.search(Path(name).stem)
    if header and filename and int(header[1]) != int(filename[1]):
        raise ValueError(f"{name}: filename and header disagree about episode number")
    matched = header or filename
    if not matched and not single:
        raise ValueError(f"{name}: missing episode number in file header or filename")
    number = int(matched[1]) if matched else 1
    if number < 1:
        raise ValueError(f"{name}: episode number must be positive")

    lines = [line.strip() for line in script.splitlines()]
    cues: list[Cue] = []
    scene = 0
    timed_rows: list[int] = []
    for i, line in enumerate(lines):
        if re.match(r"^start\s*:", line, re.I):
            if not _TIMES.fullmatch(line):
                raise ValueError(f"{name} line {i+1}: malformed cue timestamps")
            timed_rows.append(i)
    for index, i in enumerate(timed_rows):
        prev = i - 1
        while prev >= 0 and not lines[prev]:
            prev -= 1
        if prev < 0:
            raise ValueError(f"{name} line {i+1}: missing cue label")
        previous_time = timed_rows[index-1] if index else -1
        for line in lines[previous_time+1:prev]:
            found = _SCENE.match(line)
            if found:
                scene = int(found[1])
        label = lines[prev].strip("*# ").rstrip(":").strip()
        if not label or _META.match(label) or len(label) > 200 or not (lines[prev].endswith((":", "**")) or lines[prev].isupper()):
            raise ValueError(f"{name} line {i+1}: missing cue label")
        base = label.split("(")[0].strip().rstrip(":").strip()
        kind = _KINDS.get(base.casefold(), "dialogue")
        # Stop at the next label even in tightly formatted files with no blank line.
        until = len(lines)
        if index + 1 < len(timed_rows):
            until = timed_rows[index+1] - 1
            while until > i and not lines[until]:
                until -= 1
        body = []
        for line in lines[i+1:until]:
            if _META.match(line):
                break
            if line:
                body.append(line)
        if not body:
            raise ValueError(f"{name} line {i+1}: cue has no text")
        times = _TIMES.fullmatch(lines[i])
        start, end = map(_centis, times.groups())
        if start >= end:
            raise ValueError(f"{name} line {i+1}: cue end must follow its start")
        cues.append(Cue(index+1, start, end, kind, base, " ".join(body), scene))
    if not cues:
        raise ValueError(f"{name}: no timed cues found")
    logline, continuity = (_header(script, label) for label in ("logline", "continuity notes"))
    return Episode(number, sorted(cues, key=lambda cue: (cue.start, cue.id)), logline, continuity)


def _header(script: str, label: str) -> str:
    found = re.search(rf"^\s*(?:\*\*)?episode\s+{label}\s*:\s*(?:\*\*)?\s*(.+)$|^\s*(?:\*\*)?{label}\s*:\s*(?:\*\*)?\s*(.+)$",
                      script, re.I | re.M)
    return (found[1] or found[2]).strip() if found else ""


def _input_file(name: str) -> bool:
    path = PurePosixPath(name)
    return path.suffix.lower() == ".txt" and not any(part.startswith((".", "__MACOSX")) for part in path.parts)


MAX_FILES, MAX_FILE_BYTES, MAX_BYTES = 2000, 5_000_000, 100_000_000  # guards against ZIP bombs


def load_episodes(path: Path) -> list[Episode]:
    path = Path(path)
    if path.is_dir():
        sources = [(str(f.relative_to(path)), f.read_bytes()) for f in sorted(path.rglob("*"))
                   if f.is_file() and _input_file(f.relative_to(path).as_posix())]
    elif path.suffix.lower() == ".zip":
        with ZipFile(path) as archive:
            wanted = [entry for entry in archive.infolist() if _input_file(entry.filename)]
            if len(wanted) > MAX_FILES or sum(e.file_size for e in wanted) > MAX_BYTES or any(e.file_size > MAX_FILE_BYTES for e in wanted):
                raise ValueError(f"ZIP too large: at most {MAX_FILES} episodes, {MAX_FILE_BYTES // 1_000_000} MB each, {MAX_BYTES // 1_000_000} MB in total")
            sources = [(entry.filename, archive.read(entry)) for entry in wanted]
    elif path.suffix.lower() == ".txt":
        sources = [(path.name, path.read_bytes())]
    else:
        raise ValueError("Expected a .txt screenplay, a directory, or a ZIP of .txt screenplays")
    if not sources:
        raise ValueError("No .txt screenplays found")
    by_number = {}
    for name, raw in sources:
        episode = _parse(name, raw, single=len(sources) == 1)
        if episode.number in by_number:
            raise ValueError(f"Duplicate episode number {episode.number} ({name})")
        by_number[episode.number] = episode
    return [by_number[number] for number in sorted(by_number)]


# Generic editorial cues for candidate discovery. The model and reviewer later
# assess the actual story; lexical signals alone cannot decide publishability.
_STAKES = re.compile(r"\b(?:wedding|marry|marrying|bride|husband|wife|sister|daughter|son|mother|father|dead|death|alive|money|stole|stolen|crime|trial|prison|evidence|truth|liar|lied|betray\w*|blood|kill\w*|arrest\w*|steal\w*|murder\w*|secret\w*|poison\w*|innocent|guilty|fired|divorc\w*|fraud|owe|debt|forg\w*|impersonat\w*|missing|witness|weapon|gun|knife|marriage|abandon\w*)\b", re.I)
_REVERSAL = re.compile(r"\b(?:you (?:will|must|dare|knew|have no|should|cannot|can't)|how dare|turn around|never|refuse|listen to me|wait|stop|what have you|who are you|enough|where is|tell me|hand it over|give me|i swear|not anymore|i know|no longer|why (?:are|did|would))\b", re.I)
_VISUAL = re.compile(r"\b(?:slap\w*|shatter\w*|snatch\w*|collaps\w*|interrupt\w*|reveal\w*|recogniz\w*|unmask\w*|lung\w*|burst\w*|overhear\w*|witness\w*|drop(?:s|ped)?|blood\w*|slam\w*|discover\w*|pulls? (?:out|back)|tears? (?:off|open)|point(?:s|ing) (?:a|the)|creaks? open)\b", re.I)
_ANTICIPATION = re.compile(r"\b(?:about to|just as|reaches? for|begins? to|slowly turns?|swings? open|cracks? open|knock\w*|freez\w*|terrifi\w*|gasps?|at the door|stares? in (?:shock|horror)|stops? short|steps? into view)\b", re.I)
_RESOLUTION = re.compile(r"\b(?:thank you|at peace|contented|peaceful|relieved|reassuring|reunited|smiles? warmly|happily|settled|forgive you|all is well)\b", re.I)


def _signals(cue: Cue) -> tuple[float, float]:
    t = cue.text.strip(" “”—\"")
    concrete = min(2, len(set(m.group().lower() for m in _STAKES.finditer(t))))
    if cue.kind == "dialogue":
        q = "?" in t
        short = len(t.split()) < 4
        hook = 1.2 + 0.85 * concrete + 1.45 * bool(_REVERSAL.search(t)) + 0.55 * q - 0.65 * short
        close = 0.4 + 2.4 * q + 0.7 * concrete + 0.9 * bool(_REVERSAL.search(t)) - 0.45 * short
        if t.startswith(("...", "…")):
            hook -= 2.4
        if t.endswith(("...", "…")):
            hook -= 0.5
    else:
        visual = bool(_VISUAL.search(t))
        suspense = bool(_ANTICIPATION.search(t))
        # Technical descriptions and musical swells are never hooks by themselves.
        hook = 0.1 + 1.8 * visual + 0.55 * concrete + 0.65 * suspense
        close = 0.15 + 1.1 * visual + 0.55 * concrete + 1.8 * suspense
        if cue.kind == "camera" and not (visual or suspense):
            hook -= 0.8
            close -= 0.8
    if _RESOLUTION.search(t):
        close -= 1.5
    return hook, close


def story_beats_after(episode: Episode, end: int):
    """In order, dialogue and action plus cameras that describe a narrative beat."""
    for cue in sorted(episode.cues, key=lambda c: (c.start, {"dialogue": 0, "action": 1}.get(c.kind, 2), c.id)):
        if cue.start < end or cue.kind == "sound":
            continue
        if cue.kind != "camera" or _VISUAL.search(cue.text) or _ANTICIPATION.search(cue.text):
            yield cue


def next_beat(episode: Episode, end: int) -> Cue | None:
    return next(story_beats_after(episode, end), None)


def propose(episode: Episode, limit: int = 5) -> list[Window]:
    if limit < 1 or episode.duration < 2000:
        return []
    cues = sorted((c for c in episode.cues if c.kind != "sound"), key=lambda c: (c.start, c.id))
    speeches = [c for c in cues if c.kind == "dialogue"]
    def clean_edge(t: int) -> bool:
        return all(not (c.start < t < c.end) for c in speeches)

    starts = [c for c in cues if clean_edge(c.start)]
    ends = [c for c in cues if clean_edge(c.end)]
    scores = {c.id: _signals(c) for c in cues}
    best: dict[tuple[int, int], Window] = {}
    for initial in starts:
        # Start on this event. Fully visible quick actions can sell an immediate
        # hook, while dialogue with its payoff late in a long line is weaker.
        hook_score, _ = scores[initial.id]
        if hook_score < 0.3:
            continue
        if initial.end - initial.start > 300:
            hook_score -= min(0.9, (initial.end - initial.start - 300) / 500)
        for ending in ends:
            length = ending.end - initial.start
            if not 2000 <= length <= 6000 or ending.start < initial.end:
                continue
            _, end_score = scores[ending.id]
            if end_score < 0.2:
                continue
            if ending.kind != "dialogue" and any(ending.start < c.start < ending.end - 100 for c in speeches):
                continue
            sequence = [c for c in speeches if c.start >= initial.start and c.end <= ending.end]
            # A grounded conversation rewards sufficient context. Repeated or
            # unrelated scenes lower the likelihood of a cold viewer following.
            coherence = min(0.8, len(sequence) * 0.14)
            if initial.scene and ending.scene and initial.scene != ending.scene:
                coherence -= 1.4
            score = hook_score + end_score + coherence - abs(length - 3350) / 11000
            window = Window(initial.start, ending.end, initial, ending, round(score, 3))
            key = (window.start, window.end)
            if key not in best or window.score > best[key].score:
                best[key] = window
    ordered = sorted(best.values(), key=lambda w: (-w.score, w.start, w.end, w.hook.id, w.closing.id))
    selected: list[Window] = []
    for w in ordered:
        def similar(other: Window) -> bool:
            overlap = max(0, min(w.end, other.end) - max(w.start, other.start))
            union = (w.end - w.start) + (other.end - other.start) - overlap
            return overlap / union >= 0.6 or w.closing.id == other.closing.id
        if not any(similar(other) for other in selected):
            selected.append(w)
        if len(selected) == limit:
            break
    return selected


def cue_ref(episode: Episode, cue: Cue) -> str:
    """Stable human-readable reference, e.g. E07-034."""
    return f"E{episode.number:02d}-{cue.id:03d}"


def clean_edges(episode: Episode) -> set[int]:
    """Times where a cut never splits a spoken line."""
    speech = [c for c in episode.cues if c.kind == "dialogue"]
    times = {c.start for c in episode.cues} | {c.end for c in episode.cues} | {0}
    return {t for t in times if not any(c.start < t < c.end for c in speech)}


def render(episode: Episode, cues: list[Cue] | None = None, *, ids: bool = True,
           camera: bool = True, names: dict[str, str] | None = None, origin: int = 0) -> str:
    """Compact screenplay text for a model: one cue per line on the source clock."""
    rows = []
    for c in cues if cues is not None else episode.cues:
        if c.kind == "camera" and not camera:
            continue
        who = (names or {}).get(c.speaker.casefold(), c.speaker) if c.kind == "dialogue" else c.kind.upper()
        ref = f"{cue_ref(episode, c)} " if ids else ""
        rows.append(f"[{ref}{stamp(c.start - origin)}-{stamp(c.end - origin)}] {who}: {c.text}")
    return "\n".join(rows)
