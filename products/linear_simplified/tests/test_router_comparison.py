"""3.2 slice 2: the new router, in comparison mode, against today's recorded engine decisions.

Production behaviour is unchanged: today's engine still makes every real decision, and the
backend golden test keeps comparing it with its recording.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from products.linear_simplified.tests.router_comparison import (
    LEGACY_ACTIONS,
    NOTES_PATH,
    UnmappedDecision,
    compare_all,
    load_notes,
    load_router,
    recorded_decision,
    report,
)
from app.definitions.loader import DEFAULT_SOURCE, load_definition
from app.engine.memory import ConversationMemory
from app.engine.router import TurnContext
from app.engine.routing import RouteKind

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


class RouterComparisonTest(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.comparisons = compare_all()
        cls.notes = load_notes()

    def test_every_recorded_turn_is_compared(self):
        cases = json.loads((GOLDEN_DIR / "conversations.json").read_text(encoding="utf-8"))["cases"]
        self.assertEqual(len(self.comparisons), sum(len(case["turns"]) for case in cases))

    def test_every_difference_is_explained_and_every_note_is_current(self):
        result = report(self.comparisons, self.notes)
        summary = {
            "unexplained": [
                f"{c.case}[{c.turn}] expected {c.expected} actual {c.actual}" for c in result["unexplained"]
            ],
            "stale": [f"{n['case']}[{n['turn']}]" for n in result["stale"]],
            "outdated": [f"{n['case']}[{n['turn']}] now {c.actual}" for n, c in result["outdated"]],
        }
        self.assertEqual(summary, {"unexplained": [], "stale": [], "outdated": []})

    def test_scope_disclosures_are_classified_as_security(self):
        security = {note["case"] for note in self.notes if note["resolution"] == "security"}
        self.assertEqual(security, {
            "update-outside-person", "update-unknown-person", "scope-outside-person", "scope-platform-outside-person",
        })
        for note in self.notes:
            if note["resolution"] == "security":
                with self.subTest(case=note["case"]):
                    self.assertNotEqual(note["actual"]["outcome"], "refuse:scope")
                    self.assertIn("unknown_person", json.dumps(note["actual"]))

    def test_hidden_and_unknown_people_get_the_same_answer(self):
        routers = load_router()
        hidden = routers["workspace-product-eng"].route("Show Avery's tickets", ConversationMemory(), TurnContext(1))
        unknown = routers["workspace-product-eng"].route("Show Zed's tickets", ConversationMemory(), TurnContext(1))
        self.assertEqual(
            (hidden.result.kind, hidden.result.response_key, hidden.result.proposal),
            (unknown.result.kind, unknown.result.response_key, unknown.result.proposal),
        )


class MemoryAcrossTurnsTest(unittest.TestCase):
    """Follow-up turns depend on what earlier turns produced, not on prepared state."""

    def test_follow_ups_use_the_previous_turns_focus(self):
        by_turn = {(c.case, c.turn): c for c in compare_all()}
        for case in ("current-ticket", "update-reassign", "update-priority", "update-status"):
            with self.subTest(case=case):
                self.assertEqual(by_turn[(case, 1)].actual["params"].get("target"), "LIN-142")

    def test_the_same_follow_up_without_history_does_not_act(self):
        router = load_router()["workspace-product-eng"]
        alone = router.route("assign it to Noah", ConversationMemory(), TurnContext(1)).result
        self.assertEqual((alone.kind, alone.response_key), (RouteKind.CLARIFY, "clarify_update_target"))


class AnsweredQuestionTest(unittest.TestCase):
    """An answer to Edith's question continues that request instead of starting a new one."""

    def setUp(self):
        self.router = load_router()["workspace-product-eng"]

    def conversation(self, *messages):
        from app.engine.router import remember_accepted

        memory = ConversationMemory()
        results = []
        for turn, message in enumerate(messages, 1):
            routed = self.router.route(message, memory, TurnContext(turn))
            memory = routed.memory
            if routed.result.kind in (RouteKind.PROPOSE, RouteKind.CONFIRM):
                memory = remember_accepted(memory, routed.result)
            results.append(routed.result)
        return results

    def test_choosing_what_to_create_continues_the_creation(self):
        vague, chosen, owned = self.conversation("Create something new", "a ticket", "Noah")
        self.assertEqual(vague.response_key, "clarify_create")
        self.assertEqual(chosen.response_key, "clarify_owner", "a ticket still needs an owner")
        self.assertEqual((owned.kind, owned.proposal.action_key), (RouteKind.PROPOSE, "create_issue"))
        self.assertEqual(owned.proposal.fields["assignee"], "noah-patel")

    def test_naming_the_owner_completes_a_ticket_request(self):
        asked, answered = self.conversation("Create a new ticket", "Noah")
        self.assertEqual(asked.response_key, "clarify_owner")
        self.assertEqual(answered.proposal.fields["assignee"], "noah-patel")

    def test_answering_which_items_opens_that_list(self):
        asked, answered = self.conversation("open all", "issues")
        self.assertEqual(asked.response_key, "clarify_all_items")
        self.assertEqual(answered.proposal.action_key, "open_issues")

    def test_an_owner_from_another_workspace_is_treated_as_unknown(self):
        hidden = self.conversation("Create a new ticket", "Avery")[1]
        unknown = self.conversation("Create a new ticket", "Priya")[1]
        # Both offer to add the person, so nothing says Avery exists in another workspace.
        self.assertEqual(hidden.response_key, "member_missing")
        self.assertEqual(
            (hidden.kind, hidden.response_key, hidden.proposal.action_key),
            (unknown.kind, unknown.response_key, unknown.proposal.action_key),
        )


class ComparisonTablesTest(unittest.TestCase):
    def test_every_legacy_action_maps_to_a_declared_action(self):
        definition = load_definition(DEFAULT_SOURCE, "linear_simplified", 1).definition
        self.assertEqual(set(LEGACY_ACTIONS.values()), set(definition.actions) - {"create_member"})

    def test_unmapped_decisions_fail(self):
        turn = {"proposed_action": None, "speech": "Something new", "status": "completed"}
        with self.assertRaises(UnmappedDecision):
            recorded_decision(turn)
        with self.assertRaises(UnmappedDecision):
            recorded_decision({"proposed_action": {"type": "OPEN_BILLING", "payload": {}}, "speech": "", "status": "completed"})
        with self.assertRaises(UnmappedDecision):
            recorded_decision({"proposed_action": {"type": "OPEN_DEMO_ISSUE", "payload": {"issue_id": "LIN-1", "extra": 1}},
                               "speech": "", "status": "completed"})

    def test_notes_are_validated(self):
        base = dict(load_notes()[0])
        invalid = {
            "blanket reason": [{**base, "reason": "v1 limitation"}],
            "unknown resolution": [{**base, "resolution": "ignore"}],
            "missing key": [{k: v for k, v in base.items() if k != "actual"}],
            "duplicate": [base, base],
        }
        for label, notes in invalid.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as root:
                path = Path(root) / "notes.json"
                path.write_text(json.dumps(notes), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_notes(path)

    def test_stale_and_outdated_notes_are_reported(self):
        comparisons = compare_all()
        notes = load_notes()
        stale = [dict(notes[0], case="nav-issues", turn=0)]
        self.assertEqual(len(report(comparisons, stale)["stale"]), 1)
        outdated = [dict(notes[0], actual={"outcome": "fallback", "params": {"x": 1}})]
        self.assertEqual(len(report(comparisons, outdated)["outdated"]), 1)
        self.assertTrue(NOTES_PATH.is_file())


if __name__ == "__main__":
    unittest.main()
