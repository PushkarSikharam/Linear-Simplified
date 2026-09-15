from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agent_reasoner import AgentReasoner


class ReasonerResponseTest(unittest.TestCase):
    def test_missing_or_malformed_candidates_fall_back(self):
        reasoner = AgentReasoner()
        for response in (None, [], {}, {"candidates": []}, {"candidates": None},
                         {"candidates": [None]}, {"candidates": [{"content": None}]},
                         {"candidates": [{"content": {"parts": []}}]},
                         {"candidates": [{"content": {"parts": None}}]}):
            with self.subTest(response=response):
                self.assertIsNone(reasoner._parse_response(response))

    def test_non_object_or_invalid_json_falls_back(self):
        for text in ("null", "[]", "42", '"hello"', "invalid", "{}"):
            with self.subTest(text=text):
                self.assertIsNone(AgentReasoner()._parse_response({
                    "candidates": [{"content": {"parts": [{"text": text}]}}]
                }))

    def test_split_text_is_parsed_without_thought_content(self):
        answer = json.dumps({
            "speech": "I'll open Cycles.",
            "proposed_action": {"type": "OPEN_CYCLES", "payload": {}},
            "intent_trace": {"confidence": 0.9, "status": "active"}
        })
        result = AgentReasoner()._parse_response({
            "candidates": [{"content": {"parts": [
                {"thought": True, "text": "Internal content must not enter speech."},
                {"text": answer[:30]}, {"text": answer[30:]}
            ]}}]
        })
        self.assertIsNotNone(result)
        self.assertEqual(result.speech, "I'll open Cycles.")
        self.assertEqual(result.proposed_action.type, "OPEN_CYCLES")


if __name__ == "__main__":
    unittest.main()
