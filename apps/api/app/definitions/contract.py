"""The Product Definition contract.

Every model rejects unknown fields and type coercion. Cross-references (entities, fields,
views, controls, actions, scope paths) are checked for the definition as a whole, so an
invalid definition is rejected completely and never partially applied.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.definitions.safety import check_key, check_slug, check_template, check_term, check_text, check_value
from app.definitions.vocabulary import (
    MAX_SCOPE_HOPS,
    PLATFORM_VIEWS,
    REFERENCE_FIELD_TYPES,
    RESPONSE_KEYS,
    Capability,
)

IntentRequirement = Literal["person", "record", "selected_record", "unknown_person"]

Key = Annotated[str, AfterValidator(check_key)]
Slug = Annotated[str, AfterValidator(check_slug)]
Term = Annotated[str, AfterValidator(check_term)]
Value = Annotated[str, AfterValidator(check_value)]
Text = Annotated[str, Field(max_length=500), AfterValidator(check_text)]
ShortText = Annotated[str, Field(max_length=80), AfterValidator(check_text)]
Template = Annotated[str, Field(max_length=500), AfterValidator(check_template)]
Terms = Annotated[list[Term], Field(max_length=200)]
Keys = Annotated[list[Key], Field(max_length=60)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class DefinitionIdentity(Strict):
    """Which definition this is and who owns it. Ownership is part of the immutable content."""

    definition_id: Key
    version: int = Field(ge=1, le=100_000)
    ownership: Literal["platform_shared", "organization_private"]
    owner_organization: Slug | None = None

    @model_validator(mode="after")
    def _owner_matches_ownership(self) -> "DefinitionIdentity":
        private = self.ownership == "organization_private"
        if private != (self.owner_organization is not None):
            raise ValueError("organization-private definitions, and only those, name an owner organization")
        return self


class Identity(Strict):
    product_name: ShortText
    assistant_name: ShortText
    persona: Text
    voice_style: Text
    greeting: Template


class Vocabulary(Strict):
    terms: Terms = []
    synonyms: dict[Term, Terms] = Field(default_factory=dict, max_length=200)
    corrections: dict[Term, Term] = Field(default_factory=dict, max_length=300)
    negatable_terms: Terms = []
    correction_markers: Terms = []


FieldType = Literal["text", "integer", "enum", "date", "boolean", "text_list", "ref", "refs"]


class FieldSpec(Strict):
    type: FieldType
    label: ShortText | None = None
    required: bool = False
    editable: bool = True
    display: bool = True
    min: int | None = None
    max: int | None = None
    values: Annotated[list[Value], Field(max_length=50)] = []
    target: Key | None = None
    default: bool | int | Value | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "FieldSpec":
        if self.type == "enum" and not self.values:
            raise ValueError("enum fields need values")
        if self.type != "enum" and self.values:
            raise ValueError("only enum fields may declare values")
        if (self.type in REFERENCE_FIELD_TYPES) != (self.target is not None):
            raise ValueError("reference fields, and only reference fields, need a target")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not exceed max")
        if self.type in {"boolean", "date"} | REFERENCE_FIELD_TYPES and (self.min is not None or self.max is not None):
            raise ValueError(f"{self.type} fields cannot declare bounds")
        return self

    @property
    def is_reference(self) -> bool:
        return self.type in REFERENCE_FIELD_TYPES


class IdSpec(Strict):
    strategy: Literal["prefix", "slug"]
    prefix: Annotated[str, Field(pattern=r"^[A-Z]{2,6}$")] | None = None
    from_field: Key | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "IdSpec":
        if self.strategy == "prefix" and (self.prefix is None or self.from_field is not None):
            raise ValueError("prefix IDs need a prefix and no source field")
        if self.strategy == "slug" and (self.from_field is None or self.prefix is not None):
            raise ValueError("slug IDs need a source field and no prefix")
        return self


class EntitySpec(Strict):
    label: ShortText
    plural: ShortText
    id: IdSpec
    title_field: Key
    summary_fields: Keys = []
    fields: dict[Key, FieldSpec] = Field(min_length=1, max_length=60)


class PeopleSpec(Strict):
    entity: Key
    # "entity.field" pairs whose references assign a person.
    assigned_by: Annotated[list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")]],
                           Field(max_length=20)] = []
    match_on: Keys = Field(min_length=1)


class ScopeSpec(Strict):
    anchor: Key
    # For each entity, the reference fields to follow to reach the anchor. [] means the
    # entity is the anchor itself.
    paths: dict[Key, Annotated[list[Key], Field(max_length=MAX_SCOPE_HOPS)]]


class ControlSpec(Strict):
    label: ShortText


class ViewSpec(Strict):
    label: ShortText
    kind: Literal["dashboard", "list", "detail", "form", "adapter"]
    entity: Key | None = None
    navigable: bool = True
    shortcut: Annotated[str, Field(pattern=r"^[A-Z]$")] | None = None
    columns: Keys = []
    controls: dict[Key, ControlSpec] = Field(default_factory=dict, max_length=40)

    @model_validator(mode="after")
    def _consistent(self) -> "ViewSpec":
        needs_entity = self.kind in {"list", "detail", "form"}
        if needs_entity and self.entity is None:
            raise ValueError(f"{self.kind} views need an entity")
        if not needs_entity and self.columns:
            raise ValueError("only record views may declare columns")
        return self


class ActionSpec(Strict):
    # Non-strict only so YAML strings convert to the enum; values outside it are still rejected.
    capability: Annotated[Capability, Field(strict=False)]
    description: Text
    view: Key | None = None
    entity: Key | None = None
    control: Key | None = None
    record: bool = False
    by: Key | None = None
    fields: Keys = []
    prefill: Keys = []
    confirm: bool = False

    @model_validator(mode="after")
    def _parameters_match_capability(self) -> "ActionSpec":
        allowed = _ACTION_PARAMETERS[self.capability]
        present = {
            name for name in ("view", "entity", "control", "by")
            if getattr(self, name) is not None
        } | {name for name in ("fields", "prefill") if getattr(self, name)} | ({"record"} if self.record else set())
        required = _REQUIRED_ACTION_PARAMETERS[self.capability]
        if missing := required - present:
            raise ValueError(f"{self.capability} needs {', '.join(sorted(missing))}")
        if unexpected := present - allowed:
            raise ValueError(f"{self.capability} does not accept {', '.join(sorted(unexpected))}")
        if self.prefill and self.entity is None:
            raise ValueError("prefill fields need an entity")
        return self


_ACTION_PARAMETERS = {
    Capability.NAVIGATE_VIEW: {"view"},
    Capability.OPEN_RECORD: {"entity"},
    Capability.FILTER_RECORDS: {"entity", "by"},
    Capability.CREATE_RECORD: {"entity", "fields"},
    Capability.UPDATE_RECORD: {"entity", "fields"},
    Capability.HIGHLIGHT_CONTROL: {"view", "control", "entity", "record", "prefill"},
}
_REQUIRED_ACTION_PARAMETERS = {
    Capability.NAVIGATE_VIEW: {"view"},
    Capability.OPEN_RECORD: {"entity"},
    Capability.FILTER_RECORDS: {"entity", "by"},
    Capability.CREATE_RECORD: {"entity", "fields"},
    Capability.UPDATE_RECORD: {"entity", "fields"},
    Capability.HIGHLIGHT_CONTROL: {"view", "control"},
}


class MatchRule(Strict):
    """Literal term matching against the normalized visitor message.

    - `match`: every group must contain at least one term found in the message.
    - `exclude`: no listed term may be found.
    - `exact`: alternatively, the whole message equals one of these phrases.
    """

    match: Annotated[list[Annotated[list[Term], Field(min_length=1, max_length=60)]], Field(max_length=4)] = []
    exclude: Terms = []
    exact: Terms = []

    @model_validator(mode="after")
    def _not_empty(self) -> "MatchRule":
        if not (self.match or self.exact):
            raise ValueError("a rule needs match groups or exact phrases")
        return self


class IntentSpec(MatchRule):
    action: Key
    requires: Annotated[list[IntentRequirement], Field(max_length=4)] = []
    response: Key | None = None
    examples: Annotated[list[Text], Field(max_length=20)] = []


class ClarificationSpec(MatchRule):
    response: Key


class GuardrailSpec(MatchRule):
    topic: Key
    response: Key


class ProspectSignals(Strict):
    roles: dict[Value, Terms] = Field(default_factory=dict, max_length=30)
    current_tools: dict[Value, Terms] = Field(default_factory=dict, max_length=30)
    goals: dict[Value, Terms] = Field(default_factory=dict, max_length=30)
    pain_points: dict[Value, Terms] = Field(default_factory=dict, max_length=30)


class ProductDefinition(Strict):
    definition: DefinitionIdentity
    identity: Identity
    vocabulary: Vocabulary = Vocabulary()
    entities: dict[Key, EntitySpec] = Field(min_length=1, max_length=40)
    people: PeopleSpec | None = None
    scope: ScopeSpec
    views: dict[Key, ViewSpec] = Field(min_length=1, max_length=40)
    actions: dict[Key, ActionSpec] = Field(min_length=1, max_length=100)
    intents: Annotated[list[IntentSpec], Field(max_length=300)] = []
    clarifications: Annotated[list[ClarificationSpec], Field(max_length=100)] = []
    guardrails: Annotated[list[GuardrailSpec], Field(max_length=100)] = []
    responses: dict[Key, Template] = Field(default_factory=dict, max_length=100)
    knowledge_topics: dict[Key, Terms] = Field(default_factory=dict, max_length=40)
    prospect_signals: ProspectSignals = ProspectSignals()
    reasoning_hints: Annotated[list[Text], Field(max_length=30)] = []

    @model_validator(mode="after")
    def _references_resolve(self) -> "ProductDefinition":
        errors: list[str] = []
        self._check_entities(errors)
        self._check_people(errors)
        self._check_scope(errors)
        self._check_views(errors)
        self._check_actions(errors)
        self._check_routing(errors)
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def _field(self, entity: str, field: str) -> FieldSpec | None:
        spec = self.entities.get(entity)
        return spec.fields.get(field) if spec else None

    def _check_entities(self, errors: list[str]) -> None:
        for name, entity in self.entities.items():
            for field_name in [entity.title_field, *entity.summary_fields]:
                if field_name not in entity.fields:
                    errors.append(f"entity {name}: unknown field {field_name}")
            if entity.id.from_field and entity.id.from_field not in entity.fields:
                errors.append(f"entity {name}: ID source field {entity.id.from_field} is not declared")
            for field_name, spec in entity.fields.items():
                if spec.is_reference and spec.target not in self.entities:
                    errors.append(f"entity {name}.{field_name}: unknown target entity {spec.target}")

    def _check_people(self, errors: list[str]) -> None:
        if self.people is None:
            return
        person = self.entities.get(self.people.entity)
        if person is None:
            errors.append(f"people: unknown entity {self.people.entity}")
            return
        errors.extend(
            f"people: {self.people.entity} has no field {field}"
            for field in self.people.match_on if field not in person.fields
        )
        for pair in self.people.assigned_by:
            entity, field = pair.split(".")
            spec = self._field(entity, field)
            if spec is None or not spec.is_reference or spec.target != self.people.entity:
                errors.append(f"people: {pair} must reference {self.people.entity}")

    def _check_scope(self, errors: list[str]) -> None:
        anchor = self.scope.anchor
        if anchor not in self.entities:
            errors.append(f"scope: unknown anchor entity {anchor}")
            return
        if self.scope.paths.get(anchor) != []:
            errors.append(f"scope: the anchor {anchor} must have an empty path")
        for entity in self.entities:
            if entity not in self.scope.paths:
                errors.append(f"scope: entity {entity} has no path to {anchor}")
        for entity, path in self.scope.paths.items():
            if entity not in self.entities:
                errors.append(f"scope: unknown entity {entity}")
                continue
            current = entity
            for hop in path:
                spec = self._field(current, hop)
                if spec is None or not spec.is_reference:
                    errors.append(f"scope: {current}.{hop} is not a reference field")
                    break
                current = spec.target
            else:
                if current != anchor:
                    errors.append(f"scope: path for {entity} ends at {current}, not {anchor}")

    def _check_views(self, errors: list[str]) -> None:
        for name, view in self.views.items():
            if name in PLATFORM_VIEWS:
                errors.append(f"view {name}: name is reserved for the platform")
            if view.entity is not None and view.entity not in self.entities:
                errors.append(f"view {name}: unknown entity {view.entity}")
                continue
            for column in view.columns:
                if self._field(view.entity, column) is None:
                    errors.append(f"view {name}: unknown column {column}")

    def _check_actions(self, errors: list[str]) -> None:
        for name, action in self.actions.items():
            if action.view is not None and action.view not in self.views and action.view not in PLATFORM_VIEWS:
                errors.append(f"action {name}: unknown view {action.view}")
            if action.entity is not None and action.entity not in self.entities:
                errors.append(f"action {name}: unknown entity {action.entity}")
                continue
            view = self.views.get(action.view) if action.view else None
            if action.control is not None and (view is None or action.control not in view.controls):
                errors.append(f"action {name}: view {action.view} has no control {action.control}")
            if action.record and (view is None or view.entity != action.entity or action.entity is None):
                errors.append(f"action {name}: record controls need the entity of view {action.view}")
            for field in [*action.fields, *action.prefill, *([action.by] if action.by else [])]:
                if self._field(action.entity, field) is None:
                    errors.append(f"action {name}: entity {action.entity} has no field {field}")
            if action.capability == Capability.UPDATE_RECORD:
                for field in action.fields:
                    spec = self._field(action.entity, field)
                    if spec is not None and not spec.editable:
                        errors.append(f"action {name}: field {field} is not editable")
            if action.capability == Capability.CREATE_RECORD and action.entity in self.entities:
                for field, spec in self.entities[action.entity].fields.items():
                    if spec.required and field not in action.fields and spec.default is None:
                        errors.append(
                            f"action {name}: required field {field} can neither be set nor defaulted"
                        )

    def _check_routing(self, errors: list[str]) -> None:
        for intent in self.intents:
            if intent.action not in self.actions:
                errors.append(f"intent: unknown action {intent.action}")
            if intent.response is not None:
                self._check_response_key(intent.response, errors)
            if intent.requires and self.people is None and {"person", "unknown_person"} & set(intent.requires):
                errors.append("intent: person matching needs a people section")
        for rule in [*self.clarifications, *self.guardrails]:
            self._check_response_key(rule.response, errors)
        for key in self.responses:
            if key not in RESPONSE_KEYS:
                errors.append(f"responses: unknown response key {key}")

    def _check_response_key(self, key: str, errors: list[str]) -> None:
        if key not in RESPONSE_KEYS:
            errors.append(f"unknown response key {key}")
        elif key not in self.responses:
            errors.append(f"response {key} is referenced but not defined")


class TenantSettings(Strict):
    """Per-product overrides allowed on a product binding. The key set is fixed by the platform."""

    display_name: ShortText | None = None
    assistant_name: ShortText | None = None
    greeting: Template | None = None
