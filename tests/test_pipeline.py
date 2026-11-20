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
    def test_rejects_cut_between_two_cues_of_one_sentence(self):
        from dataclasses import replace

        ep = episode()
        start = cue(ep, '"Line 1?"')
        end = cue(ep, '"Line 6?"')
        next_line = cue(ep, '"Line 7?"')
        ep.cues[ep.cues.index(next_line)] = replace(next_line, speaker=end.speaker,
                                                      text='"...the same sentence."')
        cut, reason = build(ep, start, end, "beats", preserve_ending=True)
        self.assertIsNone(cut)
        self.assertIn("finishes the sentence", reason)

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


class RecoveryTest(unittest.TestCase):
    def test_skips_already_reviewed_intervals_and_repeated_openings(self):
        from unittest.mock import patch
        from promo.run import recovery_cuts

        rows = [{"cut": Cut([Segment(1, start, end)], hook, "", "recovery")}
                for start, end, hook in [(0, 2500, "A"), (100, 2500, "B"),
                                         (100, 3500, "B"), (200, 3500, "C")]]
        with patch("promo.run.rules_cuts", return_value=rows):
            actual = recovery_cuts(episode(), {rows[0]["cut"].key})
        self.assertEqual(actual, [rows[1], rows[3]])


class CoverageTest(unittest.TestCase):
    def test_records_passed_review_needed_and_no_eligible_cut(self):
        from unittest.mock import patch
        from promo.coverage import episode_coverage

        eps = {n: episode(n) for n in (1, 2, 3)}
        passed = [{"rank": 1, "segments": [Segment(1, 0, 3000).as_dict()]}]
        candidate = {"segments": [Segment(2, 100, 3100).as_dict()]}
        rejected = [{"episode": 2, "why_rejected": "ending resolved"}]
        with patch("promo.coverage.best_review_candidate", side_effect=[candidate, None]):
            result = episode_coverage(eps, passed, rejected)
        self.assertEqual([row["status"] for row in result],
                         ["Viewer passed", "Review needed", "No eligible cut"])
        self.assertEqual(result[1]["reason"], "ending resolved")
        self.assertIsNone(result[2]["cut"])

    def test_recovery_preserves_the_exact_ending_cue(self):
        ep = episode()
        opening = cue(ep, '"Line 1?"')
        closing = cue(ep, '"Line 6?"')
        repaired, _ = build(ep, opening, closing, "recovery", preserve_ending=True)
        self.assertIsNotNone(repaired)
        self.assertEqual(repaired.segments[0].end, closing.end)
        short, _ = build(ep, opening, cue(ep, '"Line 2?"'), "recovery", preserve_ending=True)
        self.assertIsNone(short)


class RankingTest(unittest.TestCase):
    def test_bradley_terry_orders_a_consistent_winner_first(self):
        wins = {(0, 1): 3, (1, 2): 3, (0, 2): 3}
        p = bradley_terry(3, wins)
        self.assertGreater(p[0], p[1])
        self.assertGreater(p[1], p[2])

    def test_cold_viewer_uses_source_labels_and_ignores_show_guide(self):
        from unittest.mock import Mock
        from promo.ai import viewer

        ep = episode()
        ep.logline = "Unseen context"
        cut, _ = build(ep, cue(ep, '"Line 1?"'), cue(ep, '"Line 6?"'), "editor")
        model = Mock()
        viewer(model, cut, {ep.number: ep})
        prompt = model.ask.call_args.args[2]
        self.assertIn("MIA:", prompt)
        self.assertNotIn("E01-", prompt)
        self.assertNotIn(ep.logline, prompt)

    def test_incomplete_ranking_ballot_contributes_no_votes(self):
        from unittest.mock import Mock
        from promo.ai import rank

        ep = episode()
        cuts = [Cut([Segment(1, 0, 2000)], "", "", "rules"),
                Cut([Segment(1, 2000, 4000)], "", "", "rules")]
        model = Mock()
        model.ask.return_value = {"answer": {"order": ["A", "A"]}, "model": "fixture"}
        raw = []
        result = rank(model, cuts, {1: ep}, rounds=1, raw=raw)
        self.assertEqual(raw, [model.ask.return_value])
        self.assertEqual(result["comparisons"], 0)
        self.assertEqual(result["strength"], [1.0, 1.0])
        self.assertEqual(result["rounds"][0]["excluded"], "incomplete ballot")

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

    def test_flags_an_ending_between_two_lines_of_one_sentence(self):
        ep = episode()
        at = next(i for i, c in enumerate(ep.cues) if c.text == '"Line 7?"')
        old = ep.cues[at]
        ep.cues[at] = Cue(old.id, old.start, old.end, "dialogue", "TOM", '"...and it is you."', old.scene)   # the same speaker carries the sentence on
        promo = {"id": "P3", "segments": [{"episode": 1, "start_cs": 500, "end_cs": 3500}], "hook_cue": [1, 4]}
        self.assertIn("finishes the sentence", " ".join(check_rules([promo], {1: ep})))


