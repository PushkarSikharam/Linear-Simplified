"""The backend must keep making the recorded decisions for the golden conversations."""
from __future__ import annotations

import json
import unittest

from products.linear_simplified.tests.golden_backend import RECORDING, load_cases, record_backend_decisions


class BackendGoldenTest(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.recorded = json.loads(RECORDING.read_text(encoding="utf-8"))
        cls.current = record_backend_decisions()

    def test_every_case_is_recorded(self):
        self.assertEqual(sorted(self.recorded), sorted(case["id"] for case in load_cases()))

    def test_decisions_match_the_recording(self):
        for case_id, expected in self.recorded.items():
            with self.subTest(case=case_id):
                self.assertEqual(self.current[case_id], expected)


if __name__ == "__main__":
    unittest.main()
