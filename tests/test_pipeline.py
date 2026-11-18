import unittest

from promo.ai import bradley_terry, clip_text, passes
from promo.cuts import MAX_LEN, Cut, Segment, build, join, overlap
from promo.evaluate import check_rules
from promo.llm import check, obj, string, array, _json_from
from promo import plan
from promo.screenplay import Cue, Episode, clean_edges


def episode(number=1):
    """A synthetic 70 s episode: shots every 5 s, a line in each shot."""
    cues, i = [], 1
    for k in range(14):
        t = k * 500
        cues.append(Cue(i, t, t + 500, "camera", "CAMERA", f"Shot {k}.", 1)); i += 1
        cues.append(Cue(i, t + 50, t + 400, "dialogue", "MIA" if k % 2 else "TOM", f'"Line {k}?"', 1)); i += 1
    return Episode(number, cues)


def cue(ep, text):
    return next(c for c in ep.cues if c.text == text)


class CutTest(unittest.TestCase):
    def test_build_snaps_to_shot_and_keeps_hook_in_three_seconds(self):
        ep = episode()
        cut, why = build(ep, cue(ep, '"Line 1?"'), cue(ep, '"Line 6?"'), "editor")
        self.assertEqual(why, "ok")
        seg = cut.segments[0]
        self.assertEqual(seg.start, 500)          # the shot the hook sits in
        self.assertLessEqual(cue(ep, '"Line 1?"').start - seg.start, 300)
        self.assertEqual(seg.end, 3500)           # end of the closing line's shot
        edges = clean_edges(ep)
        self.assertIn(seg.start, edges)
        self.assertIn(seg.end, edges)

    def test_build_rejects_too_short_and_too_long(self):
        ep = episode()
        short, _ = build(ep, cue(ep, '"Line 1?"'), cue(ep, '"Line 2?"'), "editor")
        self.assertEqual(short.length, 2000)        # repaired: extended to the first 20 s shot end
        self.assertEqual(short.notes["extended_from_s"], 10.0)
        cut, why = build(ep, cue(ep, '"Line 0?"'), cue(ep, '"Line 13?"'), "editor")
        self.assertIsNone(cut)
        self.assertIn("longer than 60", why)

    def test_join_requires_story_order_and_total_length(self):
        a, b = episode(2), episode(5)
        cut, why = join([(a, cue(a, '"Line 0?"'), cue(a, '"Line 2?"')), (b, cue(b, '"Line 9?"'), cue(b, '"Line 11?"'))])
        self.assertEqual(why, "ok")
        self.assertEqual([s.episode for s in cut.segments], [2, 5])
        self.assertTrue(2000 <= cut.length <= MAX_LEN)
        backwards, why = join([(b, cue(b, '"Line 0?"'), cue(b, '"Line 2?"')), (a, cue(a, '"Line 9?"'), cue(a, '"Line 11?"'))])
        self.assertIsNone(backwards)
        self.assertIn("story order", why)

    def test_overlap_is_temporal_iou(self):
        x = Cut([Segment(1, 0, 1000)], "", "", "editor")
        y = Cut([Segment(1, 500, 1500)], "", "", "editor")
        z = Cut([Segment(2, 0, 1000)], "", "", "editor")
        self.assertAlmostEqual(overlap(x, y), 500 / 1500)
        self.assertEqual(overlap(x, z), 0)

    def test_clip_text_is_clip_relative_without_ids(self):
        ep = episode()
        cut, _ = build(ep, cue(ep, '"Line 1?"'), cue(ep, '"Line 6?"'), "editor")
        text = clip_text(cut, {1: ep}, {"mia": "MIA CARTER"})
        self.assertTrue(text.startswith("[00:00.00-"))
        self.assertNotIn("E01-", text)
        self.assertIn("MIA CARTER", text)


