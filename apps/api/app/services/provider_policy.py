"""Paid-provider policy: which capabilities a product may use, and how much.

Limits are configured per deployment today and applied per organization and product.
Every lookup already takes the product context, so policies can move to per-organization
records without changing accounting semantics or call sites.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from app.services.env import env_bool, env_int, env_value
from app.tenancy import ProductContext

CAPABILITIES = ("speech", "reasoning", "realtime")


@dataclass(frozen=True)
class CapabilityPolicy:
    """Daily quotas for one capability. ``None`` means no limit on that dimension."""

    unit: str
    max_units_per_attempt: int
    user_attempts: int
    deployment_attempts: int
    session_attempts: int | None
    user_units: int | None
    deployment_units: int | None

    @property
    def enabled(self) -> bool:
        return self.user_attempts > 0 and self.deployment_attempts > 0


@dataclass(frozen=True)
class ReasoningTokenLimits:
    max_input_tokens: int
    max_output_tokens: int


_DEFAULTS: dict[str, CapabilityPolicy] = {
    "speech": CapabilityPolicy(
        unit="characters", max_units_per_attempt=2_000,
        user_attempts=100, deployment_attempts=500, session_attempts=None,
        user_units=25_000, deployment_units=125_000,
    ),
    "reasoning": CapabilityPolicy(
        unit="tokens", max_units_per_attempt=0,  # derived from the token limits below
        user_attempts=50, deployment_attempts=250, session_attempts=25,
        user_units=None, deployment_units=None,
    ),
    # Realtime voice opens ongoing audio usage we cannot bound yet; it stays disabled.
    "realtime": CapabilityPolicy(
        unit="seconds", max_units_per_attempt=0,
        user_attempts=0, deployment_attempts=0, session_attempts=None,
        user_units=0, deployment_units=0,
    ),
}


def paid_providers_enabled(tenant: ProductContext) -> bool:
    """Kill switch for every paid provider."""
    return env_bool("PIXEL_PAID_PROVIDERS_ENABLED", default=True)


def reasoning_token_limits(tenant: ProductContext) -> ReasoningTokenLimits:
    return ReasoningTokenLimits(
        max_input_tokens=env_int("LLM_MAX_INPUT_TOKENS", 4_000),
        max_output_tokens=env_int("LLM_MAX_OUTPUT_TOKENS", 512),
    )


def capability_policy(tenant: ProductContext, capability: str) -> CapabilityPolicy:
    if capability not in _DEFAULTS:
        raise ValueError(f"Unknown capability: {capability}")
    default = _DEFAULTS[capability]
    prefix = f"PIXEL_BUDGET_{capability.upper()}"
    policy = replace(
        default,
        max_units_per_attempt=env_int(f"{prefix}_MAX_UNITS_PER_ATTEMPT", default.max_units_per_attempt),
        user_attempts=env_int(f"{prefix}_USER_ATTEMPTS", default.user_attempts),
        deployment_attempts=env_int(f"{prefix}_DEPLOYMENT_ATTEMPTS", default.deployment_attempts),
        session_attempts=_optional_int(f"{prefix}_SESSION_ATTEMPTS", default.session_attempts),
        user_units=_optional_int(f"{prefix}_USER_UNITS", default.user_units),
        deployment_units=_optional_int(f"{prefix}_DEPLOYMENT_UNITS", default.deployment_units),
    )
    if capability == "reasoning":
        # One reasoning attempt may use at most the input limit plus the output limit.
        limits = reasoning_token_limits(tenant)
        policy = replace(policy, max_units_per_attempt=limits.max_input_tokens + limits.max_output_tokens)
    return policy


def max_attempts_per_request(tenant: ProductContext) -> int:
    return env_int("PIXEL_MAX_ATTEMPTS_PER_REQUEST", 2)


def total_attempt_cap(tenant: ProductContext) -> int | None:
    """Optional hard ceiling on every attempt recorded for this deployment (measurement runs)."""
    return _optional_int("PIXEL_TOTAL_ATTEMPT_CAP", None)


def usage_retention_days() -> int:
    return env_int("PIXEL_USAGE_RETENTION_DAYS", 90)


def _optional_int(name: str, default: int | None) -> int | None:
    value = env_value(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
