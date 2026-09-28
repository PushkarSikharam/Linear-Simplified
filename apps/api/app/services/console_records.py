"""What Pixel knows about itself, as records its own assistant can read.

Somebody asking "how many products do I have" is asking about the application, not about a
product inside it. The things Pixel keeps - the products an organization runs, and the people in
it - live in the platform's own tables, so they are read from there and shown to the engine as
ordinary records. Nothing is copied into a record store: a count that could drift from what the
application actually has would be worse than no count at all.

It is read-only, and bound to one organization when it is built. Nothing here can widen that:
another organization's products are not absent from a filter, they are never loaded.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.db import use_connection
from app.definitions.contract import ProductDefinition
from app.definitions.organizations import OrganizationDirectory
from app.engine.lookup import PeopleMatch, PersonView, RecordView
from app.installed_products import ProductPackage
from app.product_knowledge import ApprovedKnowledge
from app.services.generic_package import DefinitionTranslator, client_action_type

# The entities Pixel's own definition declares, and what each one is read from.
PRODUCT_ENTITY = "product"
MEMBER_ENTITY = "member"
TEAM_ENTITY = "team"


def readable_id(title: str, taken: set[str], fallback: str) -> str:
    """A record identifier somebody could read aloud.

    Pixel's own records are listed back to people by identifier in several answers, so an
    identifier of `user-2f1c...` is not an implementation detail there - it is what somebody is
    told when they ask who is in their organization. A name makes a readable one, and where two
    people share a name the second gets a number rather than the first being renamed.
    """
    base = "-".join("".join(ch for ch in word if ch.isalnum()) for word in title.lower().split())
    base = "-".join(part for part in base.split("-") if part) or fallback
    candidate, suffix = base, 2
    while candidate in taken:
        candidate, suffix = f"{base}-{suffix}", suffix + 1
    taken.add(candidate)
    return candidate


class ConsoleLookup:
    """One organization's view of its own Pixel: the products it runs and the people in it."""

    def __init__(self, definition: ProductDefinition, tenant_id: str, exclude_product: str) -> None:
        self._definition = definition
        self._tenant_id = tenant_id
        # Pixel is not one of somebody's products, so it is not counted among them.
        self._exclude = exclude_product
        self._loaded: dict[str, tuple[RecordView, ...]] | None = None

    def _all(self) -> Mapping[str, tuple[RecordView, ...]]:
        if self._loaded is not None:
            return self._loaded
        loaded: dict[str, tuple[RecordView, ...]] = {
            entity: () for entity in self._definition.entities
        }
        directory = OrganizationDirectory()
        if PRODUCT_ENTITY in self._definition.entities:
            loaded[PRODUCT_ENTITY] = tuple(self._products(directory))
        products = tuple(record.id for record in loaded.get(PRODUCT_ENTITY, ()))
        teams: dict[str, RecordView] = {}
        if TEAM_ENTITY in self._definition.entities:
            teams = self._teams(directory, products)
            loaded[TEAM_ENTITY] = tuple(teams.values())
        if MEMBER_ENTITY in self._definition.entities:
            loaded[MEMBER_ENTITY] = tuple(self._members(products, teams))
        self._loaded = loaded
        return loaded

    def _products(self, directory: OrganizationDirectory) -> list[RecordView]:
        found: list[RecordView] = []
        for binding in directory.active_products():
            if binding.tenant_id != self._tenant_id or binding.product_id == self._exclude:
                continue
            try:
                definition = directory.definitions.load(
                    binding.definition_id, binding.definition_version).definition
                name = definition.identity.product_name
            except Exception:
                # A product whose definition cannot be read is still a product they have.
                name = binding.product_id
            found.append(RecordView(PRODUCT_ENTITY, binding.product_id, name, {
                "state": binding.state,
                "version": binding.definition_version,
                # What the organization said this product is for. Empty for one added before
                # anybody was asked; the screens and the assistant both say so plainly.
                "purpose": binding.purpose or "",
            }))
        return found

    def _teams(self, directory: OrganizationDirectory,
               products: tuple[str, ...]) -> dict[str, RecordView]:
        """The organization's teams, each knowing how many people are in it.

        The count is taken here rather than left to a screen, because "how many people are on
        Mobile" is a question asked of the assistant far more often than it is clicked for.
        """
        people: dict[str, int] = {}
        with use_connection() as connection:
            for row in connection.execute(
                "select team_id, count(*) as people from memberships "
                "where tenant_id = ? and team_id is not null group by team_id",
                (self._tenant_id,),
            ).fetchall():
                people[row["team_id"]] = row["people"]
        taken: set[str] = set()
        found: dict[str, RecordView] = {}
        for team in directory.teams(self._tenant_id):
            if team.state != "active":
                continue
            record_id = readable_id(team.name, taken, team.team_id)
            found[team.team_id] = RecordView(TEAM_ENTITY, record_id, team.name, {
                "people": people.get(team.team_id, 0),
                "products": products,
            })
        return found

    def _members(self, products: tuple[str, ...],
                 teams: Mapping[str, RecordView]) -> list[RecordView]:
        """The people in this organization, called what they are called.

        Their name is what an answer uses, falling back to their address when Pixel was never
        told one. An address is never wrong, only less human - and a list of addresses is what
        this used to be, which reads as a mailing list rather than as colleagues.
        """
        with use_connection() as connection:
            rows = connection.execute(
                "select m.user_id as user_id, m.role as role, m.team_id as team_id, "
                "a.email as email, a.first_name as first_name, a.last_name as last_name "
                "from memberships m left join email_accounts a on a.user_id = m.user_id "
                "where m.tenant_id = ? order by m.user_id", (self._tenant_id,),
            ).fetchall()
        taken: set[str] = set()
        found: list[RecordView] = []
        for row in rows:
            name = " ".join(part for part in (row["first_name"], row["last_name"]) if part)
            title = name or row["email"] or row["user_id"]
            team = teams.get(row["team_id"]) if row["team_id"] else None
            found.append(RecordView(MEMBER_ENTITY, readable_id(title, taken, row["user_id"]), title, {
                "role": row["role"],
                "team": team.id if team is not None else "",
                "products": products,
            }))
        return found

    # --- RecordLookup ---

    def get(self, entity: str, record_id: str) -> RecordView | None:
        wanted = record_id.lower()
        return next((r for r in self._all().get(entity, ()) if r.id.lower() == wanted), None)

    def search(self, entity: str, text: str, limit: int) -> list[RecordView]:
        needle = text.lower().strip()
        if not needle:
            return []
        return [r for r in self._all().get(entity, ()) if needle in r.title.lower()][:limit]

    def by_person(self, entity: str, person_id: str, limit: int) -> list[RecordView]:
        return []

    def people(self, text: str, limit: int) -> PeopleMatch:
        wanted = text.lower().split()
        if not wanted:
            return PeopleMatch()
        matches = tuple(
            PersonView(r.id, r.title) for r in self._all().get(MEMBER_ENTITY, ())
            if r.title.lower().split() == wanted
            or (len(wanted) == 1 and wanted[0] in r.title.lower().split())
        )
        return PeopleMatch(matches[:limit])

    def count(self, entity: str) -> int:
        return len(self._all().get(entity, ()))

    # --- snapshot source ---

    @property
    def scope_label(self) -> str:
        return self._definition.identity.product_name

    def records_from(self, data: Mapping[str, Any]) -> Mapping[str, tuple[RecordView, ...]]:
        """Pixel's own records. `data` belongs to a product inside it and is not read here."""
        return self._all()

    def materialize(self, connection) -> Mapping[str, tuple[RecordView, ...]]:
        return self._all()


