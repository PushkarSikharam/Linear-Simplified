"""Routing stages and results (3.2 plan, section 3).

`ROUTING_STAGES` is the normative precedence; the router evaluates stages in exactly this order
and stops at the first that decides.

A routing result is only a proposal. It is not validated, authorized, dispatchable or executed;
the action-contract validator (slice 3) decides that.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from app.engine.actions import ConfirmationReason, GenericAction, RecordRef


class RouteStage(StrEnum):
    PLATFORM_GATES = "platform_gates"
    REFUSALS = "refusals"
    PENDING_CONFIRMATION = "pending_confirmation"
    PENDING_CLARIFICATION = "pending_clarification"
    EXACT_PHRASES = "exact_phrases"
    INTENT_GROUPS = "intent_groups"
    REQUIREMENTS = "requirements"
    CLARIFICATION_RULES = "clarification_rules"
    MODEL = "model"
    FALLBACK = "fallback"


ROUTING_STAGES: tuple[RouteStage, ...] = tuple(RouteStage)


class RouteKind(StrEnum):
    PROPOSE = "propose"  # a proposed action, still to be validated
    CONFIRM = "confirm"  # a proposed action that needs an explicit yes before it may be dispatched
    CLARIFY = "clarify"  # a question; nothing happens yet
    ANSWER = "answer"  # a reply without an action
    REFUSE = "refuse"  # a guardrail refusal
    CANCELLED = "cancelled"  # a pending confirmation was declined
    FALLBACK = "fallback"


@dataclass(frozen=True)
class RouteResult:
    kind: RouteKind
    stage: RouteStage
    response_key: str | None
    proposal: GenericAction | None = None
    confirmation_reason: ConfirmationReason | None = None
    # The visitor explicitly confirmed this proposal on this turn.
    confirmed: bool = False
    # A pending confirmation was cancelled on this turn before the message was routed.
    cancelled_confirmation: bool = False
    topic: str | None = None
    # The visible person the proposal is about, if any.
    person: RecordRef | None = None
    placeholders: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        needs_proposal = self.kind in {RouteKind.PROPOSE, RouteKind.CONFIRM}
        if needs_proposal != (self.proposal is not None):
            raise ValueError(f"{self.kind} results {'need' if needs_proposal else 'cannot carry'} a proposal")
        if (self.kind == RouteKind.CONFIRM) != (self.confirmation_reason is not None):
            raise ValueError("only confirmation results carry a confirmation reason")
        if self.confirmed and self.kind != RouteKind.PROPOSE:
            raise ValueError("only a proposal can be confirmed")
        if (self.kind == RouteKind.REFUSE) != (self.topic is not None):
            raise ValueError("refusals, and only refusals, name a topic")
        object.__setattr__(self, "placeholders", MappingProxyType(dict(self.placeholders)))
