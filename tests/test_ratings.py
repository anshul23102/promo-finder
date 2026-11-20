"""A person's keep / trim / pass file is scored against the tool's cuts: the Review tab's handoff CSV and the older ratings CSV both work."""
import csv
import tempfile
import unittest

from promo.evaluate import human_review

PROMOS = [
    {"segments": [{"episode": 2, "start": "00:10.00", "end": "00:36.00"}], "plan": "post_first", "source": "beats", "rank": 1},
    {"segments": [{"episode": 3, "start": "01:00.00", "end": "01:30.50"}], "plan": "library", "source": "rules", "rank": 2},
]


def write(header, rows):
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(header)
    w.writerows(rows)
    f.close()
    return f.name


class RatingsTest(unittest.TestCase):
    def test_older_ratings_csv(self):
        path = write(["rank", "decision", "segments_in_order"], [[1, "keep", "Ep 2 [00:10.00 – 00:36.00]"], [2, "pass", "Ep 3 [01:00.00 – 01:30.50]"]])
        h = human_review(path, PROMOS)
        self.assertEqual((h["all"]["n"], h["post_first"]["keep"], h["by_finder"]["rules"]["pass"], h["kind"]), (2, 1, 1, "human"))

    def test_handoff_csv_from_the_review_tab(self):
        path = write(["rank", "segments_in_order", "your_decision", "original_segments"],
                     [[1, "Ep 2 00:12.50 to 00:36.00", "trim", "Ep 2 00:10.00 to 00:36.00"], [2, "Ep 3 01:00.00 to 01:30.50", "keep", ""]])
        h = human_review(path, PROMOS, "Editor", "human")
        self.assertEqual((h["reviewer"], h["all"]["n"], h["all"]["trim"], h["all"]["keep"]), ("Editor", 2, 1, 1))

    def test_unknown_cuts_and_decisions_are_ignored(self):
        path = write(["segments_in_order", "your_decision"], [["Ep 9 00:00.00 to 00:30.00", "keep"], ["Ep 2 00:10.00 to 00:36.00", "maybe"]])
        self.assertEqual(human_review(path, PROMOS)["all"]["n"], 0)


if __name__ == "__main__":
    unittest.main()
