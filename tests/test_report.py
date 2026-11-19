import copy
import re
import unittest
from html.parser import HTMLParser

from promo.report import render_report


def fixture():
    return {
        "show": "Beacon Shift",
        "summary": {"episodes": 2, "cues": 10, "model": "fixture", "model_success": 2},
        "promos": [
            {
                "rank": 1,
                "episode": 2,
                "start": "00:10.00",
                "end": "00:36.00",
                "duration_s": 26,
                "hook": "A second light appears in the harbor.",
                "cliffhanger": "Who is sending the signal?",
                "why": "The reply arrives just before the cut.",
                "next_beat": "The keeper recognizes the pattern.",
                "opening_evidence": "A lantern flashes.",
                "closing_evidence": "Three answering flashes.",
                "method": "rules",
                "score": 7,
                "segments": [{"episode": 2, "start": "00:10.00", "end": "00:36.00"}],
            },
            {
                "rank": 2, "episode": 1, "start": "00:01.00", "end": "00:12.00",
                "duration_s": 24, "hook": "A key falls.", "cliffhanger": "Who catches it?",
                "why": "The second scene reframes the handoff.", "next_beat": "The light returns.",
                "opening_evidence": "A brass key.", "closing_evidence": "An open hand.",
                "method": "rules", "score": 6,
                "segments": [
                    {"episode": 1, "start": "00:01.00", "end": "00:12.00"},
                    {"episode": 2, "start": "00:20.00", "end": "00:33.00"},
                ],
            },
        ],
    }


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class ReportTests(unittest.TestCase):
    def test_empty_report(self):
        html = render_report({"show": "Empty", "summary": {}, "promos": []})
        self.assertIn("No cuts to review", html)
        self.assertNotIn('id="export"', html)
        self.assertNotIn('class="cut"', html)

    def test_evidence_ordered_segments_and_spoiler(self):
        html = render_report(fixture())
        self.assertIn("A lantern flashes.", html)
        self.assertIn("Three answering flashes.", html)
        self.assertIn("<summary>Reveal the next beat</summary>", html)
        self.assertIn("<td>Episode 1</td><td>00:01.00</td><td>00:12.00</td>", html)
        self.assertIn("<td>Episode 2</td><td>00:20.00</td><td>00:33.00</td>", html)
        self.assertIn('href="#cut-1"', html)

    def test_script_content_is_escaped_in_text_and_attributes(self):
        data = fixture()
        payload = '</h2><script src="https://example.invalid"></script><img onerror="throw 0">'
        data["show"] = payload
        data["promos"][0].update(hook=payload, next_beat=payload, method=payload)
        data["promos"][0]["segments"][0]["episode"] = payload
        html = render_report(data)
        dom = Tags()
        dom.feed(html)
        self.assertNotIn(payload, html)
        self.assertIn("&lt;script", html)
        self.assertEqual([attrs for tag, attrs in dom.tags if tag == "script"], [{}])
        self.assertFalse(any(tag == "img" or "onerror" in attrs for tag, attrs in dom.tags))

    def test_storage_identity_tracks_actual_content(self):
        data = fixture()
        updated = copy.deepcopy(data)
        updated["promos"][0]["next_beat"] = "A different outcome."
        key = lambda value: re.search(r' data-run="([0-9a-f]+)"', render_report(value)).group(1)
        self.assertEqual(key(data), key(copy.deepcopy(data)))
        self.assertNotEqual(key(data), key(updated))


if __name__ == "__main__":
    unittest.main()


class HumanReviewTest(unittest.TestCase):
    def test_review_page_export_round_trips_into_the_score(self):
        import csv, tempfile
        from promo.evaluate import human_review
        promos = [{"segments": [{"episode": 2, "start": "00:10.00", "end": "00:36.00"}], "plan": "post_first", "source": "beats"},
                  {"segments": [{"episode": 3, "start": "00:00.00", "end": "00:30.00"}, {"episode": 4, "start": "00:05.00", "end": "00:20.00"}],
                   "plan": "library", "source": "rules"}]
        html = render_report({"show": "x", "summary": {}, "promos": promos})
        cells = re.findall(r'data-segments="([^"]+)"', html)
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["rank", "decision", "segments_in_order"])
            w.writerow([1, "keep", cells[0].replace("&amp;", "&")])
            w.writerow([2, "pass", cells[1].replace("&amp;", "&")])
        h = human_review(f.name, promos)
        self.assertEqual(h["all"]["n"], 2)
        self.assertEqual(h["post_first"]["keep"], 1)
        self.assertEqual(h["by_finder"]["rules"]["pass"], 1)


class ReviewerKindTest(unittest.TestCase):
    def test_an_ai_reviewer_is_never_reported_as_a_human(self):
        import csv, tempfile
        from promo.evaluate import human_review
        promos = [{"segments": [{"episode": 2, "start": "00:10.00", "end": "00:36.00"}], "plan": "post_first", "source": "beats"}]
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["rank", "decision", "segments_in_order"])
            w.writerow([1, "keep", "Ep 2 [00:10.00 \u2013 00:36.00]"])
        h = human_review(f.name, promos, "Codex (script review)", "ai")
        self.assertEqual((h["reviewer"], h["kind"]), ("Codex (script review)", "ai"))
        self.assertEqual(human_review(f.name, promos)["kind"], "human")


class AgreementTest(unittest.TestCase):
    def test_kappa_and_counts(self):
        from promo.evaluate import review_agreement
        mk = lambda name, d: {"reviewer": name, "decisions": d}
        a = mk("a", {"x": "keep", "y": "keep", "z": "pass", "w": "trim"})
        b = mk("b", {"x": "keep", "y": "pass", "z": "pass", "w": "trim"})
        g = review_agreement(a, b)
        self.assertEqual((g["cuts"], g["identical"], g["post_vs_pass_agree"]), (4, 3, 3))
        self.assertGreater(g["kappa_three_way"], 0.5)
        self.assertIsNone(review_agreement(a, None))
