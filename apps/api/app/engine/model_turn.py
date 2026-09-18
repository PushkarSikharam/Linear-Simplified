"""The one way a model reply may become an action (3.2 plan, sections 8.2–8.4).

A model reply reaches a record through exactly this module, and it is fail-closed at every step:

    raw reply
      → parsed against the output contract        (section 8.2)
      → a generic action whose capability comes from the definition, never the model
      → every parameter traced to a verified source (section 8.3)
      → validated against the pinned definition and the turn snapshot (section 4)
      → a mutation becomes a *pending confirmation*, never a dispatch (section 8.4)

**Model origin is carried by a type, not remembered.** `ModelProposal` is the only thing this
module accepts, and `ActionOrigin.MODEL` travels with it to the confirmation decision. A later
call site cannot forget to pass a flag, because there is no flag to pass.

**Nothing here dispatches.** The only mutation outcome is `AwaitingConfirmation`, which holds no
execution key. Confirming is a separate call that requires a *fresh* snapshot, re-validates
everything, and makes no provider call — the question it asked came from a deterministic
template. Dispatch itself belongs to the execution boundary, wired in a later slice.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.definitions.contract import ProductDefinition
from app.definitions.vocabulary import MUTATING_CAPABILITIES
from app.engine.actions import (
    ActionOrigin,
    ConfirmationReason,
    FilterParam,
    GenericAction,
    RecordRef,
    UnknownAction,
    confirmation_reason,
)
from app.engine.proposal_parser import MalformedOutput, ParsedProposal, parse
from app.engine.provenance import Attributed, Provenance, ProvenanceChecker, TurnEvidence, Unattributable
from app.engine.snapshot import TurnSnapshot
from app.engine.validator import ActionContractValidator, Refusal, ValidatedAction


@dataclass(frozen=True)
class ModelProposal:
    """A parsed reply, tagged with where it came from. Only `consider` constructs one."""

    parsed: ParsedProposal
    origin: ActionOrigin = ActionOrigin.MODEL


@dataclass(frozen=True)
class Refused:
    """The reply cannot become an action. Nothing is proposed, asked or dispatched."""

    reason: str
    detail: str = ""
    speech: str | None = None


@dataclass(frozen=True)
class Answered:
    """The model only spoke, or only asked. No action is involved."""

    speech: str
    clarification: str | None = None


@dataclass(frozen=True)
class Proposed:
    """A validated non-mutating action, ready for a composer. Still not dispatched."""

    validated: ValidatedAction
    speech: str
    origin: ActionOrigin
    provenance: Attributed | None = None


@dataclass(frozen=True)
class AwaitingConfirmation:
    """A validated mutation the visitor has not yet approved.

    It carries no execution key by construction, so there is nothing here to dispatch. The
    question names the exact target and change, and comes from the definition's own template.
    """

    validated: ValidatedAction
    reason: ConfirmationReason
    origin: ActionOrigin
    question_key: str = "confirm_action"
    provenance: Attributed | None = None
    source_snapshot_id: str = ""

    @property
    def target(self) -> RecordRef | None:
        return self.validated.action.target

    @property
    def changes(self) -> dict:
        return dict(self.validated.action.fields or {})


Outcome = Refused | Answered | Proposed | AwaitingConfirmation


def consider(
    raw: str, *, definition: ProductDefinition, snapshot: TurnSnapshot, evidence: TurnEvidence,
    validator: ActionContractValidator | None = None,
) -> Outcome:
    """Turn one model reply into an outcome. A mutation can only ever await confirmation."""
    if evidence.snapshot is not snapshot:
        return Refused("snapshot_mismatch", "turn evidence and validation must use one snapshot")
    try:
        parsed = parse(raw)
    except MalformedOutput as malformed:
        return Refused(f"malformed_{malformed.reason}", malformed.detail)

    proposal = ModelProposal(parsed)
    if proposal.parsed.action is None:
        return Answered(proposal.parsed.speech, proposal.parsed.clarification)

    call = proposal.parsed.action
    spec = definition.actions.get(call.action_key)
    if spec is None:
        return Refused("unknown_action", call.action_key, proposal.parsed.speech)

    try:
        action = _build(definition, call)
    except (UnknownAction, TypeError, ValueError) as error:
        return Refused("bad_parameters", str(error), proposal.parsed.speech)

    mutating = action.capability in MUTATING_CAPABILITIES
    attributed: Attributed | None = None
    if mutating:
        # Provenance first: an unattributable value is refused before anything is asked.
        checker = ProvenanceChecker(definition)
        if action.target is not None or spec.capability.name == "UPDATE_RECORD":
            target_source = checker.check_target(action.target, evidence)
            if isinstance(target_source, Unattributable):
                return Refused("unattributable_target", target_source.detail, proposal.parsed.speech)
        field_sources = checker.check_fields(
            spec.entity, dict(action.fields or {}), evidence,
            creating=spec.capability.name == "CREATE_RECORD",
        )
        if isinstance(field_sources, Unattributable):
            return Refused("unattributable_value", field_sources.detail, proposal.parsed.speech)
        attributed = field_sources

    checked = (validator or ActionContractValidator(definition, snapshot)).validate(action)
    if isinstance(checked, Refusal):
        return Refused(checked.code, checked.detail, proposal.parsed.speech)

    if not mutating:
        return Proposed(checked, proposal.parsed.speech, proposal.origin)

    reason = confirmation_reason(spec, target_from_correction=False, origin=proposal.origin)
    if reason is None:
        return Refused("confirmation_required", "model-originated mutations must be confirmed")
    return AwaitingConfirmation(
        checked, reason, proposal.origin, provenance=attributed,
        source_snapshot_id=snapshot.snapshot_id,
    )


def confirm(
    pending: AwaitingConfirmation, *, definition: ProductDefinition, snapshot: TurnSnapshot,
    evidence: TurnEvidence, validator: ActionContractValidator | None = None,
) -> Proposed | Refused:
    """Re-check an approved mutation against a **fresh** snapshot before anything acts on it.

    The visitor's "yes" authorizes the change they were shown, not whatever the world looks like
    now, so every parameter is re-resolved and re-validated. This makes no provider call.
    """
    if evidence.snapshot is not snapshot:
        return Refused("snapshot_mismatch", "confirmation evidence must use the fresh snapshot")
    if snapshot.snapshot_id == pending.source_snapshot_id:
        return Refused("stale_confirmation_snapshot", "confirmation requires a fresh snapshot")
    action = pending.validated.action
    spec = definition.actions[action.action_key]

    checker = ProvenanceChecker(definition)
    if action.target is not None:
        if isinstance(checker.check_target(action.target, evidence), Unattributable):
            return Refused("unattributable_target", "the record is no longer what was approved")
    fields = checker.check_fields(
        spec.entity, dict(action.fields or {}), evidence,
        creating=spec.capability.name == "CREATE_RECORD",
    )
    if isinstance(fields, Unattributable):
        return Refused("unattributable_value", fields.detail)

    checked = (validator or ActionContractValidator(definition, snapshot)).validate(
        action, confirmation=pending.reason
    )
    if isinstance(checked, Refusal):
        return Refused(checked.code, checked.detail)
    return Proposed(checked, "", pending.origin, provenance=fields)


def _build(definition: ProductDefinition, call) -> GenericAction:
    """Build the generic action. The capability comes from the definition, never from the model."""
    params: dict = {}
    for name, value in call.params.items():
        if name == "target":
            params["target"] = RecordRef(value["entity"], value["id"])
        elif name == "filter":
            params["filter"] = FilterParam(value["field"], value["value"])
        elif name in ("fields", "prefill"):
            params[name] = {
                field: tuple(item) if isinstance(item, (list, tuple)) else item
                for field, item in value.items()
            }
        else:
            params[name] = value
    return GenericAction.for_definition(definition, call.action_key, **params)
