"""The Linear demo is a valid platform-shared Product Definition, run by the seeded demo organization."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.auth import create_token  # noqa: E402
from app.definitions.loader import DEFAULT_SOURCE, load_definition  # noqa: E402
from app.definitions.organizations import OrganizationDirectory  # noqa: E402
from app.definitions.registry import DefinitionRegistry  # noqa: E402
from app.definitions.vocabulary import Capability  # noqa: E402
from app.main import app  # noqa: E402
from app.services import env as env_module  # noqa: E402

DEFINITION_ID = "linear_simplified"
# The seeded development organization and its product running this definition.
TENANT_ID, PRODUCT_ID = "pixel-dev", "linear-demo"

# Every action the current web app and backend know, and the definition action expressing it.
LEGACY_ACTIONS = {
    "OPEN_DASHBOARD": ("open_dashboard", Capability.NAVIGATE_VIEW),
    "OPEN_ISSUES": ("open_issues", Capability.NAVIGATE_VIEW),
    "OPEN_PROJECTS": ("open_projects", Capability.NAVIGATE_VIEW),
    "OPEN_CYCLES": ("open_cycles", Capability.NAVIGATE_VIEW),
    "OPEN_TEAMS": ("open_teams", Capability.NAVIGATE_VIEW),
    "OPEN_INTEGRATIONS": ("open_integrations", Capability.NAVIGATE_VIEW),
    "OPEN_SYSTEM_ARCHITECTURE": ("open_architecture", Capability.NAVIGATE_VIEW),
    "OPEN_DEMO_ISSUE": ("open_issue", Capability.OPEN_RECORD),
    "CREATE_DEMO_ISSUE": ("create_issue", Capability.CREATE_RECORD),
    "CREATE_DEMO_TEAM_MEMBER": ("create_member", Capability.CREATE_RECORD),
    "UPDATE_DEMO_ISSUE": ("update_issue", Capability.UPDATE_RECORD),
    "FILTER_ISSUES_BY_ASSIGNEE": ("issues_by_assignee", Capability.FILTER_RECORDS),
    "HIGHLIGHT_ASSIGNMENT_CONTROL": ("highlight_assignment", Capability.HIGHLIGHT_CONTROL),
    "HIGHLIGHT_CREATE_TICKET_BUTTON": ("highlight_create_issue", Capability.HIGHLIGHT_CONTROL),
    "HIGHLIGHT_ADD_MEMBER_BUTTON": ("highlight_add_member", Capability.HIGHLIGHT_CONTROL),
    "HIGHLIGHT_CYCLE_PROGRESS": ("highlight_cycle_progress", Capability.HIGHLIGHT_CONTROL),
    "OPEN_GITHUB_SETUP": ("open_github_setup", Capability.HIGHLIGHT_CONTROL),
    "HIGHLIGHT_GITHUB_CARD": ("highlight_github", Capability.HIGHLIGHT_CONTROL),
    "HIGHLIGHT_SLACK_CARD": ("highlight_slack", Capability.HIGHLIGHT_CONTROL),
}


class LinearDefinitionTest(unittest.TestCase):
    def setUp(self):
        self.definition = load_definition(DEFAULT_SOURCE, DEFINITION_ID, 1).definition

    def test_v1_loads_and_validates(self):
        identity = self.definition.definition
        self.assertEqual((identity.definition_id, identity.ownership), (DEFINITION_ID, "platform_shared"))
        self.assertIsNone(identity.owner_organization)
        self.assertEqual(set(self.definition.entities), {"project", "cycle", "member", "issue"})

    def test_every_current_action_is_expressed(self):
        for legacy, (key, capability) in LEGACY_ACTIONS.items():
            with self.subTest(action=legacy):
                self.assertEqual(self.definition.actions[key].capability, capability)
        self.assertEqual(len(self.definition.actions), len(LEGACY_ACTIONS))

    def test_scope_is_anchored_on_projects_by_reference(self):
        self.assertEqual(self.definition.scope.anchor, "project")
        self.assertEqual(self.definition.scope.paths["issue"], ["project"])
        self.assertEqual(self.definition.scope.paths["member"], ["projects"])

    def test_people_are_references_not_names(self):
        self.assertEqual(self.definition.entities["issue"].fields["assignee"].target, "member")
        self.assertEqual(self.definition.entities["project"].fields["lead"].target, "member")

    def test_no_tenant_business_data_in_the_definition(self):
        text = DEFAULT_SOURCE.definition_path(DEFINITION_ID, 1).read_text(encoding="utf-8")
        for record_value in ("Maya", "Noah", "Avery", "Iris", "Sam Rivera", "LIN-142", "PRJ-10", "workspace-",
                             TENANT_ID, PRODUCT_ID, "planning-team"):
            with self.subTest(value=record_value):
                self.assertNotIn(record_value, text)


class LinearDemoOrganizationTest(unittest.TestCase):
    """The seed package creates the demo organization, and its chat turns run on pinned sessions."""

    def setUp(self):
        files_patch = patch.object(env_module, "_env_files", lambda: ())
        files_patch.start()
        self.addCleanup(files_patch.stop)
        env_patch = patch.dict(os.environ, {"LLM_ENABLED": "false", "PIXEL_BLOCK_EXTERNAL_HTTP": "true",
                                            "PIXEL_DEMO_SEEDS": "true"})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        db_patch = patch.object(db, "DB_PATH", Path(temporary.name) / "linear.sqlite3")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        db.migrate()
        self.client = TestClient(app, raise_server_exceptions=False)
        self.headers = {"Authorization": f"Bearer {create_token('demo-admin')}"}
        self.registry = DefinitionRegistry()
        self.directory = OrganizationDirectory(self.registry)

    def turn(self, session_id: str, turn_id: int = 1, message: str = "Show me the issues"):
        return self.client.post("/api/turn", headers=self.headers, json={
            "session_id": session_id, "turn_id": turn_id, "product_id": PRODUCT_ID, "message": message,
        }).json()

    def test_the_seeded_product_runs_v1_for_its_team(self):
        binding = self.directory.product(TENANT_ID, PRODUCT_ID)
        self.assertEqual(
            (binding.team_id, binding.definition_id, binding.definition_version, binding.state),
            ("planning-team", DEFINITION_ID, 1, "active"),
        )
        self.assertEqual(self.directory.membership(TENANT_ID, "demo-admin").role, "org_admin")
        for user_id in ("demo-product-eng", "demo-platform"):
            with self.subTest(user_id=user_id):
                self.assertEqual(self.directory.membership(TENANT_ID, user_id).team_id, "planning-team")

    def test_chat_turns_pin_their_session(self):
        self.assertEqual(self.turn("pinned")["status"], "completed")
        with db.get_connection() as connection:
            row = connection.execute(
                "select tenant_id, team_id, product_id, definition_id, definition_version, definition_checksum "
                "from sessions where id = 'pinned'"
            ).fetchone()
        self.assertEqual(
            (row["tenant_id"], row["team_id"], row["product_id"], row["definition_id"], row["definition_version"]),
            (TENANT_ID, "planning-team", PRODUCT_ID, DEFINITION_ID, 1),
        )
        self.assertEqual(row["definition_checksum"], self.registry.get(DEFINITION_ID, 1).checksum)

    def test_revoking_the_version_ends_live_conversations(self):
        self.assertEqual(self.turn("live")["status"], "completed")
        self.registry.revoke(DEFINITION_ID, 1)
        ended = self.turn("live", turn_id=2)
        self.assertEqual(ended["status"], "denied")
        self.assertIn("definition_revoked", ended["intent_trace"]["reason"])
        self.assertEqual(self.turn("new")["status"], "denied")

    def test_disabling_the_product_stops_its_pixel(self):
        self.assertEqual(self.turn("live")["status"], "completed")
        self.directory.set_product_state(TENANT_ID, PRODUCT_ID, "disabled")
        self.assertIn("product_disabled", self.turn("live", turn_id=2)["intent_trace"]["reason"])


if __name__ == "__main__":
    unittest.main()
