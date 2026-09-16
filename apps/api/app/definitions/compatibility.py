"""Classifies the change between two definition versions.

There are only two classes. Changes outside `entities` are always compatible, because live
sessions stay pinned to their own version; entity changes are compatible only when they are
strictly additive, since every version reads and writes the same tenant records.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.definitions.contract import EntitySpec, FieldSpec, ProductDefinition


class ChangeClass(StrEnum):
    ADDITIVE_COMPATIBLE = "additive-compatible"
    BREAKING_REQUIRES_MIGRATION = "breaking-requires-migration"


@dataclass(frozen=True)
class Compatibility:
    change: ChangeClass
    breaking_changes: list[str] = field(default_factory=list)


def classify(previous: ProductDefinition, current: ProductDefinition) -> Compatibility:
    breaking: list[str] = []
    for name, before in previous.entities.items():
        after = current.entities.get(name)
        if after is None:
            breaking.append(f"entity {name} was removed")
        else:
            breaking.extend(_entity_changes(name, before, after))
    # New entities have no existing records, so anything they declare is additive.
    change = ChangeClass.BREAKING_REQUIRES_MIGRATION if breaking else ChangeClass.ADDITIVE_COMPATIBLE
    return Compatibility(change=change, breaking_changes=breaking)


def _entity_changes(entity: str, before: EntitySpec, after: EntitySpec) -> list[str]:
    changes: list[str] = []
    if before.id != after.id:
        changes.append(f"{entity}: ID strategy changed")
    for name, old in before.fields.items():
        new = after.fields.get(name)
        if new is None:
            changes.append(f"{entity}.{name} was removed")
        else:
            changes.extend(f"{entity}.{name}: {reason}" for reason in _field_changes(old, new))
    for name, new in after.fields.items():
        if name not in before.fields and new.required and new.default is None:
            changes.append(f"{entity}.{name} is a new required field without a default")
    return changes


def _field_changes(old: FieldSpec, new: FieldSpec) -> list[str]:
    reasons: list[str] = []
    if old.type != new.type:
        reasons.append(f"type changed from {old.type} to {new.type}")
    if old.target != new.target:
        reasons.append("reference target changed")
    if new.required and not old.required:
        reasons.append("became required")
    if removed := set(old.values) - set(new.values):
        reasons.append(f"enum values removed: {sorted(removed)}")
    if _tightened(old.min, new.min, lower_is_looser=True):
        reasons.append("minimum was tightened")
    if _tightened(old.max, new.max, lower_is_looser=False):
        reasons.append("maximum was tightened")
    return reasons


def _tightened(old: int | None, new: int | None, lower_is_looser: bool) -> bool:
    if new is None:
        return False
    if old is None:
        return True
    return new > old if lower_is_looser else new < old
