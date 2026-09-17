"""Generic actions, their parameter contract and their lifecycle.

A `GenericAction` names an action declared by the pinned definition. Its capability is always
derived from that declaration; it is never accepted from a model or a request. The parameter
rules below are the normative table in the 3.2 plan, section 4.2. Value checks (field specs,
record visibility) belong to the validator, which also re-checks everything here.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from app.definitions.contract import ActionSpec, ProductDefinition
from app.definitions.vocabulary import MUTATING_CAPABILITIES, Capability


class Param(StrEnum):
    VIEW = "view"
    CONTROL = "control"
    TARGET = "target"
    FILTER = "filter"
    FIELDS = "fields"
    PREFILL = "prefill"


@dataclass(frozen=True)
class ParameterRule:
    required: frozenset[Param]
    optional: frozenset[Param] = frozenset()

    @property
    def forbidden(self) -> frozenset[Param]:
        return frozenset(Param) - self.required - self.optional


PARAMETER_RULES: Mapping[Capability, ParameterRule] = MappingProxyType({
    Capability.NAVIGATE_VIEW: ParameterRule(frozenset({Param.VIEW})),
    Capability.OPEN_RECORD: ParameterRule(frozenset({Param.TARGET})),
    Capability.FILTER_RECORDS: ParameterRule(frozenset({Param.FILTER})),
    Capability.CREATE_RECORD: ParameterRule(frozenset({Param.FIELDS})),
    Capability.UPDATE_RECORD: ParameterRule(frozenset({Param.TARGET, Param.FIELDS})),
    Capability.HIGHLIGHT_CONTROL: ParameterRule(
        frozenset({Param.VIEW, Param.CONTROL}), frozenset({Param.TARGET, Param.PREFILL})
    ),
})


def frozen_value(value: Any) -> Any:
    """A deep, immutable snapshot, so a stored action cannot change after it was validated."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: frozen_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(frozen_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(frozen_value(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"action values must be plain data, not {type(value).__name__}")


class UnknownAction(LookupError):
    """The action key is not declared by the pinned definition."""


@dataclass(frozen=True)
class RecordRef:
    entity: str
    id: str


@dataclass(frozen=True)
class FilterParam:
    field: str
    value: Any

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", frozen_value(self.value))


@dataclass(frozen=True)
class GenericAction:
    action_key: str
    capability: Capability
    view: str | None = None
    control: str | None = None
    target: RecordRef | None = None
    filter: FilterParam | None = None
    # None means absent. An explicitly supplied mapping is present even when it is empty.
    fields: Mapping[str, Any] | None = None
    prefill: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        for name in ("fields", "prefill"):
            value = getattr(self, name)
            if value is not None:
                if not isinstance(value, Mapping):
                    raise TypeError(f"{name} must be a mapping")
                object.__setattr__(self, name, frozen_value(value))

    @classmethod
    def for_definition(cls, definition: ProductDefinition, action_key: str, **params: Any) -> "GenericAction":
        """Build an action whose capability comes from the definition, never from the caller."""
        if "capability" in params:
            raise TypeError("capability is derived from the action key and cannot be supplied")
        spec = definition.actions.get(action_key)
        if spec is None:
            raise UnknownAction(action_key)
        return cls(action_key=action_key, capability=spec.capability, **params)

    def present_params(self) -> frozenset[Param]:
        present = {
            Param.VIEW: self.view is not None,
            Param.CONTROL: self.control is not None,
            Param.TARGET: self.target is not None,
            Param.FILTER: self.filter is not None,
            Param.FIELDS: self.fields is not None,
            Param.PREFILL: self.prefill is not None,
        }
        return frozenset(param for param, is_present in present.items() if is_present)


def shape_errors(action: GenericAction, definition: ProductDefinition) -> list[str]:
    """Structural problems with an action, before any value or visibility check."""
    spec = definition.actions.get(action.action_key)
    if spec is None:
        return [f"unknown action {action.action_key}"]
    errors: list[str] = []
    if action.capability != spec.capability:
        errors.append(f"capability {action.capability} does not match {action.action_key}")
        return errors
    rule = PARAMETER_RULES[spec.capability]
    present = action.present_params()
    errors.extend(f"missing parameter {param}" for param in sorted(rule.required - present))
    errors.extend(f"forbidden parameter {param}" for param in sorted(present & rule.forbidden))
    errors.extend(_declared_value_errors(action, spec))
    return errors


def _declared_value_errors(action: GenericAction, spec: ActionSpec) -> list[str]:
    """Parameters that must equal, or stay inside, what the action declares."""
    errors: list[str] = []
    if action.view is not None and spec.view is not None and action.view != spec.view:
        errors.append(f"view must be {spec.view}")
    if action.control is not None and action.control != spec.control:
        errors.append(f"control must be {spec.control}")
    if action.target is not None and action.target.entity != spec.entity:
        errors.append(f"target must be a {spec.entity} record")
    if action.filter is not None and action.filter.field != spec.by:
        errors.append(f"filter field must be {spec.by}")
    if undeclared := set(action.fields or {}) - set(spec.fields):
        errors.append(f"fields not allowed: {', '.join(sorted(undeclared))}")
    if action.capability in MUTATING_CAPABILITIES and action.fields is not None and not action.fields:
        errors.append("a create or update needs at least one field")
    if action.capability == Capability.HIGHLIGHT_CONTROL:
        if spec.record and action.target is None:
            errors.append("this highlight needs a target record")
        if not spec.record and action.target is not None:
            errors.append("this highlight does not take a target record")
        if undeclared_prefill := set(action.prefill or {}) - set(spec.prefill):
            errors.append(f"prefill not allowed: {', '.join(sorted(undeclared_prefill))}")
    return errors


class ConfirmationReason(StrEnum):
    DEFINITION = "definition"
    CORRECTION = "correction"


def confirmation_reason(spec: ActionSpec, *, target_from_correction: bool) -> ConfirmationReason | None:
    """requires_confirmation = action.confirm OR correction_requires_confirmation (plan, 4.3)."""
    if spec.confirm:
        return ConfirmationReason.DEFINITION
    if target_from_correction and spec.capability in MUTATING_CAPABILITIES:
        return ConfirmationReason.CORRECTION
    return None


class ActionState(StrEnum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    DISPATCHED = "dispatched"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Committed outcomes are final: nothing may relabel or re-execute them.
ACTION_TRANSITIONS: Mapping[ActionState, frozenset[ActionState]] = MappingProxyType({
    ActionState.PROPOSED: frozenset({ActionState.VALIDATED}),
    ActionState.VALIDATED: frozenset({ActionState.AWAITING_CONFIRMATION, ActionState.DISPATCHED}),
    ActionState.AWAITING_CONFIRMATION: frozenset({ActionState.DISPATCHED, ActionState.CANCELLED}),
    ActionState.DISPATCHED: frozenset({ActionState.EXECUTED, ActionState.FAILED, ActionState.CANCELLED}),
    ActionState.EXECUTED: frozenset(),
    ActionState.FAILED: frozenset(),
    ActionState.CANCELLED: frozenset(),
})


def can_transition(current: ActionState, target: ActionState) -> bool:
    return target in ACTION_TRANSITIONS[current]
