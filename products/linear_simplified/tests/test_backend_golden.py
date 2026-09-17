"""The backend must keep making the recorded decisions for the golden conversations.

Every difference from the recording must be listed, with its reason, in
`golden/reviewed_differences.json`. The recording itself is never regenerated to pass.
"""
from __future__ import annotations

import json
import unittest

from products.linear_simplified.tests.golden_backend import GOLDEN_DIR, RECORDING, load_cases, record_backend_decisions
from products.linear_simplified.tests.golden_parity import compare, load_reviewed

REVIEWED_DIFFERENCES = GOLDEN_DIR / "reviewed_differences.json"


class BackendGoldenTest(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.recorded = json.loads(RECORDING.read_text(encoding="utf-8"))
        cls.current = record_backend_decisions()

    def test_every_case_is_recorded(self):
        self.assertEqual(sorted(self.recorded), sorted(case["id"] for case in load_cases()))

    def test_decisions_match_the_recording_except_reviewed_differences(self):
        report = compare(self.recorded, self.current, load_reviewed(REVIEWED_DIFFERENCES))
        self.assertTrue(report.clean, "\n" + report.describe())


if __name__ == "__main__":
    unittest.main()
