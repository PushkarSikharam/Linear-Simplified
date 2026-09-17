"""The engine's only view of product records (3.2 plan, section 7).

A lookup is read-only and bound to one caller's visible scope when it is built. Callers cannot
widen it. Records and people outside that scope are indistinguishable from ones that do not
exist: no method reports that something is hidden.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RecordView:
    entity: str
    id: str
    title: str
    fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PersonView:
    id: str
    name: str


@dataclass(frozen=True)
class PeopleMatch:
    """Visible people whose names match. Empty means none the caller may see."""

    matches: tuple[PersonView, ...] = ()

    @property
    def unique(self) -> PersonView | None:
        return self.matches[0] if len(self.matches) == 1 else None


@runtime_checkable
class RecordLookup(Protocol):
    def get(self, entity: str, record_id: str) -> RecordView | None: ...

    def search(self, entity: str, text: str, limit: int) -> list[RecordView]: ...

    def by_person(self, entity: str, person_id: str, limit: int) -> list[RecordView]: ...

    def people(self, text: str, limit: int) -> PeopleMatch: ...

    def count(self, entity: str) -> int: ...
