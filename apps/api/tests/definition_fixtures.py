"""A neutral sample product for testing the definition platform without any real product."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from app.definitions.loader import DefinitionSource

DEFINITION_ID = "sample_desk"


def sample_definition(version: int = 1, owner_organization: str | None = None) -> dict:
    """Accounts own contacts; notes belong to contacts (two hops from their account).

    Platform-shared by default; naming an owner makes it private to that organization.
    """
    identity = {
        "definition_id": DEFINITION_ID,
        "version": version,
        "ownership": "organization_private" if owner_organization else "platform_shared",
    }
    if owner_organization:
        identity["owner_organization"] = owner_organization
    return copy.deepcopy({
        "definition": identity,
        "identity": {
            "product_name": "Sample Desk",
            "assistant_name": "Guide",
            "persona": "A concise guide for the sample desk.",
            "voice_style": "Calm and clear.",
            "greeting": "Welcome to {product}. I'm {assistant}.",
        },
        "vocabulary": {"terms": ["account", "contact", "note"], "corrections": {"acount": "account"}},
        "entities": {
            "account": {
                "label": "Account", "plural": "Accounts",
                "id": {"strategy": "prefix", "prefix": "ACC"},
                "title_field": "name",
                "fields": {
                    "name": {"type": "text", "required": True, "max": 100},
                    "tier": {"type": "enum", "values": ["Free", "Pro"], "required": True},
                },
            },
            "agent": {
                "label": "Agent", "plural": "Agents",
                "id": {"strategy": "slug", "from_field": "name"},
                "title_field": "name",
                "fields": {
                    "name": {"type": "text", "required": True, "editable": False},
                    "accounts": {"type": "refs", "target": "account"},
                },
            },
            "contact": {
                "label": "Contact", "plural": "Contacts",
                "id": {"strategy": "prefix", "prefix": "CON"},
                "title_field": "name",
                "fields": {
                    "name": {"type": "text", "required": True, "max": 100},
                    "account": {"type": "ref", "target": "account", "required": True},
                    "owner": {"type": "ref", "target": "agent"},
                    "status": {"type": "enum", "values": ["Open", "Closed"]},
                },
            },
            "note": {
                "label": "Note", "plural": "Notes",
                "id": {"strategy": "prefix", "prefix": "NOTE"},
                "title_field": "body",
                "fields": {
                    "body": {"type": "text", "required": True, "max": 1000},
                    "contact": {"type": "ref", "target": "contact", "required": True},
                },
            },
        },
        "people": {"entity": "agent", "assigned_by": ["contact.owner"], "match_on": ["name"]},
        "scope": {
            "anchor": "account",
            "paths": {"account": [], "agent": ["accounts"], "contact": ["account"], "note": ["contact", "account"]},
        },
        "views": {
            "home": {"label": "Home", "kind": "dashboard"},
            "contacts": {
                "label": "Contacts", "kind": "list", "entity": "contact", "columns": ["name", "status"],
                "controls": {"new_contact": {"label": "New contact"}},
            },
            "contact_detail": {
                "label": "Contact", "kind": "detail", "entity": "contact", "navigable": False,
                "controls": {"owner_field": {"label": "Owner"}},
            },
            "channels": {"label": "Channels", "kind": "adapter", "controls": {"mail_card": {"label": "Mail"}}},
        },
        "actions": {
            "open_contacts": {"capability": "NAVIGATE_VIEW", "view": "contacts", "description": "Open contacts."},
            "open_architecture": {"capability": "NAVIGATE_VIEW", "view": "architecture", "description": "Open it."},
            "open_contact": {"capability": "OPEN_RECORD", "entity": "contact", "description": "Open a contact."},
            "contacts_by_owner": {
                "capability": "FILTER_RECORDS", "entity": "contact", "by": "owner", "description": "Filter.",
            },
            "create_contact": {
                "capability": "CREATE_RECORD", "entity": "contact", "fields": ["name", "account"],
                "description": "Create a contact.",
            },
            "update_contact": {
                "capability": "UPDATE_RECORD", "entity": "contact", "fields": ["status", "owner"],
                "confirm": True, "description": "Update a contact.",
            },
            "highlight_owner": {
                "capability": "HIGHLIGHT_CONTROL", "view": "contact_detail", "control": "owner_field",
                "entity": "contact", "record": True, "description": "Show the owner field.",
            },
            "highlight_mail": {
                "capability": "HIGHLIGHT_CONTROL", "view": "channels", "control": "mail_card",
                "description": "Show the mail channel.",
            },
        },
        "intents": [
            {"action": "open_contacts", "match": [["contact", "contacts"]], "response": "view_opened"},
            {"action": "contacts_by_owner", "requires": ["person"], "match": [["owned by", "for"]]},
        ],
        "clarifications": [{"response": "clarify_create", "match": [["create", "new"]], "exclude": ["contact"]}],
        "guardrails": [{"topic": "external_billing", "response": "out_of_scope", "match": [["invoice"]]}],
        "responses": {
            "view_opened": "I'll open {view}.",
            "clarify_create": "What should I create?",
            "out_of_scope": "I can only help with {product} here.",
        },
        "knowledge_topics": {"contacts": ["contact", "contacts"]},
        "reasoning_hints": ["Contact questions map to open_contacts."],
    })


def adapter_manifest() -> dict:
    return {"definition_id": DEFINITION_ID, "views": {"channels": {"controls": ["mail_card"]}}}


class SampleProductFiles:
    """Writes sample definition files and the adapter manifest under a temporary root."""

    def __init__(self, root: Path) -> None:
        self.source = DefinitionSource(products_root=root / "products", adapters_root=root / "adapters")
        self.write_manifest(adapter_manifest())

    def write(self, document: dict | str, version: int = 1, definition_id: str = DEFINITION_ID) -> Path:
        path = self.source.definition_path(definition_id, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = document if isinstance(document, str) else yaml.safe_dump(document, sort_keys=False)
        path.write_text(text, encoding="utf-8")
        return path

    def write_manifest(self, manifest: dict | None, definition_id: str = DEFINITION_ID) -> None:
        path = self.source.manifest_path(definition_id)
        if manifest is None:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")
