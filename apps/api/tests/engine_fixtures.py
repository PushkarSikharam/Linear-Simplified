"""A neutral, non-project-management product for engine tests.

The sample desk (accounts, contacts, notes) from `definition_fixtures` is extended with a
confirm-free mutation, so both confirmation reasons can be tested. `InMemoryLookup` is a
scope-bound record lookup: records outside the caller's accounts behave as if they did not
exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.definitions.contract import ProductDefinition
from app.engine.lookup import PeopleMatch, PersonView, RecordView
from definition_fixtures import sample_definition


def engine_definition(version: int = 1) -> dict:
    document = sample_definition(version)
    document["actions"]["reassign_contact"] = {
        "capability": "UPDATE_RECORD", "entity": "contact", "fields": ["owner"],
        "description": "Give a contact to another agent.",
    }
    document["intents"].append({
        "action": "reassign_contact", "requires": ["person"],
        "match": [["reassign", "give"]], "response": "record_update_proposed",
    })
    document["responses"].update({
        "record_update_proposed": "I'll update {record_id}: {changes}.",
        "confirm_action": "Should I go ahead and update {record_id}?",
        "action_cancelled": "Okay, I won't change anything.",
    })
    return document


def load_engine_definition(version: int = 1) -> ProductDefinition:
    return ProductDefinition.model_validate(engine_definition(version))


@dataclass
class SampleDesk:
    """Two accounts; the caller may see only ACC-1 and what belongs to it."""

    accounts: dict[str, RecordView] = field(default_factory=lambda: {
        "ACC-1": RecordView("account", "ACC-1", "Northwind", {"tier": "Pro"}),
        "ACC-2": RecordView("account", "ACC-2", "Contoso", {"tier": "Free"}),
    })
    agents: dict[str, tuple[str, str]] = field(default_factory=lambda: {
        # agent id -> (name, account id)
        "ana-lopez": ("Ana Lopez", "ACC-1"),
        "ben-okafor": ("Ben Okafor", "ACC-1"),
        "cara-singh": ("Cara Singh", "ACC-2"),
    })
    contacts: dict[str, tuple[RecordView, str]] = field(default_factory=lambda: {
        "CON-1": (RecordView("contact", "CON-1", "Dana Reyes", {"owner": "ana-lopez", "status": "Open"}), "ACC-1"),
        "CON-2": (RecordView("contact", "CON-2", "Eli Moss", {"owner": "ben-okafor", "status": "Open"}), "ACC-1"),
        "CON-3": (RecordView("contact", "CON-3", "Fay Chu", {"owner": "cara-singh", "status": "Closed"}), "ACC-2"),
    })


class InMemoryLookup:
    def __init__(self, desk: SampleDesk, visible_accounts: frozenset[str]) -> None:
        self._desk = desk
        self._visible = visible_accounts

    def _records(self, entity: str) -> list[RecordView]:
        if entity == "account":
            return [record for key, record in self._desk.accounts.items() if key in self._visible]
        if entity == "contact":
            return [record for record, account in self._desk.contacts.values() if account in self._visible]
        return []

    def get(self, entity: str, record_id: str) -> RecordView | None:
        return next((record for record in self._records(entity) if record.id == record_id), None)

    def search(self, entity: str, text: str, limit: int) -> list[RecordView]:
        needle = text.lower()
        return [record for record in self._records(entity) if needle in record.title.lower()][:limit]

    def by_person(self, entity: str, person_id: str, limit: int) -> list[RecordView]:
        return [record for record in self._records(entity) if record.fields.get("owner") == person_id][:limit]

    def people(self, text: str, limit: int) -> PeopleMatch:
        needle = text.lower()
        matches = tuple(
            PersonView(agent_id, name)
            for agent_id, (name, account) in self._desk.agents.items()
            if account in self._visible and needle in name.lower()
        )
        return PeopleMatch(matches[:limit])

    def count(self, entity: str) -> int:
        return len(self._records(entity))
