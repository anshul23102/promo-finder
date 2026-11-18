import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from promo.screenplay import Cue, Episode, load_episodes, next_beat, propose, stamp


def script(number):
    return f"""EPISODE NUMBER: Episode {number}
EPISODE LOGLINE: A hint outside the cut.
CONTINUITY NOTES: A future reveal.

SCENE 01
**ACTION:**
Start: (00:00.00) | End: (00:04.00)
A ring drops to the floor.

**MIA (alarmed):**
Start: (00:01.00) | End: (00:03.00)
"Whose wedding ring is this?"

**TOM:**
Start: (00:20.20) | End: (00:24.75)
"Did you steal my
wife's ring?"

**SOUND FX:**
Start: (00:23.20) | End: (00:26.25)
Doorbell.
**MIA:**
Start: (00:27.00) | End: (00:30.00)
"I can explain."

--- SCRIPT END ---
"""


class ScreenplayTest(unittest.TestCase):
    def test_reads_zip_sorts_numbers_ignores_sidecars_and_retains_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "series.ZIP"
            with ZipFile(path, "w") as archive:
                archive.writestr("story/EPISODE-10.TXT", script(10))
                archive.writestr("story/episode-002.txt", script(2))
                archive.writestr("__MACOSX/._episode-002.txt", "ignore")
                archive.writestr("story/.DS_Store", "ignore")
            episodes = load_episodes(path)
        self.assertEqual([e.number for e in episodes], [2, 10])
        first = episodes[0]
        self.assertEqual(first.duration, 3000)
        self.assertEqual(len(first.cues), 5)
        self.assertEqual(first.cues[2].text, '"Did you steal my wife\'s ring?"')
        self.assertEqual([c.kind for c in first.cues], ["action", "dialogue", "dialogue", "sound", "dialogue"])
        self.assertTrue(all(c.scene == 1 for c in first.cues))
        self.assertEqual(next_beat(first, 2475).id, 5)
        self.assertIsNone(next_beat(first, 3000))
        self.assertEqual(stamp(2475), "00:24.75")

    def test_fresh_script_case_bom_decimal_comma_and_single_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.TXT"
            path.write_text("scene 02\nAlice:\nstart: (00:00:00,010) | end: (00:00:02,995)\nCome here.", encoding="utf-8-sig")
            ep, = load_episodes(path)
        self.assertEqual(ep.number, 1)
        self.assertEqual((ep.cues[0].start, ep.cues[0].end, ep.cues[0].speaker), (1, 300, "Alice"))

    def test_duplicate_number_conflict_and_bad_cue_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            f = folder / "episode-1.txt"
            f.write_text(script(2))
            with self.assertRaisesRegex(ValueError, "disagree"):
                load_episodes(f)
            f.write_text(script(1))
            (folder / "second.txt").write_text(script(1))
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_episodes(folder)
            f.write_text(script(1).replace("00:20.20", "00:31.10"))
            with self.assertRaisesRegex(ValueError, "end must follow"):
                load_episodes(f)
            f.write_text(script(1).replace("Start: (00:01.00)", "Start: (oops)"))
            with self.assertRaisesRegex(ValueError, "malformed"):
                load_episodes(f)

    def test_relative_duration_score_and_full_speech_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.txt"
            path.write_text(script(9))
            ep, = load_episodes(path)
        chosen = propose(ep)
        self.assertEqual(chosen, propose(ep))
        self.assertTrue(chosen)
        self.assertGreaterEqual(chosen[0].score, chosen[-1].score)
        self.assertEqual(chosen[0].closing.id, 3)
        self.assertEqual(propose(ep, limit=0), [])
        for w in chosen:
            self.assertLessEqual(2000, w.end-w.start)
            self.assertLessEqual(w.end-w.start, 6000)
            self.assertEqual((w.start, w.end), (w.hook.start, w.closing.end))
            for c in ep.cues:
                if c.kind == "dialogue":
                    self.assertFalse(c.start < w.start < c.end or c.start < w.end < c.end)
        self.assertFalse(propose(Episode(1, [Cue(1, 0, 500, "action", "", "A bell rings.")])))
