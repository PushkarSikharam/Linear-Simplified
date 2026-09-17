"""The parity harness must catch unlisted, stale and mismatched differences."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from products.linear_simplified.tests.golden_parity import (
    CASE_PRESENCE,
    MISSING,
    TURN_COUNT,
    ReviewedDifference,
    compare,
    differences,
    load_reviewed,
)

RECORDED = {
    "greeting": [{"speech": "Hi there.", "status": "completed"}],
    "update": [
        {"speech": "Which ticket?", "status": "completed"},
        {"speech": "Done. I updated LIN-1.", "status": "completed"},
    ],
}


def changed(edits: dict | None = None) -> dict:
    current = json.loads(json.dumps(RECORDED))
    for (case, turn, field), value in (edits or {}).items():
        current[case][turn][field] = value
    return current


def entry(**overrides) -> ReviewedDifference:
    values = {
        "case": "update", "turn": 1, "field": "speech",
        "recorded": "Done. I updated LIN-1.", "current": "I'll update LIN-1.",
        "kind": "behaviour", "reason": "Completion is claimed only after the write commits.",
    }
    values.update(overrides)
    return ReviewedDifference(**values)


class ParityHarnessTest(unittest.TestCase):
    def test_identical_recordings_are_clean(self):
        self.assertTrue(compare(RECORDED, changed(), []).clean)

    def test_unlisted_differences_fail(self):
        current = changed({("update", 1, "speech"): "I'll update LIN-1."})
        report = compare(RECORDED, current, [])
        self.assertEqual([(d.case, d.turn, d.field) for d in report.unlisted], [("update", 1, "speech")])
        self.assertIn("unlisted update[1].speech", report.describe())

    def test_listed_differences_pass(self):
        current = changed({("update", 1, "speech"): "I'll update LIN-1."})
        self.assertTrue(compare(RECORDED, current, [entry()]).clean)

    def test_listed_differences_that_no_longer_occur_fail(self):
        report = compare(RECORDED, changed(), [entry()])
        self.assertEqual(len(report.stale), 1)
        self.assertFalse(report.clean)

    def test_listed_differences_with_other_values_fail(self):
        current = changed({("update", 1, "speech"): "Updating LIN-1 now."})
        report = compare(RECORDED, current, [entry()])
        self.assertEqual(len(report.mismatched), 1)
        self.assertFalse(report.clean)

    def test_structural_differences_are_reported(self):
        current = changed()
        del current["greeting"]
        current["update"].append({"speech": "Extra.", "status": "completed"})
        fields = {(d.case, d.field) for d in differences(RECORDED, current)}
        self.assertEqual(fields, {("greeting", CASE_PRESENCE), ("update", TURN_COUNT)})

    def test_missing_fields_count_as_differences(self):
        current = changed()
        del current["greeting"][0]["status"]
        self.assertEqual([d.field for d in differences(RECORDED, current)], ["status"])

    def test_a_removed_null_field_is_a_difference(self):
        recorded = {"turn": [{"speech": "Hi.", "validated_action": None}]}
        current = {"turn": [{"speech": "Hi."}]}
        found = differences(recorded, current)
        self.assertEqual([(d.field, d.recorded, d.current) for d in found], [("validated_action", None, MISSING)])
        self.assertFalse(compare(recorded, current, []).clean)

    def test_an_added_null_field_is_a_difference(self):
        recorded = {"turn": [{"speech": "Hi."}]}
        current = {"turn": [{"speech": "Hi.", "validated_action": None}]}
        found = differences(recorded, current)
        self.assertEqual([(d.field, d.recorded, d.current) for d in found], [("validated_action", MISSING, None)])
        self.assertFalse(compare(recorded, current, []).clean)

    def test_values_of_different_json_types_differ(self):
        recorded = {"turn": [{"flag": True, "count": 1}]}
        current = {"turn": [{"flag": 1, "count": 1.0}]}
        self.assertEqual({d.field for d in differences(recorded, current)}, {"flag", "count"})

    def test_a_removed_field_can_be_reviewed_with_the_missing_marker(self):
        recorded = {"turn": [{"speech": "Hi.", "validated_action": None}]}
        current = {"turn": [{"speech": "Hi."}]}
        listed = entry(case="turn", turn=0, field="validated_action", recorded=None, current=MISSING)
        self.assertTrue(compare(recorded, current, [listed]).clean)


class ReviewedFileTest(unittest.TestCase):
    def load(self, entries) -> list[ReviewedDifference]:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "reviewed.json"
            path.write_text(json.dumps(entries), encoding="utf-8")
            return load_reviewed(path)

    def valid(self, **overrides) -> dict:
        values = dict(entry().__dict__)
        values.update(overrides)
        return values

    def test_valid_entries_load(self):
        self.assertEqual(self.load([self.valid()]), [entry()])

    def test_invalid_entries_are_rejected(self):
        invalid = {
            "unknown kind": [self.valid(kind="cosmetic")],
            "missing reason": [self.valid(reason="")],
            "vague reason": [self.valid(reason="changed")],
            "extra key": [{**self.valid(), "approved_by": "me"}],
            "missing key": [{k: v for k, v in self.valid().items() if k != "kind"}],
            "duplicate location": [self.valid(), self.valid()],
            "not a list": {"entries": []},
        }
        for label, entries in invalid.items():
            with self.subTest(case=label), self.assertRaises(ValueError):
                self.load(entries)


if __name__ == "__main__":
    unittest.main()
