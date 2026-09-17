"""Explicit per-session conversation state (3.2 plan, section 6).

Memory never authorizes anything: every remembered reference is re-resolved through the
session's `RecordLookup` on the turn that uses it.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from app.engine.actions import ConfirmationReason, GenericAction, RecordRef

# A pending question or confirmation is answered on the next turn or not at all.
PENDING_TURNS = 1


@dataclass(frozen=True)
class PendingClarification:
    key: str  # the response key that asked the question
    action_key: str | None  # the action waiting for the answer, if any
    expected: str  # "person", "record" or "choice"
    candidates: tuple[RecordRef, ...] = ()
    rejected: tuple[RecordRef, ...] = ()
    # The one candidate the assistant's last reply named, if it named exactly one.
    singled_out: RecordRef | None = None
    turn: int = 0

    def __post_init__(self) -> None:
        if len(self.candidates) > 3:
            raise ValueError("a clarification offers at most three candidates")
        if self.singled_out is not None and self.singled_out not in self.candidates:
            raise ValueError("the singled-out candidate must be one of the candidates")

    def reject_singled_out(self) -> "PendingClarification":
        """Remove the candidate a correction refers to. Never selects another one."""
        if self.singled_out is None:
            raise ValueError("no candidate was singled out, so a correction cannot remove one")
        remaining = tuple(c for c in self.candidates if c != self.singled_out)
        return replace(self, candidates=remaining, rejected=(*self.rejected, self.singled_out), singled_out=None)


@dataclass(frozen=True)
class PendingConfirmation:
    action: GenericAction
    reason: ConfirmationReason
    turn: int


@dataclass(frozen=True)
class ConversationMemory:
    pending_clarification: PendingClarification | None = None
    pending_confirmation: PendingConfirmation | None = None
    focus: RecordRef | None = None
    last_person: RecordRef | None = None
    last_view: str | None = None
    last_change: str | None = None  # an executed ledger entry's key
    turn: int = 0

    def next_turn(self, turn: int) -> "ConversationMemory":
        """Advance to a new turn, expiring pending state that was not answered in time."""
        clarification = self.pending_clarification
        if clarification is not None and turn - clarification.turn > PENDING_TURNS:
            clarification = None
        confirmation = self.pending_confirmation
        if confirmation is not None and turn - confirmation.turn > PENDING_TURNS:
            confirmation = None
        return replace(self, pending_clarification=clarification, pending_confirmation=confirmation, turn=turn)

    def discard_pending(self) -> "ConversationMemory":
        """A refusal, scope change or cancellation clears anything waiting for an answer."""
        return replace(self, pending_clarification=None, pending_confirmation=None)

    def change_scope(self) -> "ConversationMemory":
        """References made in another scope are never carried across."""
        return ConversationMemory(last_change=self.last_change, turn=self.turn)