class ConsoleKnowledge(ApprovedKnowledge):
    """Pixel's own approved text, and what this organization said each of its products is for.

    Somebody in Pixel asking "what is Northwind Billing for?" is asking about their own product
    while standing outside it, and the sentence that answers them was written on the day they
    added it. It is read from the binding at the moment of the question rather than copied into
    Pixel's own documents: a copy would be one more thing to keep in step, and would say the old
    sentence for as long as nobody noticed.

    Nothing widens what may be read. The passages are built from one organization's own bindings,
    and this object is made for one organization.
    """

    def __init__(self, context, tenant_id: str, exclude_product: str) -> None:
        super().__init__(context)
        self._tenant_id = tenant_id
        self._exclude = exclude_product

    def documents(self):
        found = list(super().documents())
        directory = OrganizationDirectory()
        for binding in directory.active_products():
            if binding.tenant_id != self._tenant_id or binding.product_id == self._exclude:
                continue
            if not binding.purpose:
                continue
            try:
                name = directory.definitions.load(
                    binding.definition_id, binding.definition_version).definition.identity.product_name
            except Exception:  # noqa: BLE001 - a product that cannot be read is still theirs
                name = binding.product_id
            found.append({
                "document_id": f"product:{binding.product_id}",
                "title": f"What the {name} product is for",
                "body": f"{name} is one of your products in Pixel. It is for: {binding.purpose}",
            })
        return found


def console_package(definition: ProductDefinition, tenant_id: str,
                    product_id: str) -> ProductPackage:
    """The package that serves Pixel's own product for one organization."""
    def lookup_for(grant: Any, _store: Any = None) -> ConsoleLookup:
        return ConsoleLookup(definition, tenant_id, product_id)

    return ProductPackage(
        definition_id=definition.definition.definition_id,
        lookup_factory=lookup_for,
        legacy_translator=lambda lookup: DefinitionTranslator(definition, lookup),
        client_action_types=frozenset(client_action_type(key) for key in definition.actions),
        knowledge_factory=lambda context: ConsoleKnowledge(context, tenant_id, product_id),
    )
