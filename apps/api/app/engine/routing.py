"""Routing stages and results (3.2 plan, section 3).

`ROUTING_STAGES` is the normative precedence; the router in slice 2 must evaluate stages in
exactly this order and stop at the first that decides.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from app.engine.actions import ConfirmationReason, GenericAction


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
    ACTION = "action"  # a validated action to dispatch
    CONFIRM = "confirm"  # an action waiting for an explicit yes
    CLARIFY = "clarify"  # a question; nothing happens yet
    REFUSE = "refuse"  # a guardrail or platform refusal
    CANCELLED = "cancelled"  # a pending confirmation was declined
    FALLBACK = "fallback"


@dataclass(frozen=True)
class RouteResult:
    kind: RouteKind
    stage: RouteStage
    response_key: str
    action: GenericAction | None = None
    confirmation_reason: ConfirmationReason | None = None
    placeholders: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        needs_action = self.kind in {RouteKind.ACTION, RouteKind.CONFIRM}
        if needs_action != (self.action is not None):
            raise ValueError(f"{self.kind} results {'need' if needs_action else 'cannot carry'} an action")
        if (self.kind == RouteKind.CONFIRM) != (self.confirmation_reason is not None):
            raise ValueError("only confirmation results carry a confirmation reason")
