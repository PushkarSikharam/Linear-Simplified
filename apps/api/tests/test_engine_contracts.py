"""Milestone 3.2 slice 1: engine contracts, memory rules, lookup boundary and package registry."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.definitions import vocabulary
from app.definitions.loader import load_definition
from app.definitions.safety import check_term
from app.definitions.vocabulary import Capability
from app.engine.actions import (
    ACTION_TRANSITIONS,
    PARAMETER_RULES,
    ActionState,
    ConfirmationReason,
    FilterParam,
    GenericAction,
    Param,
    RecordRef,
    UnknownAction,
    can_transition,
    confirmation_reason,
    shape_errors,
)
from app.engine.lookup import RecordLookup
from app.engine.memory import ConversationMemory, PendingClarification, PendingConfirmation
from app.engine.routing import ROUTING_STAGES, RouteKind, RouteResult, RouteStage
from app import installed_products
from definition_fixtures import DEFINITION_ID, SampleProductFiles
from engine_fixtures import InMemoryLookup, SampleDesk, engine_definition, load_engine_definition

CONTACT_1 = RecordRef("contact", "CON-1")
CONTACT_2 = RecordRef("contact", "CON-2")
CONTACT_3 = RecordRef("contact", "CON-3")


class ParameterContractTest(unittest.TestCase):
    """The table in the 3.2 plan, section 4.2, exactly."""

    def setUp(self):
        self.definition = load_engine_definition()

    def action(self, key, **params):
        return GenericAction.for_definition(self.definition, key, **params)

    def test_rules_cover_every_capability_as_planned(self):
        expected = {
            Capability.NAVIGATE_VIEW: ({Param.VIEW}, set()),
            Capability.OPEN_RECORD: ({Param.TARGET}, set()),
            Capability.FILTER_RECORDS: ({Param.FILTER}, set()),
            Capability.CREATE_RECORD: ({Param.FIELDS}, set()),
            Capability.UPDATE_RECORD: ({Param.TARGET, Param.FIELDS}, set()),
            Capability.HIGHLIGHT_CONTROL: ({Param.VIEW, Param.CONTROL}, {Param.TARGET, Param.PREFILL}),
        }
        self.assertEqual(set(PARAMETER_RULES), set(Capability))
        for capability, (required, optional) in expected.items():
            with self.subTest(capability=capability):
                rule = PARAMETER_RULES[capability]
                self.assertEqual((set(rule.required), set(rule.optional)), (required, optional))
                self.assertEqual(rule.forbidden, frozenset(Param) - required - optional)

    def test_capability_comes_from_the_definition(self):
        action = self.action("update_contact", target=CONTACT_1, fields={"status": "Closed"})
        self.assertEqual(action.capability, Capability.UPDATE_RECORD)
        with self.assertRaises(TypeError):
            self.action("update_contact", capability="NAVIGATE_VIEW")
        with self.assertRaises(UnknownAction):
            self.action("delete_contact")

    def test_a_capability_that_disagrees_with_the_definition_is_rejected(self):
        forged = GenericAction("update_contact", Capability.NAVIGATE_VIEW, view="contacts")
        self.assertEqual(shape_errors(forged, self.definition), ["capability NAVIGATE_VIEW does not match update_contact"])

    def test_valid_actions_for_every_capability(self):
        valid = [
            self.action("open_contacts", view="contacts"),
            self.action("open_contact", target=CONTACT_1),
            self.action("contacts_by_owner", filter=FilterParam("owner", "ana-lopez")),
            self.action("create_contact", fields={"name": "Gil", "account": "ACC-1"}),
            self.action("update_contact", target=CONTACT_1, fields={"status": "Closed"}),
            self.action("highlight_owner", view="contact_detail", control="owner_field", target=CONTACT_1),
            self.action("highlight_mail", view="channels", control="mail_card"),
        ]
        self.assertEqual({action.capability for action in valid}, set(Capability))
        for action in valid:
            with self.subTest(action=action.action_key):
                self.assertEqual(shape_errors(action, self.definition), [])

    def test_missing_and_forbidden_parameters_are_rejected(self):
        cases = {
            "navigation without a view": (self.action("open_contacts"), "missing parameter view"),
            "navigation with a target": (
                self.action("open_contacts", view="contacts", target=CONTACT_1), "forbidden parameter target"),
            "open without a target": (self.action("open_contact"), "missing parameter target"),
            "filter with fields": (
                self.action("contacts_by_owner", filter=FilterParam("owner", "x"), fields={"status": "Open"}),
                "forbidden parameter fields"),
            "create with a target": (
                self.action("create_contact", fields={"name": "Gil"}, target=CONTACT_1), "forbidden parameter target"),
            "update without a target": (
                self.action("update_contact", fields={"status": "Closed"}), "missing parameter target"),
            "update without fields": (self.action("update_contact", target=CONTACT_1), "missing parameter fields"),
            "highlight with a filter": (
                self.action("highlight_mail", view="channels", control="mail_card", filter=FilterParam("owner", "x")),
                "forbidden parameter filter"),
        }
        for label, (action, error) in cases.items():
            with self.subTest(case=label):
                self.assertIn(error, shape_errors(action, self.definition))

    def test_parameters_must_match_what_the_action_declares(self):
        cases = {
            "another view": (self.action("open_contacts", view="home"), "view must be contacts"),
            "another entity": (self.action("open_contact", target=RecordRef("account", "ACC-1")), "target must be a contact record"),
            "another filter field": (
                self.action("contacts_by_owner", filter=FilterParam("status", "Open")), "filter field must be owner"),
            "an undeclared field": (
                self.action("update_contact", target=CONTACT_1, fields={"name": "X"}), "fields not allowed: name"),
            "another control": (
                self.action("highlight_mail", view="channels", control="sms_card"), "control must be mail_card"),
            "a record highlight without its record": (
                self.action("highlight_owner", view="contact_detail", control="owner_field"),
                "this highlight needs a target record"),
            "a plain highlight with a record": (
                self.action("highlight_mail", view="channels", control="mail_card", target=CONTACT_1),
                "this highlight does not take a target record"),
            "an undeclared prefill": (
                self.action("highlight_mail", view="channels", control="mail_card", prefill={"name": "X"}),
                "prefill not allowed: name"),
        }
        for label, (action, error) in cases.items():
            with self.subTest(case=label):
                self.assertIn(error, shape_errors(action, self.definition))


class ExplicitParameterTest(unittest.TestCase):
    """Absent and explicitly empty parameters are different."""

    def setUp(self):
        self.definition = load_engine_definition()

    def action(self, key, **params):
        return GenericAction.for_definition(self.definition, key, **params)

    def test_empty_forbidden_parameters_are_rejected(self):
        navigation = self.action("open_contacts", view="contacts", fields={}, prefill={})
        self.assertEqual(navigation.present_params(), {Param.VIEW, Param.FIELDS, Param.PREFILL})
        errors = shape_errors(navigation, self.definition)
        self.assertIn("forbidden parameter fields", errors)
        self.assertIn("forbidden parameter prefill", errors)

    def test_empty_mutations_are_rejected_separately(self):
        update = self.action("update_contact", target=CONTACT_1, fields={})
        self.assertEqual(shape_errors(update, self.definition), ["a create or update needs at least one field"])
        create = self.action("create_contact", fields={})
        self.assertEqual(shape_errors(create, self.definition), ["a create or update needs at least one field"])

    def test_absent_optional_parameters_are_absent(self):
        highlight = self.action("highlight_mail", view="channels", control="mail_card")
        self.assertEqual(highlight.present_params(), {Param.VIEW, Param.CONTROL})
        self.assertIsNone(highlight.fields)


class SnapshotTest(unittest.TestCase):
    """A stored action cannot change after the visitor saw and confirmed it."""

    def setUp(self):
        self.definition = load_engine_definition()

    def test_changing_the_source_mapping_does_not_change_a_pending_confirmation(self):
        values = {"status": "Closed", "labels": ["vip"], "meta": {"source": "chat"}}
        action = GenericAction.for_definition(self.definition, "update_contact", target=CONTACT_1, fields=values)
        pending = PendingConfirmation(action, ConfirmationReason.DEFINITION, turn=1)
        values["status"] = "Open"
        values["labels"].append("churned")
        values["meta"]["source"] = "model"
        self.assertEqual(pending.action.fields["status"], "Closed")
        self.assertEqual(pending.action.fields["labels"], ("vip",))
        self.assertEqual(pending.action.fields["meta"]["source"], "chat")

    def test_stored_values_cannot_be_modified(self):
        action = GenericAction.for_definition(
            self.definition, "update_contact", target=CONTACT_1, fields={"status": "Closed", "meta": {"a": 1}}
        )
        with self.assertRaises(TypeError):
            action.fields["status"] = "Open"
        with self.assertRaises(TypeError):
            action.fields["meta"]["a"] = 2
        prefilled = GenericAction.for_definition(
            self.definition, "highlight_owner", view="contact_detail", control="owner_field",
            target=CONTACT_1, prefill={"owner": "ana-lopez"},
        )
        with self.assertRaises(TypeError):
            prefilled.prefill["owner"] = "ben-okafor"

    def test_filter_values_are_snapshots_too(self):
        source = ["ana-lopez"]
        action = GenericAction.for_definition(self.definition, "contacts_by_owner", filter=FilterParam("owner", source))
        source.append("cara-singh")
        self.assertEqual(action.filter.value, ("ana-lopez",))

    def test_only_plain_data_is_accepted(self):
        with self.assertRaises(TypeError):
            GenericAction.for_definition(self.definition, "update_contact", target=CONTACT_1, fields={"status": object()})
        with self.assertRaises(TypeError):
            GenericAction.for_definition(self.definition, "update_contact", target=CONTACT_1, fields=[("status", "Open")])


class ConfirmationTest(unittest.TestCase):
    def setUp(self):
        self.actions = load_engine_definition().actions

    def test_definition_confirmation(self):
        self.assertEqual(
            confirmation_reason(self.actions["update_contact"], target_from_correction=False),
            ConfirmationReason.DEFINITION,
        )

    def test_corrections_require_confirmation_for_confirm_free_mutations(self):
        spec = self.actions["reassign_contact"]
        self.assertFalse(spec.confirm)
        self.assertIsNone(confirmation_reason(spec, target_from_correction=False))
        self.assertEqual(confirmation_reason(spec, target_from_correction=True), ConfirmationReason.CORRECTION)

    def test_corrections_do_not_confirm_non_mutating_actions(self):
        self.assertIsNone(confirmation_reason(self.actions["open_contact"], target_from_correction=True))


class LifecycleTest(unittest.TestCase):
    def test_committed_outcomes_are_final(self):
        for state in (ActionState.EXECUTED, ActionState.FAILED, ActionState.CANCELLED):
            with self.subTest(state=state):
                self.assertEqual(ACTION_TRANSITIONS[state], frozenset())
        self.assertFalse(can_transition(ActionState.EXECUTED, ActionState.CANCELLED))

    def test_actions_reach_dispatch_only_after_validation(self):
        self.assertFalse(can_transition(ActionState.PROPOSED, ActionState.DISPATCHED))
        self.assertTrue(can_transition(ActionState.VALIDATED, ActionState.DISPATCHED))
        self.assertTrue(can_transition(ActionState.AWAITING_CONFIRMATION, ActionState.DISPATCHED))
        self.assertTrue(can_transition(ActionState.DISPATCHED, ActionState.CANCELLED))
        self.assertEqual(set(ACTION_TRANSITIONS), set(ActionState))


class MemoryTest(unittest.TestCase):
    def test_pending_state_expires_after_one_turn(self):
        definition = load_engine_definition()
        action = GenericAction.for_definition(definition, "reassign_contact", target=CONTACT_1, fields={"owner": "ben-okafor"})
        memory = ConversationMemory(
            pending_clarification=PendingClarification("clarify_owner", "reassign_contact", "person", turn=4),
            pending_confirmation=PendingConfirmation(action, ConfirmationReason.CORRECTION, turn=4),
            focus=CONTACT_1,
            turn=4,
        )
        answered = memory.next_turn(5)
        self.assertIsNotNone(answered.pending_clarification)
        self.assertIsNotNone(answered.pending_confirmation)
        expired = memory.next_turn(6)
        self.assertIsNone(expired.pending_clarification)
        self.assertIsNone(expired.pending_confirmation)
        self.assertEqual(expired.focus, CONTACT_1, "focus survives beyond pending state")

    def test_refusals_discard_pending_state_and_scope_changes_drop_references(self):
        memory = ConversationMemory(
            pending_clarification=PendingClarification("clarify_owner", None, "person", turn=1),
            focus=CONTACT_1, last_person=RecordRef("agent", "ana-lopez"), last_view="contacts", last_change="key-1",
        )
        refused = memory.discard_pending()
        self.assertIsNone(refused.pending_clarification)
        self.assertEqual(refused.focus, CONTACT_1)
        moved = memory.change_scope()
        self.assertEqual((moved.focus, moved.last_person, moved.last_view), (None, None, None))
        self.assertEqual(moved.last_change, "key-1")

    def test_corrections_remove_only_the_singled_out_candidate(self):
        pending = PendingClarification(
            "clarify_owner", "reassign_contact", "choice",
            candidates=(CONTACT_1, CONTACT_2, CONTACT_3), singled_out=CONTACT_1,
        )
        corrected = pending.reject_singled_out()
        self.assertEqual(corrected.candidates, (CONTACT_2, CONTACT_3))
        self.assertEqual(corrected.rejected, (CONTACT_1,))
        self.assertIsNone(corrected.singled_out, "a correction never selects the next candidate")

    def test_a_correction_after_a_list_cannot_remove_anything(self):
        listed = PendingClarification("clarify_owner", None, "choice", candidates=(CONTACT_1, CONTACT_2))
        with self.assertRaises(ValueError):
            listed.reject_singled_out()

    def test_clarifications_offer_at_most_three_candidates(self):
        with self.assertRaises(ValueError):
            PendingClarification("clarify_owner", None, "choice", candidates=(CONTACT_1, CONTACT_2, CONTACT_3, CONTACT_1))
        with self.assertRaises(ValueError):
            PendingClarification("clarify_owner", None, "choice", candidates=(CONTACT_1,), singled_out=CONTACT_2)


class RoutingContractTest(unittest.TestCase):
    def test_stages_follow_the_normative_order(self):
        self.assertEqual(
            [stage.value for stage in ROUTING_STAGES],
            ["platform_gates", "refusals", "pending_confirmation", "pending_clarification", "exact_phrases",
             "intent_groups", "requirements", "clarification_rules", "model", "fallback"],
        )

    def test_results_carry_proposals_only_when_they_propose_or_confirm(self):
        definition = load_engine_definition()
        proposal = GenericAction.for_definition(definition, "open_contacts", view="contacts")
        RouteResult(RouteKind.PROPOSE, RouteStage.INTENT_GROUPS, "view_opened", proposal=proposal)
        with self.assertRaises(ValueError):
            RouteResult(RouteKind.REFUSE, RouteStage.REFUSALS, "out_of_scope", proposal=proposal, topic="x")
        with self.assertRaises(ValueError):
            RouteResult(RouteKind.PROPOSE, RouteStage.INTENT_GROUPS, "view_opened")
        with self.assertRaises(ValueError):
            RouteResult(RouteKind.CONFIRM, RouteStage.PENDING_CLARIFICATION, "confirm_action", proposal=proposal)
        RouteResult(RouteKind.CONFIRM, RouteStage.PENDING_CLARIFICATION, "confirm_action", proposal=proposal,
                    confirmation_reason=ConfirmationReason.CORRECTION)

    def test_only_proposals_can_be_confirmed_and_only_refusals_name_a_topic(self):
        with self.assertRaises(ValueError):
            RouteResult(RouteKind.CLARIFY, RouteStage.REQUIREMENTS, "clarify_owner", confirmed=True)
        with self.assertRaises(ValueError):
            RouteResult(RouteKind.REFUSE, RouteStage.REFUSALS, "out_of_scope")
        with self.assertRaises(ValueError):
            RouteResult(RouteKind.FALLBACK, RouteStage.FALLBACK, "fallback", topic="x")


class PlatformVocabularyTest(unittest.TestCase):
    def test_new_response_keys_are_platform_keys(self):
        for key in ("record_create_proposed", "record_update_proposed", "confirm_action", "action_cancelled"):
            with self.subTest(key=key):
                self.assertIn(key, vocabulary.RESPONSE_KEYS)

    def test_reply_lists_are_literal_normalized_terms(self):
        for term in (*vocabulary.AFFIRMATIONS, *vocabulary.CORRECTION_CUES):
            with self.subTest(term=term):
                self.assertEqual(check_term(term), term)
        self.assertFalse(vocabulary.AFFIRMATIONS & vocabulary.CORRECTION_CUES)

    def test_the_engine_fixture_is_a_valid_definition_file(self):
        with tempfile.TemporaryDirectory() as root:
            files = SampleProductFiles(Path(root))
            files.write(engine_definition())
            loaded = load_definition(files.source, DEFINITION_ID, 1)
        self.assertIn("reassign_contact", loaded.definition.actions)


class LookupBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.lookup = InMemoryLookup(SampleDesk(), frozenset({"ACC-1"}))

    def test_the_fixture_satisfies_the_protocol(self):
        self.assertIsInstance(self.lookup, RecordLookup)

    def test_hidden_records_look_exactly_like_missing_ones(self):
        self.assertIsNotNone(self.lookup.get("contact", "CON-1"))
        self.assertEqual(self.lookup.get("contact", "CON-3"), self.lookup.get("contact", "CON-404"))
        self.assertEqual(self.lookup.search("contact", "Fay", 5), self.lookup.search("contact", "Nobody", 5))
        self.assertEqual(self.lookup.by_person("contact", "cara-singh", 5), [])
        self.assertEqual(self.lookup.count("contact"), 2)
        self.assertIsNone(self.lookup.get("agent", "cara-singh"))

    def test_hidden_people_look_exactly_like_unknown_people(self):
        self.assertEqual(self.lookup.people("Lopez", 3).unique.id, "ana-lopez")
        self.assertEqual(self.lookup.people("Ana Lopez", 3).unique.id, "ana-lopez")
        self.assertEqual(self.lookup.people("Cara", 3), self.lookup.people("Priya", 3))
        self.assertIsNone(self.lookup.people("Ana", 3).unique, "several matches are never collapsed to one")
        self.assertEqual(self.lookup.people("a", 3).matches, (), "people match on whole name parts only")


class InstalledProductsTest(unittest.TestCase):
    def test_packages_are_found_by_definition_id(self):
        self.assertEqual(installed_products.package_for("linear_simplified").definition_id, "linear_simplified")

    def test_unknown_definitions_fail_closed(self):
        with self.assertRaises(installed_products.PackageMissing):
            installed_products.package_for("sample_desk")

    def test_a_definition_is_served_by_one_package(self):
        package = installed_products.ProductPackage(definition_id="sample_desk")
        with self.assertRaises(ValueError):
            installed_products.index_packages([package, package])


if __name__ == "__main__":
    unittest.main()