class NewRuleTest(unittest.TestCase):
    def test_rejects_dangling_opening_and_micro_segments(self):
        ep = episode()
        ep.cues[1] = Cue(2, 50, 400, "dialogue", "TOM", '"...and it isn\'t you."', 1)
        cut, why = build(ep, ep.cues[1], cue(ep, '"Line 6?"'), "editor")
        self.assertIsNone(cut)
        self.assertIn("continues an earlier sentence", why)
        # a 1.5 s opening shot followed by a normal 5 s shot, then a 15 s shot
        cues = [Cue(1, 0, 150, "camera", "CAMERA", "Quick shot.", 1), Cue(2, 10, 140, "dialogue", "TOM", '"Now!"', 1),
                Cue(3, 150, 650, "camera", "CAMERA", "Wide.", 1), Cue(4, 200, 600, "dialogue", "MIA", '"Why?"', 1),
                Cue(5, 650, 2150, "camera", "CAMERA", "Long.", 1), Cue(6, 700, 2000, "dialogue", "TOM", '"Because."', 1)]
        short = Episode(2, cues)
        tiny, why = join([(short, cues[1], cues[1]), (short, cues[5], cues[5])])
        self.assertIsNone(tiny)
        self.assertIn("at least 5 s", why)


class RankingTest(unittest.TestCase):
    def test_bradley_terry_orders_a_consistent_winner_first(self):
        wins = {(0, 1): 3, (1, 2): 3, (0, 2): 3}
        p = bradley_terry(3, wins)
        self.assertGreater(p[0], p[1])
        self.assertGreater(p[1], p[2])

    def test_viewer_gate(self):
        good = {"first_3s": "stop", "makes_sense": "yes", "ending": "unresolved", "open_question": "Will he answer?"}
        self.assertTrue(passes(good)[0])
        self.assertFalse(passes({**good, "ending": "resolved"})[0])
        self.assertFalse(passes({**good, "open_question": "None."})[0])
        self.assertFalse(passes({**good, "first_3s": "scroll_past"})[0])


class PlanTest(unittest.TestCase):
    def entry(self, id_, ep, strength, spoiler="none", hook="reveal", start=0):
        return {"id": id_, "cut": Cut([Segment(ep, start, start + 3000)], "", "", "editor"),
                "strength": strength, "spoiler": spoiler, "hook_type": hook}

    def test_early_episodes_and_spoilers(self):
        rows = plan.order([self.entry("late", 50, 1.0), self.entry("early", 1, 0.9),
                           self.entry("spoil", 2, 1.0, "major")], last_episode=50)
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(rows[0]["id"], "early")
        self.assertEqual(by_id["spoil"]["plan"], "hold_back")
        self.assertEqual(by_id["late"]["plan"], "post_first")

    def test_one_post_first_per_episode_and_continuous_preferred(self):
        rows = plan.order([self.entry("a", 3, 1.0), self.entry("b", 3, 0.99, start=4000)], last_episode=50)
        self.assertEqual(sorted(r["plan"] for r in rows), ["library", "post_first"])
        stitched = self.entry("s", 3, 1.0)
        stitched["cut"] = Cut([Segment(3, 0, 1500), Segment(3, 4000, 5500)], "", "", "editor")
        plain = self.entry("p", 3, 1.0, start=9000)
        rows = plan.order([stitched, plain], last_episode=50)
        self.assertEqual(rows[0]["id"], "p")        # same strength and episode: the continuous clip wins
        self.assertLess(stitched["score"], plain["score"])

    def test_overlapping_clip_becomes_alternate(self):
        rows = plan.order([self.entry("a", 1, 1.0), self.entry("b", 1, 0.95, start=500)], last_episode=10)
        self.assertEqual({r["id"]: r["plan"] for r in rows}, {"a": "post_first", "b": "alternate"})


class RuleCheckTest(unittest.TestCase):
    def test_flags_mid_line_cut_and_late_hook(self):
        ep = episode()
        good = {"id": "P1", "segments": [{"episode": 1, "start_cs": 500, "end_cs": 3500}], "hook_cue": [1, 4]}
        self.assertEqual(check_rules([good], {1: ep}), [])
        bad = {"id": "P2", "segments": [{"episode": 1, "start_cs": 600, "end_cs": 3500}], "hook_cue": [1, 8]}
        problems = " ".join(check_rules([bad], {1: ep}))
        self.assertIn("spoken line", problems)
        self.assertIn("first 3 seconds", problems)


class SchemaTest(unittest.TestCase):
    def test_check_and_lenient_json(self):
        schema = obj(order=array(string("A", "B")), reason=string())
        self.assertEqual(check({"order": ["B", "A"], "reason": " ok "}, schema), {"order": ["B", "A"], "reason": "ok"})
        with self.assertRaises(ValueError):
            check({"order": ["C"], "reason": ""}, schema)
        self.assertEqual(_json_from('<think>hm</think>```json\n{"a": 1}\n```'), {"a": 1})


if __name__ == "__main__":
    unittest.main()
