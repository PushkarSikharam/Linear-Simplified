"""The model output contract (3.2 plan, section 8.2).

A model's reply is untrusted text. This module turns it into a `ParsedProposal` or refuses it,
and nothing downstream ever sees a half-checked structure. Every limit here is a number, not a
judgement, so a malformed reply is always malformed for a nameable reason.

The contract is exactly:

    {speech: string, action: {action_key, params} | null, clarification: string | null}

Three rules deserve their own sentence:

- **`capability` is not the model's to choose.** It is derived from the action key and the pinned
  definition, so a `capability` key anywhere is malformed rather than ignored.
- **Code fences are rejected, never stripped.** Stripping would quietly widen the contract, so a
  fenced reply is refused under its own reason and the fallback rate stays visible.
- **Duplicate keys are caught while parsing.** Python's `json` keeps the last value silently,
  which would let a reply say one thing and mean another.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.engine.actions import frozen_value

# Numeric limits. A reply outside any of them is malformed.
MAX_RAW_BYTES = 32 * 1024
MAX_DEPTH = 8
MAX_SPEECH = 2000
MAX_CLARIFICATION = 500
MAX_ACTION_KEY = 64
MAX_PARAMS = 16
MAX_STRING = 1000
MAX_LIST = 20

TOP_KEYS = frozenset({"speech", "action", "clarification"})
ACTION_KEYS = frozenset({"action_key", "params"})
# The parameters an action may carry, and the shape each one must have (plan section 4.2).
# A create or update genuinely needs structure, so each structured parameter is checked
# against its own schema rather than refused for being an object.
PARAM_NAMES = frozenset({"view", "control", "target", "filter", "fields", "prefill"})
TARGET_KEYS = frozenset({"entity", "id"})
FILTER_KEYS = frozenset({"field", "value"})
_FENCE = re.compile(r"^\s*(?:```|~~~)")


class MalformedOutput(Exception):
    """The model's reply cannot be used; `reason` is a stable code for the ledger and tests."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class ProposedCall:
    """An action the model asked for. Its capability is *not* here: the definition decides that.

    `params` is deeply frozen: nothing downstream may edit, extend or reinterpret what the model
    actually asked for.
    """

    action_key: str
    params: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", frozen_value(self.params))


@dataclass(frozen=True)
class ParsedProposal:
    """A structurally valid reply. Nothing here is validated, authorized or dispatchable."""

    speech: str
    action: ProposedCall | None = None
    clarification: str | None = None


