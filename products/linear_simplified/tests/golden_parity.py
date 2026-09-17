"""Exact comparison of golden recordings, with individually reviewed differences.

A recording is evidence, never a target: it is not regenerated to make a test pass. Every
field that differs must be listed in the reviewed-differences file with its kind and reason,
and a listed difference that no longer occurs is also a failure.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KINDS = frozenset({"wording", "behaviour", "security"})
ENTRY_KEYS = frozenset({"case", "turn", "field", "recorded", "current", "kind", "reason"})
# Pseudo-fields for structural differences.
CASE_PRESENCE = "__case__"
TURN_COUNT = "__turns__"
# Stands for a field that is absent, which is different from a field whose value is null.
MISSING = {"__missing__": True}


@dataclass(frozen=True)
class Difference:
    case: str
    turn: int
    field: str
    recorded: Any
    current: Any


@dataclass(frozen=True)
class ReviewedDifference:
    case: str
    turn: int
    field: str
    recorded: Any
    current: Any
    kind: str
    reason: str

    @property
    def location(self) -> tuple[str, int, str]:
        return self.case, self.turn, self.field


@dataclass(frozen=True)
class ParityReport:
    unlisted: tuple[Difference, ...]
    stale: tuple[ReviewedDifference, ...]
    mismatched: tuple[tuple[ReviewedDifference, Difference], ...]

    @property
    def clean(self) -> bool:
        return not (self.unlisted or self.stale or self.mismatched)

    def describe(self) -> str:
        lines = [f"unlisted {d.case}[{d.turn}].{d.field}: {d.recorded!r} -> {d.current!r}" for d in self.unlisted]
        lines += [f"stale {r.case}[{r.turn}].{r.field}: listed but no longer different" for r in self.stale]
        lines += [
            f"mismatched {r.case}[{r.turn}].{r.field}: listed {r.recorded!r} -> {r.current!r}, "
            f"actual {d.recorded!r} -> {d.current!r}"
            for r, d in self.mismatched
        ]
        return "\n".join(lines)


def differences(recorded: dict[str, list[dict]], current: dict[str, list[dict]]) -> list[Difference]:
    found: list[Difference] = []
    for case in sorted(set(recorded) | set(current)):
        if case not in recorded or case not in current:
            found.append(Difference(case, 0, CASE_PRESENCE, case in recorded, case in current))
            continue
        before, after = recorded[case], current[case]
        if len(before) != len(after):
            found.append(Difference(case, 0, TURN_COUNT, len(before), len(after)))
        for turn, (old, new) in enumerate(zip(before, after)):
            for field in sorted(set(old) | set(new)):
                before_value = old[field] if field in old else MISSING
                after_value = new[field] if field in new else MISSING
                if (field in old) != (field in new) or not same_value(before_value, after_value):
                    found.append(Difference(case, turn, field, before_value, after_value))
    return found


def same_value(left: Any, right: Any) -> bool:
    """Exact JSON equality: `true`, `1` and `1.0` are different values."""
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def load_reviewed(path: Path) -> list[ReviewedDifference]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("reviewed differences must be a list")
    reviewed: list[ReviewedDifference] = []
    seen: set[tuple[str, int, str]] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise ValueError(f"entry {index} must have exactly the keys {sorted(ENTRY_KEYS)}")
        if entry["kind"] not in KINDS:
            raise ValueError(f"entry {index} has unknown kind {entry['kind']!r}")
        if not isinstance(entry["reason"], str) or len(entry["reason"].strip()) < 20:
            raise ValueError(f"entry {index} needs a real reason")
        item = ReviewedDifference(**entry)
        if item.location in seen:
            raise ValueError(f"entry {index} repeats {item.location}")
        seen.add(item.location)
        reviewed.append(item)
    return reviewed


def compare(recorded: dict, current: dict, reviewed: list[ReviewedDifference]) -> ParityReport:
    found = {(d.case, d.turn, d.field): d for d in differences(recorded, current)}
    listed = {r.location: r for r in reviewed}
    unlisted = tuple(d for location, d in found.items() if location not in listed)
    stale = tuple(r for location, r in listed.items() if location not in found)
    mismatched = tuple(
        (r, found[location]) for location, r in listed.items()
        if location in found and not (
            same_value(found[location].recorded, r.recorded) and same_value(found[location].current, r.current)
        )
    )
    return ParityReport(unlisted, stale, mismatched)
