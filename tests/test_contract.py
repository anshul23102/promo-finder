"""The run contract (promo/contract.py): a fixture and a round trip for each consumer, plus the refusals."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from promo.browser import clean, run_upload
from promo.contract import HANDOFF_SCHEMA, SCHEMA, apply_review, validate

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "contract" / "examples"
VOLATILE = ("sha256", "run_id", "idempotency_key", "outputs_sha256")     # change whenever any source file or output changes


def strip(value):
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(clean, self.tmp)
        data = (ROOT / "examples/the-last-edition/episode-001.txt").read_bytes()
        self.doc = run_upload("episode-001.txt", data, work=self.tmp / "r", log_fn=lambda _l: None)["contract"]

    def test_the_golden_run_document_still_matches_what_the_code_produces(self):
        golden = json.loads((GOLDEN / "run.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(validate(golden), [])
        self.assertEqual(strip(self.doc), strip(golden))

    def test_round_trip_through_json(self):
        again = json.loads(json.dumps(self.doc))
        self.assertEqual(again, self.doc)
        self.assertEqual(validate(again), [])
        self.assertEqual(self.doc["schema"], SCHEMA)
        self.assertEqual(self.doc["timeline"]["unit"], "centisecond")
        self.assertTrue(self.doc["review"]["ready_requires_human_decision"])
        self.assertTrue(all(s["status"] == "timing_checked" for s in self.doc["suggestions"]))

    def test_same_input_same_idempotency_key(self):
        data = (ROOT / "examples/the-last-edition/episode-001.txt").read_bytes()
        other = run_upload("episode-001.txt", data, work=self.tmp / "r2", log_fn=lambda _l: None)["contract"]
        self.assertEqual(other["invariants"]["idempotency_key"], self.doc["invariants"]["idempotency_key"])
        changed = run_upload("episode-001.txt", data + b"\n", work=self.tmp / "r3", log_fn=lambda _l: None)["contract"]
        self.assertNotEqual(changed["invariants"]["idempotency_key"], self.doc["invariants"]["idempotency_key"])

    def test_reader_refuses_what_it_cannot_read(self):
        future = copy.deepcopy(self.doc)
        future["schema"] = "promo-finder.run/2"
        self.assertIn("unknown schema", validate(future)[0])
        approved = copy.deepcopy(self.doc)
        approved["suggestions"][0]["status"] = "human_approved"
        self.assertTrue(any("approved" in p for p in validate(approved)))
        broken = copy.deepcopy(self.doc)
        broken["suggestions"][0]["segments"][0]["end_cs"] = broken["suggestions"][0]["segments"][0]["start_cs"]
        self.assertTrue(validate(broken))
        with self.assertRaises(ValueError):
            apply_review(future, [])

    def test_handoff_keeps_only_human_decisions_and_flags_trims(self):
        s = self.doc["suggestions"][0]
        seg = s["segments"][0]
        ok = apply_review(self.doc, [{"id": s["id"], "decision": "keep", "reviewer": "A. Editor"}])
        self.assertEqual(ok["schema"], HANDOFF_SCHEMA)
        self.assertEqual(ok["ready"][0]["boundary_status"], "original_boundaries")
        trimmed = apply_review(self.doc, [{"id": s["id"], "decision": "trim", "reviewer": "A. Editor",
                                           "proposed": [{"start_cs": seg["start_cs"] + 100, "end_cs": seg["end_cs"]}]}])
        self.assertTrue(trimmed["ready"][0]["needs_rereview"])
        self.assertEqual(trimmed["ready"][0]["duration_cs"], seg["end_cs"] - seg["start_cs"] - 100)
        too_short = apply_review(self.doc, [{"id": s["id"], "decision": "trim", "reviewer": "A. Editor",
                                             "proposed": [{"start_cs": seg["start_cs"], "end_cs": seg["start_cs"] + 500}]}])
        self.assertEqual(too_short["ready"], [])
        self.assertIn("20-60", too_short["left_out"][0]["reason"])
        passed = apply_review(self.doc, [{"id": s["id"], "decision": "pass", "reviewer": "A. Editor"}])
        self.assertEqual(passed["ready"], [])
        with self.assertRaises(ValueError):
            apply_review(self.doc, [{"id": s["id"], "decision": "keep", "reviewer": ""}])
        with self.assertRaises(ValueError):
            apply_review(self.doc, [{"id": "P999", "decision": "keep", "reviewer": "x"}])
        golden = json.loads((GOLDEN / "handoff.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(golden["schema"], HANDOFF_SCHEMA)
        self.assertEqual(golden["ready"][0]["boundary_status"], "trimmed_by_reviewer")


if __name__ == "__main__":
    unittest.main()