class ResilientRunTest(unittest.TestCase):
    def test_provider_outage_exports_review_outcomes_without_viewer_passes(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from promo.llm import ModelError
        from promo.run import main

        source = Path(__file__).resolve().parents[1] / "examples" / "last-edition"
        with TemporaryDirectory() as temp:
            out = Path(temp) / "output"
            args = [str(source), "--model", "ollama:fixture", "--out", str(out)]
            with (patch("promo.beats.score_beats", side_effect=ModelError("finder offline")),
                  patch("promo.ai.viewer", side_effect=ModelError("judge offline"))):
                main(args, log_fn=lambda _: None)
            self.assertEqual(json.loads((out / "promos.json").read_text())["promos"], [])
            coverage = json.loads((out / "coverage.json").read_text())
            self.assertEqual([r["status"] for r in coverage], ["Review needed", "Review needed"])   # the second episode ends on its own last beat, which the rules now accept as an ending
            self.assertIn("Cold viewer unavailable", (out / "evaluation.md").read_text())
            with self.assertRaisesRegex(ValueError, "already contains a run"):
                main(args, log_fn=lambda _: None)


class WhyAndHookTest(unittest.TestCase):
    def test_hook_is_what_is_on_screen_in_the_first_three_seconds(self):
        from promo.export import opening_text
        ep = episode()
        cut, why = build(ep, cue(ep, '"Line 1?"'), cue(ep, '"Line 6?"'), "editor")
        self.assertEqual(why, "ok")
        self.assertEqual(opening_text(cut, {1: ep}), '"Line 1?"')

    def test_fallback_why_quotes_the_clip_not_a_template_of_paraphrases(self):
        from promo.ai import fallback_why
        line = fallback_why('"No." / The thug shoves her back.', "Will he fight them?")
        self.assertEqual(line, 'Opens on "No." and cuts with this still open: Will he fight them?')
        self.assertIn("No summary", fallback_why("", ""))

    def test_only_a_real_one_liner_replaces_the_fallback(self):
        from promo.ai import usable_why
        self.assertIsNone(usable_why(""))
        self.assertIsNone(usable_why("Good."))
        self.assertIsNone(usable_why("word " * 60))
        self.assertEqual(usable_why("  A thug shoves her, and we need to know if he fights back. "), "A thug shoves her, and we need to know if he fights back.")


class SchemaTest(unittest.TestCase):
    def test_check_and_lenient_json(self):
        schema = obj(order=array(string("A", "B")), reason=string())
        self.assertEqual(check({"order": ["B", "A"], "reason": " ok "}, schema), {"order": ["B", "A"], "reason": "ok"})
        with self.assertRaises(ValueError):
            check({"order": ["C"], "reason": ""}, schema)
        self.assertEqual(_json_from('<think>hm</think>```json\n{"a": 1}\n```'), {"a": 1})


if __name__ == "__main__":
    unittest.main()


class BeatSearchTest(unittest.TestCase):
    def test_search_pairs_strong_opening_with_strong_ending_inside_the_rules(self):
        from promo.beats import search
        ep = episode()
        beats = [{"cue": "E01-004", "hook": 3, "cliff": 0, "question": "A shocking line"},
                 {"cue": "E01-014", "hook": 0, "cliff": 3, "question": "Will he answer?"},
                 {"cue": "E01-028", "hook": 0, "cliff": 3, "question": "Too far away"},
                 {"cue": "E01-999", "hook": 3, "cliff": 3, "question": "Not a real cue"}]
        picked, stats = search(ep, beats)
        self.assertEqual(stats["hooks"], 1)               # the made-up cue is ignored
        self.assertEqual(len(picked), 1)                  # 004 -> 028 would be over 60 s
        cut = picked[0]["cut"]
        self.assertEqual((cut.hook_ref, cut.end_ref), ("E01-004", "E01-014"))
        self.assertTrue(2000 <= cut.length <= 6000)
        self.assertIn("Will he answer?", picked[0]["why"])


class SubsetLabelTest(unittest.TestCase):
    def test_writer_labels_survive_a_subset_run(self):
        from promo.evaluate import evaluate
        e1, e2 = episode(1), episode(2)
        e2.continuity = "Resumes after Episode 1's climax, when the lantern goes out."
        result = evaluate([], [], [e1], None, {}, [], all_episodes=[e1, e2])  # run only episode 1; note lives in episode 2
        self.assertEqual(result["writer_cliffhangers"]["labels"], 1)
