"""Parameter provenance for model-proposed mutations (3.2 plan, section 8.3).

A model may **suggest** values. It may never say where they came from. So for every parameter of
a mutation the model proposed, the platform establishes the source itself, from exactly five:

| Class | Meaning |
| --- | --- |
| `USER_EXPLICIT` | present in the visitor's current message |
| `USER_RESOLVED` | resolved by the scope-bound snapshot from something the visitor named |
| `PENDING_STATE` | carried from a prior clarification and re-resolved this turn |
| `DEFINITION_DEFAULT` | supplied by the pinned definition |
| `DEFINITION_MAPPING` | a deterministic vocabulary mapping, such as "urgent" to `High` |

A value does not have to appear literally in the message: "open Dana's record" never says the
record's ID, and that request is perfectly legitimate. What matters is that the platform can
attribute the value to one of these sources without taking the model's word for it.

**This is a data check, not an intent check.** It cannot show the visitor wanted the operation
performed, and it is not the injection defence on its own. An instruction hidden in a record can
still name values the visitor happened to supply, and it would pass here. What stops it is the
confirmation in section 8.4: the worst an injection achieves is an unwanted confirmation prompt
naming an exact target and change.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from app.definitions.contract import EntitySpec, ProductDefinition
from app.engine.actions import RecordRef
from app.engine.mentions import record_ids
from app.engine.normalizer import NormalizedMessage, contains_term
from app.engine.snapshot import TurnSnapshot


class Provenance(StrEnum):
    USER_EXPLICIT = "user_explicit"
    USER_RESOLVED = "user_resolved"
    PENDING_STATE = "pending_state"
    DEFINITION_DEFAULT = "definition_default"
    DEFINITION_MAPPING = "definition_mapping"


@dataclass(frozen=True)
class Unattributable:
    """One parameter the platform cannot trace to a source. The mutation is refused."""

    parameter: str
    detail: str


@dataclass(frozen=True)
class Attributed:
    """Every parameter traced, with the class each one came from."""

    sources: Mapping[str, Provenance]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))

    def of(self, parameter: str) -> Provenance | None:
        return self.sources.get(parameter)


def same_value(left: Any, right: Any) -> bool:
    """Exact comparison: `False` is not `0`, and `1` is not `True`.

    Python's `==` treats booleans as integers, which would let a declared default of `False`
    attribute a model-supplied `0`, or the other way round. Provenance decides whether a change
    is authorized, so it compares JSON types as well as values.
    """
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(same_value(a, b) for a, b in zip(left, right))
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(same_value(left[k], right[k]) for k in left)
    if isinstance(left, (list, tuple, Mapping)) or isinstance(right, (list, tuple, Mapping)):
        return False
    return type(left) is type(right) and left == right


@dataclass(frozen=True)
class TurnEvidence:
    """What the platform itself knows this turn, independent of anything the model said."""

    message: NormalizedMessage
    snapshot: TurnSnapshot
    # Records and people the visitor named, as the router resolved them.
    resolved_records: tuple[RecordRef, ...] = ()
    resolved_people: tuple[str, ...] = ()
    # Values carried in from a pending clarification, already re-resolved this turn.
    pending_target: RecordRef | None = None
    pending_fields: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        from app.engine.actions import frozen_value

        # Boundary data: what the platform knows cannot be edited while a turn is being decided.
        object.__setattr__(self, "resolved_records", tuple(self.resolved_records))
        object.__setattr__(self, "resolved_people", tuple(self.resolved_people))
        object.__setattr__(self, "pending_fields", frozen_value(self.pending_fields or {}))


class ProvenanceChecker:
    """Establishes where each value came from, using only what the platform can verify."""

    def __init__(self, definition: ProductDefinition) -> None:
        self._definition = definition

    def check_target(self, target: RecordRef | None, evidence: TurnEvidence) -> Provenance | Unattributable:
        if target is None:
            return Unattributable("target", "a mutation needs a target record")
        if evidence.pending_target == target:
            return Provenance.PENDING_STATE
        if target in evidence.resolved_records:
            # The router resolved it from what the visitor named.
            return Provenance.USER_RESOLVED
        if target.id.upper() in record_ids(evidence.message.focused_words):
            # The corrected clause decides: a record the visitor retracted is not attributable.
            return Provenance.USER_EXPLICIT
        return Unattributable("target", f"{target.id} was not asked for this turn")

    def check_fields(
        self, entity_key: str | None, fields: Mapping[str, Any], evidence: TurnEvidence,
        *, creating: bool = False,
    ) -> Attributed | Unattributable:
        """`creating` allows `DEFINITION_DEFAULT`, which only applies where the platform fills in."""
        entity = self._definition.entities.get(entity_key or "")
        sources: dict[str, Provenance] = {}
        for name, value in fields.items():
            outcome = self._check_field(entity, name, value, evidence, creating=creating)
            if isinstance(outcome, Unattributable):
                return outcome
            sources[name] = outcome
        return Attributed(sources)

    def _check_field(
        self, entity: EntitySpec | None, name: str, value: Any, evidence: TurnEvidence,
        *, creating: bool = False,
    ) -> Provenance | Unattributable:
        if name in evidence.pending_fields and same_value(evidence.pending_fields[name], value):
            return Provenance.PENDING_STATE

        spec = entity.fields.get(name) if entity is not None else None
        if creating and spec is not None and spec.default is not None and same_value(value, spec.default):
            # A default is something the platform supplies, which only happens on a create.
            return Provenance.DEFINITION_DEFAULT

        if spec is not None and spec.is_reference:
            return self._check_reference(spec, name, value, evidence)

        text = str(value)
        if contains_term(evidence.message.focused, text.lower()):
            return Provenance.USER_EXPLICIT

        if spec is not None and spec.type == "enum" and value in (spec.values or ()):
            if self._mapped_from_vocabulary(text, evidence):
                # "urgent" -> High: the definition's own synonyms did the work.
                return Provenance.DEFINITION_MAPPING
            return Unattributable(name, f"{value!r} was not asked for and maps from nothing said")

        return Unattributable(name, f"{value!r} appears nowhere the visitor spoke")

    def _check_reference(self, spec, name: str, value: Any, evidence: TurnEvidence):
        """Every item independently. One unattributable reference refuses the whole field."""
        ids = tuple(value) if isinstance(value, (tuple, list)) else (value,)
        if not ids:
            return Unattributable(name, "no reference given")
        found: list[Provenance] = []
        for item in ids:
            outcome = self._check_one_reference(spec, name, item, evidence)
            if isinstance(outcome, Unattributable):
                return outcome
            found.append(outcome)
        # Resolution is the weaker claim, so it wins when the items disagree.
        return Provenance.USER_RESOLVED if Provenance.USER_RESOLVED in found else found[0]

    def _check_one_reference(self, spec, name: str, item: Any, evidence: TurnEvidence):
        if not isinstance(item, str) or not item:
            return Unattributable(name, "a reference must be a record ID")
        if item in evidence.resolved_people:
            return Provenance.USER_RESOLVED
        record = evidence.snapshot.get(spec.target or "", item)
        if record is None:
            # Hidden and nonexistent are the same answer.
            return Unattributable(name, f"{item!r} is not a visible {spec.target}")
        if contains_term(evidence.message.focused, record.title.lower()):
            # The visitor named them; the snapshot resolved them to an ID.
            return Provenance.USER_RESOLVED
        if contains_term(evidence.message.focused, item.lower()):
            return Provenance.USER_EXPLICIT
        return Unattributable(name, f"{record.title} was not named this turn")

    def _mapped_from_vocabulary(self, value: str, evidence: TurnEvidence) -> bool:
        """True when a synonym the definition declares for this value was actually said."""
        synonyms = self._definition.vocabulary.synonyms
        for term, alternatives in synonyms.items():
            if term.lower() != value.lower():
                continue
            if any(contains_term(evidence.message.focused, word.lower()) for word in alternatives):
                return True
        # A synonym list may also point the other way: "urgent" -> ["high"].
        for term, alternatives in synonyms.items():
            if value.lower() in {word.lower() for word in alternatives} and \
                    contains_term(evidence.message.focused, term.lower()):
                return True
        return False