def _duplicate_free(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise MalformedOutput("duplicate_key", key)
        seen.add(key)
    return dict(pairs)


def _reject_non_finite(token: str) -> Any:
    raise MalformedOutput("non_finite_number", token)


def _depth(value: Any, level: int = 1) -> int:
    if level > MAX_DEPTH:
        raise MalformedOutput("too_deep", f"deeper than {MAX_DEPTH}")
    if isinstance(value, dict):
        return max((_depth(item, level + 1) for item in value.values()), default=level)
    if isinstance(value, list):
        return max((_depth(item, level + 1) for item in value), default=level)
    return level


def parse(raw: str) -> ParsedProposal:
    """Parse one model reply, or raise `MalformedOutput`."""
    if not isinstance(raw, str) or not raw.strip():
        raise MalformedOutput("empty_output")
    if len(raw.encode("utf-8")) > MAX_RAW_BYTES:
        # Checked on the raw text: parsing something enormous first would be the mistake.
        raise MalformedOutput("too_large", f"over {MAX_RAW_BYTES} bytes")
    if _FENCE.match(raw):
        raise MalformedOutput("markdown_fence")

    decoder = json.JSONDecoder(object_pairs_hook=_duplicate_free, parse_constant=_reject_non_finite)
    try:
        document, end = decoder.raw_decode(raw.lstrip())
    except MalformedOutput:
        raise
    except ValueError as error:
        raise MalformedOutput("invalid_json", str(error)) from error
    if raw.lstrip()[end:].strip():
        raise MalformedOutput("trailing_text")
    if not isinstance(document, dict):
        raise MalformedOutput("not_an_object")

    _depth(document)
    if unknown := sorted(set(document) - TOP_KEYS):
        raise MalformedOutput("unknown_key", ", ".join(unknown))
    if missing := sorted(TOP_KEYS - set(document)):
        raise MalformedOutput("missing_key", ", ".join(missing))

    speech = document["speech"]
    if not isinstance(speech, str) or not speech.strip():
        raise MalformedOutput("empty_speech")
    if len(speech) > MAX_SPEECH:
        raise MalformedOutput("speech_too_long", f"over {MAX_SPEECH} characters")

    clarification = _clarification(document["clarification"])
    action = _action(document["action"])
    if action is not None and clarification is not None:
        # Proposing and asking at the same time leaves the turn's intent undecided.
        raise MalformedOutput("action_and_clarification")
    return ParsedProposal(speech, action, clarification)


def _clarification(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MalformedOutput("empty_clarification")
    if len(value) > MAX_CLARIFICATION:
        raise MalformedOutput("clarification_too_long", f"over {MAX_CLARIFICATION} characters")
    return value


def _action(value: Any) -> ProposedCall | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise MalformedOutput("action_not_an_object")
    if unknown := sorted(set(value) - ACTION_KEYS):
        raise MalformedOutput("unknown_key", ", ".join(unknown))
    if missing := sorted(ACTION_KEYS - set(value)):
        raise MalformedOutput("missing_key", ", ".join(missing))

    action_key = value["action_key"]
    if not isinstance(action_key, str) or not action_key.strip():
        raise MalformedOutput("empty_action_key")
    if len(action_key) > MAX_ACTION_KEY:
        raise MalformedOutput("action_key_too_long", f"over {MAX_ACTION_KEY} characters")

    params = value["params"]
    if not isinstance(params, dict):
        raise MalformedOutput("params_not_an_object")
    if len(params) > MAX_PARAMS:
        raise MalformedOutput("too_many_params", f"over {MAX_PARAMS}")
    if unknown := sorted(set(params) - PARAM_NAMES):
        raise MalformedOutput("unknown_param", ", ".join(unknown))
    for name, param in params.items():
        _check_param(name, param)
    # Frozen here, so nothing downstream can edit what the model asked for.
    return ProposedCall(action_key, frozen_value(params))


def _check_param(name: str, value: Any) -> None:
    """One schema per permitted parameter. Structure is allowed only where it is declared."""
    if name in ("view", "control"):
        _check_scalar(name, value, allow_none=False, text_only=True)
        return
    if name == "target":
        _check_object(name, value, TARGET_KEYS)
        for key in sorted(TARGET_KEYS):
            _check_scalar(f"{name}.{key}", value[key], allow_none=False, text_only=True)
        return
    if name == "filter":
        _check_object(name, value, FILTER_KEYS)
        _check_scalar("filter.field", value["field"], allow_none=False, text_only=True)
        _check_scalar("filter.value", value["value"], allow_none=False)
        return
    # fields and prefill: a field name mapped to one value, or to a list of values.
    if not isinstance(value, dict):
        raise MalformedOutput("param_not_an_object", name)
    if len(value) > MAX_PARAMS:
        raise MalformedOutput("too_many_params", name)
    for field_name, field_value in value.items():
        if not isinstance(field_name, str) or not field_name.strip():
            raise MalformedOutput("empty_field_name", name)
        if len(field_name) > MAX_ACTION_KEY:
            raise MalformedOutput("field_name_too_long", f"{name}.{field_name}")
        if isinstance(field_value, list):
            if len(field_value) > MAX_LIST:
                raise MalformedOutput("list_too_long", f"{name}.{field_name}")
            for item in field_value:
                _check_scalar(f"{name}.{field_name}", item, allow_none=False)
        else:
            _check_scalar(f"{name}.{field_name}", field_value, allow_none=True)


def _check_object(name: str, value: Any, keys: frozenset[str]) -> None:
    if not isinstance(value, dict):
        raise MalformedOutput("param_not_an_object", name)
    if unknown := sorted(set(value) - keys):
        raise MalformedOutput("unknown_key", f"{name}.{', '.join(unknown)}")
    if missing := sorted(keys - set(value)):
        raise MalformedOutput("missing_key", f"{name}.{', '.join(missing)}")


def _check_scalar(name: str, value: Any, *, allow_none: bool, text_only: bool = False) -> None:
    if value is None:
        if allow_none:
            return
        raise MalformedOutput("empty_value", name)
    if isinstance(value, str):
        if not value.strip():
            raise MalformedOutput("empty_value", name)
        if len(value) > MAX_STRING:
            raise MalformedOutput("value_too_long", name)
        return
    if text_only:
        raise MalformedOutput("unsupported_value", name)
    if isinstance(value, bool) or isinstance(value, int):
        return
    if isinstance(value, (dict, list)):
        raise MalformedOutput("nested_param", name)
    raise MalformedOutput("unsupported_value", name)
