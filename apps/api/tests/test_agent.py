from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app import db
from app.main import app
from app.services.session_manager import SessionManager


class AgentApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp_dir.name) / "test.sqlite3"
        db.migrate()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_sprint_planning_returns_cycles_action(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 1,
                "product_id": "linear_simplified",
                "message": "We're using Jira and sprint planning is messy.",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "OPEN_CYCLES")
        self.assertEqual(body["intent_trace"]["current_tool"], "Jira")
        self.assertEqual(body["intent_trace"]["relevant_feature"], "Cycles")
        self.assertEqual(body["retrieved_context"][0]["source"], "cycles.md")

    def test_out_of_domain_action_is_rejected(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 2,
                "product_id": "linear_simplified",
                "message": "Open Salesforce and show me opportunities.",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "denied")
        self.assertEqual(body["proposed_action"]["type"], "OPEN_SALESFORCE")
        self.assertIsNone(body["validated_action"])
        self.assertEqual(body["intent_trace"]["status"], "denied")
        self.assertEqual(body["retrieved_context"], [])

    def test_person_ticket_lookup_opens_specific_issue(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 4,
                "product_id": "linear_simplified",
                "message": "Open the ticket created for Maya.",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "OPEN_DEMO_ISSUE")
        self.assertEqual(body["validated_action"]["payload"]["issue_id"], "LIN-142")
        self.assertEqual(body["intent_trace"]["current_intent"], "Open specific issue")
        self.assertEqual(body["retrieved_context"][0]["source"], "issues.md")
        self.assertEqual(body["speech"], "I found LIN-142, assigned to Maya Chen. I'll open that ticket.")

    def test_misspelled_ticket_lookup_opens_specific_issue(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 12,
                "product_id": "linear_simplified",
                "message": "Open the tikit for Maya.",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "OPEN_DEMO_ISSUE")
        self.assertEqual(body["validated_action"]["payload"]["issue_id"], "LIN-142")
        self.assertEqual(body["retrieved_context"][0]["source"], "issues.md")

    def test_all_tickets_for_person_filters_issues(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 17,
                "product_id": "linear_simplified",
                "message": "All the tickets for Maya which are assigned to her.",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "FILTER_ISSUES_BY_ASSIGNEE")
        self.assertEqual(body["validated_action"]["payload"]["assignee"], "Maya Chen")
        self.assertIn("I found 1 ticket assigned to Maya Chen: LIN-142", body["speech"])
        self.assertEqual(body["session_summary"]["last_person"], "Maya Chen")
        self.assertIn("issues", body["session_summary"]["interests"])

    def test_issue_followup_uses_previous_issue_context(self) -> None:
        self.client.post(
            "/api/turn",
            json={
                "session_id": "session_followup",
                "turn_id": 1,
                "product_id": "linear_simplified",
                "message": "All tickets for Maya.",
                "input_mode": "text",
            },
        )
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_followup",
                "turn_id": 2,
                "product_id": "linear_simplified",
                "message": "What about Noah?",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "FILTER_ISSUES_BY_ASSIGNEE")
        self.assertEqual(body["validated_action"]["payload"]["assignee"], "Noah Patel")
        self.assertIn("Noah Patel", body["speech"])

    def test_vague_all_request_asks_clarifying_question(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 20,
                "product_id": "linear_simplified",
                "message": "Open all the",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertIsNone(body["validated_action"])
        self.assertIn("Do you mean all issues", body["speech"])
        self.assertEqual(body["intent_trace"]["current_intent"], "Clarification needed")
        self.assertEqual(body["session_summary"]["clarification_pending"], "all_items")

    def test_correction_prefers_positive_feature_over_negated_feature(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 13,
                "product_id": "linear_simplified",
                "message": "No, not cycles, show issues instead.",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "OPEN_ISSUES")
        self.assertEqual(body["intent_trace"]["relevant_feature"], "Issues")

    def test_current_issue_context_supports_this_issue_followup(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 14,
                "product_id": "linear_simplified",
                "message": "How do I assign this issue?",
                "input_mode": "text",
                "current_page": "issue_detail",
                "selected_issue_id": "LIN-137",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "HIGHLIGHT_ASSIGNMENT_CONTROL")
        self.assertEqual(body["validated_action"]["payload"]["issue_id"], "LIN-137")

    def test_unknown_person_ticket_lookup_falls_back_to_issues(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 5,
                "product_id": "linear_simplified",
                "message": "Open the ticket created for Alex.",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "OPEN_ISSUES")
        self.assertIn("could not find a ticket for Alex", body["speech"])
        self.assertEqual(body["retrieved_context"][0]["source"], "issues.md")

    def test_new_ticket_request_creates_demo_issue(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 15,
                "product_id": "linear_simplified",
                "message": "Open a fresh ticket for Maya.",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["proposed_action"]["type"], "CREATE_DEMO_ISSUE")
        self.assertEqual(body["validated_action"]["type"], "CREATE_DEMO_ISSUE")
        self.assertEqual(body["validated_action"]["payload"]["assignee"], "Maya Chen")
        self.assertEqual(body["validated_action"]["payload"]["status"], "Todo")
        self.assertIn("I created", body["speech"])

    def test_ticket_creation_for_unknown_person_opens_team_directory(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 24,
                "product_id": "linear_simplified",
                "message": "Create a ticket for Lucifer.",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "HIGHLIGHT_ADD_MEMBER_BUTTON")
        self.assertEqual(body["validated_action"]["payload"]["name"], "Lucifer")
        self.assertIn("Lucifer is not in the team directory yet", body["speech"])
        self.assertNotIn("I created", body["speech"])

    def test_selected_issue_follow_up_updates_assignee(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 25,
                "product_id": "linear_simplified",
                "message": "Assign it to Noah",
                "input_mode": "text",
                "selected_issue_id": "LIN-142",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "UPDATE_DEMO_ISSUE")
        self.assertEqual(body["validated_action"]["payload"]["issue_id"], "LIN-142")
        self.assertEqual(body["validated_action"]["payload"]["assignee"], "Noah Patel")
        self.assertIn("assignee is now Noah Patel", body["speech"])

    def test_selected_issue_follow_up_updates_priority(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 26,
                "product_id": "linear_simplified",
                "message": "Make it high priority",
                "input_mode": "text",
                "selected_issue_id": "LIN-137",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "UPDATE_DEMO_ISSUE")
        self.assertEqual(body["validated_action"]["payload"]["priority"], "High")
        self.assertIn("priority is now High", body["speech"])

    def test_new_ticket_workflow_question_opens_issues(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 16,
                "product_id": "linear_simplified",
                "message": "Show me how to create a ticket.",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "HIGHLIGHT_CREATE_TICKET_BUTTON")
        self.assertIn("highlight Create ticket", body["speech"])

    def test_best_way_to_create_ticket_opens_issue_workflow(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 22,
                "product_id": "linear_simplified",
                "message": "So what is the best way to create a ticket?",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "HIGHLIGHT_CREATE_TICKET_BUTTON")
        self.assertIn("highlight Create ticket", body["speech"])

    def test_assignment_question_highlights_assignment_control(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 6,
                "product_id": "linear_simplified",
                "message": "How do I assign Maya's ticket to one developer?",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "HIGHLIGHT_ASSIGNMENT_CONTROL")
        self.assertEqual(body["validated_action"]["payload"]["issue_id"], "LIN-142")
        self.assertEqual(body["intent_trace"]["current_intent"], "Highlight assignment control")
        self.assertIsNone(body["intent_trace"]["role"])
        self.assertEqual(body["retrieved_context"][0]["source"], "issues.md")
        self.assertIn("Assignment is handled from the issue detail panel.", body["speech"])

    def test_github_question_retrieves_integrations_doc(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 7,
                "product_id": "linear_simplified",
                "message": "How does the GitHub integration work?",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "HIGHLIGHT_GITHUB_CARD")
        self.assertEqual(body["retrieved_context"][0]["source"], "integrations.md")

    def test_slack_question_highlights_slack_card(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 23,
                "product_id": "linear_simplified",
                "message": "What can Pixel do with Slack?",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "HIGHLIGHT_SLACK_CARD")
        self.assertIn("Slack lets teams create issues", body["speech"])
        self.assertEqual(body["retrieved_context"][0]["source"], "integrations.md")

    def test_github_setup_opens_setup_flow(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 21,
                "product_id": "linear_simplified",
                "message": "Set up the GitHub integration.",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "OPEN_GITHUB_SETUP")
        self.assertEqual(body["intent_trace"]["current_intent"], "Configure integration")
        self.assertIn("GitHub setup flow", body["speech"])

    def test_team_capacity_question_retrieves_teams_doc(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 8,
                "product_id": "linear_simplified",
                "message": "Show me team capacity and workload.",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "OPEN_TEAMS")
        self.assertEqual(body["retrieved_context"][0]["source"], "teams.md")

    def test_team_count_question_answers_count_and_opens_teams(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 18,
                "product_id": "linear_simplified",
                "message": "How many team members are there?",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["validated_action"]["type"], "OPEN_TEAMS")
        self.assertIn("There are 4 team members", body["speech"])

    def test_capability_question_answers_without_navigation(self) -> None:
        response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 19,
                "product_id": "linear_simplified",
                "message": "Are you capable of doing?",
                "input_mode": "text",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertIsNone(body["validated_action"])
        self.assertIn("I can guide this Pixel demo", body["speech"])

    def test_completed_turn_is_not_active_after_response(self) -> None:
        self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 3,
                "product_id": "linear_simplified",
                "message": "Show bug tracking.",
                "input_mode": "text",
            },
        )

        response = self.client.post(
            "/api/turn/3/cancel",
            json={"session_id": "session_test"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "not_active")

    def test_cancel_active_turn(self) -> None:
        sessions = SessionManager()
        sessions.ensure_session("session_test", "linear_simplified")
        self.assertTrue(sessions.activate_turn("session_test", 9))

        response = self.client.post(
            "/api/turn/9/cancel",
            json={"session_id": "session_test"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertFalse(sessions.is_active_turn("session_test", 9))

    def test_older_turn_cannot_replace_newer_turn(self) -> None:
        first_response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 11,
                "product_id": "linear_simplified",
                "message": "Show sprint planning.",
                "input_mode": "text",
            },
        )
        stale_response = self.client.post(
            "/api/turn",
            json={
                "session_id": "session_test",
                "turn_id": 10,
                "product_id": "linear_simplified",
                "message": "Show bug tracking.",
                "input_mode": "text",
            },
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.json()["status"], "completed")
        self.assertEqual(stale_response.status_code, 200)
        self.assertEqual(stale_response.json()["status"], "stale")
        self.assertEqual(stale_response.json()["intent_trace"]["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
