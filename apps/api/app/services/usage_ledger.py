"""Persistent, atomic, tenant-scoped accounting for paid-provider attempts.

Every attempt to call a paid provider must reserve allowance here first. Reservation
runs inside a SQLite ``begin immediate`` transaction, so concurrent requests cannot both
take the last allowance.

Rules:
- Reserve before dispatch. If reservation is refused, or accounting itself fails, no
  provider request may be sent.
- Once dispatched, an attempt stays counted whatever happens (error, timeout,
  cancellation). ``release`` returns allowance only when no request was sent.
- Every row and every query is scoped to a tenant, product and deployment.
- Rows hold usage metadata only. ``reserved_units`` is our estimate; ``actual_*`` columns
  hold provider-reported usage when available. Neither is billing.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.db import get_connection
from app.services.provider_policy import (
    CAPABILITIES,
    capability_policy,
    max_attempts_per_request,
    paid_providers_enabled,
    total_attempt_cap,
    usage_retention_days,
)
from app.tenancy import TenantContext

SETTLED_STATUSES = ("succeeded", "failed", "timeout", "cancelled")

# Blocked attempts never reached a provider; not_sent reservations were released.
_COUNTED = "status not in ('blocked', 'not_sent')"
# Consumption is the larger of our estimate and what the provider reported.
_CONSUMED_UNITS = "coalesce(sum(max(reserved_units, coalesce(actual_units, 0))), 0)"
_TENANT_SCOPE = "tenant_id = ? and product_id = ? and deployment_id = ?"

logger = logging.getLogger("pixel.usage")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class BudgetExceeded(Exception):
    """The attempt was refused before dispatch; ``reason`` is a stable, UI-safe code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AccountingUnavailable(Exception):
    """The ledger could not be written; paid calls must fail closed."""


@dataclass(frozen=True)
class AttemptRequest:
    tenant: TenantContext
    user_id: str
    request_id: str
    capability: str
    provider: str
    model: str | None = None
    session_id: str | None = None
    reserved_units: int = 0


class UsageLedger:
    def reserve(self, attempt: AttemptRequest) -> str:
        """Reserve one provider attempt and return its ID.

        Raises BudgetExceeded when policy refuses it and AccountingUnavailable when the
        ledger cannot record it; in both cases the caller must not contact the provider.
        """
        try:
            return self._reserve(attempt)
        except BudgetExceeded:
            raise
        except Exception as error:
            _log("accounting_unavailable", **_tenant_fields(attempt.tenant),
                 capability=attempt.capability, provider=attempt.provider, error=type(error).__name__)
            raise AccountingUnavailable("Provider accounting is unavailable.") from error

    def settle(
        self,
        attempt_id: str,
        tenant: TenantContext,
        status: str,
        *,
        user_id: str | None = None,
        duration_ms: int | None = None,
        actual_units: int | None = None,
        actual_input_units: int | None = None,
        actual_output_units: int | None = None,
        reason: str | None = None,
    ) -> bool:
        """Record the outcome of a dispatched attempt. Its allowance stays consumed."""
        if status not in SETTLED_STATUSES:
            raise ValueError(f"Unknown attempt status: {status}")
        user_clause, user_params = _optional_user(user_id)
        with get_connection() as connection:
            cursor = connection.execute(
                f"""
                update provider_attempts
                set status = ?, duration_ms = ?, actual_units = ?, actual_input_units = ?,
                    actual_output_units = ?, reason = ?, settled_at = ?
                where attempt_id = ? and status = 'reserved' and {_TENANT_SCOPE} {user_clause}
                """,
                (
                    status, duration_ms, actual_units, actual_input_units, actual_output_units,
                    _short(reason), _now().isoformat(), attempt_id, *_tenant_params(tenant), *user_params,
                ),
            )
        settled = cursor.rowcount == 1
        if settled:
            _log("attempt_settled", **_tenant_fields(tenant), attempt_id=attempt_id, status=status,
                 duration_ms=duration_ms, actual_units=actual_units, reason=_short(reason))
        return settled

    def release(self, attempt_id: str, tenant: TenantContext, *, user_id: str | None = None) -> bool:
        """Return a reservation's allowance. Only valid when no provider request was sent."""
        user_clause, user_params = _optional_user(user_id)
        with get_connection() as connection:
            cursor = connection.execute(
                f"""
                update provider_attempts set status = 'not_sent', settled_at = ?
                where attempt_id = ? and status = 'reserved' and {_TENANT_SCOPE} {user_clause}
                """,
                (_now().isoformat(), attempt_id, *_tenant_params(tenant), *user_params),
            )
        released = cursor.rowcount == 1
        if released:
            _log("attempt_released", **_tenant_fields(tenant), attempt_id=attempt_id)
        return released

    def summary(self, tenant: TenantContext, usage_day: str | None = None) -> list[dict]:
        """Per capability, provider and status totals for one tenant's product on one UTC day."""
        day = usage_day or _today()
        with get_connection() as connection:
            rows = connection.execute(
                f"""
                select capability, provider, unit, status, count(*) as attempts,
                       coalesce(sum(reserved_units), 0) as reserved_units,
                       sum(actual_units) as actual_units
                from provider_attempts
                where {_TENANT_SCOPE} and usage_day = ?
                group by capability, provider, unit, status
                order by capability, provider, status
                """,
                (*_tenant_params(tenant), day),
            ).fetchall()
        return [dict(row) for row in rows]

    def prune_expired(self) -> int:
        cutoff = (_now().date() - timedelta(days=usage_retention_days())).isoformat()
        with get_connection() as connection:
            cursor = connection.execute("delete from provider_attempts where usage_day < ?", (cutoff,))
        return cursor.rowcount

    def _reserve(self, attempt: AttemptRequest) -> str:
        now = _now()
        attempt_id = str(uuid4())
        known = attempt.capability in CAPABILITIES
        policy = capability_policy(attempt.tenant, attempt.capability) if known else None
        refusal = _static_refusal(attempt)
        with get_connection() as connection:
            connection.execute("begin immediate")
            if refusal is None:
                refusal = _budget_refusal(connection, attempt, policy, now.date().isoformat())
            connection.execute(
                """
                insert into provider_attempts(
                  attempt_id, tenant_id, product_id, deployment_id, user_id, session_id,
                  request_id, capability, provider, model, unit, reserved_units,
                  status, reason, usage_day, created_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id, *_tenant_params(attempt.tenant), attempt.user_id, attempt.session_id,
                    attempt.request_id, attempt.capability, attempt.provider, attempt.model,
                    policy.unit if policy else "none",
                    0 if refusal else attempt.reserved_units,
                    "blocked" if refusal else "reserved",
                    refusal,
                    now.date().isoformat(),
                    now.isoformat(),
                ),
            )
        _log(
            "attempt_blocked" if refusal else "attempt_reserved",
            **_tenant_fields(attempt.tenant),
            attempt_id=attempt_id, request_id=attempt.request_id, session_id=attempt.session_id,
            user_id=attempt.user_id, capability=attempt.capability, provider=attempt.provider,
            model=attempt.model, reserved_units=attempt.reserved_units, reason=refusal,
        )
        if refusal:
            raise BudgetExceeded(refusal)
        return attempt_id


def _static_refusal(attempt: AttemptRequest) -> str | None:
    """Refusals that need no ledger state."""
    if attempt.capability not in CAPABILITIES:
        return "unknown_capability"
    if not paid_providers_enabled(attempt.tenant):
        return "providers_disabled"
    policy = capability_policy(attempt.tenant, attempt.capability)
    if not policy.enabled:
        return "capability_disabled"
    if attempt.reserved_units < 0 or attempt.reserved_units > policy.max_units_per_attempt:
        return "attempt_too_large"
    return None


def _budget_refusal(connection, attempt: AttemptRequest, policy, day: str) -> str | None:
    """Refusals that depend on recorded usage; runs inside the reservation transaction."""
    tenant = _tenant_params(attempt.tenant)

    def used(clause: str, *params) -> tuple[int, int]:
        row = connection.execute(
            f"select count(*), {_CONSUMED_UNITS} from provider_attempts "
            f"where {_TENANT_SCOPE} and {_COUNTED} {clause}",
            (*tenant, *params),
        ).fetchone()
        return row[0], row[1]

    if used("and user_id = ? and request_id = ?", attempt.user_id, attempt.request_id)[0] \
            >= max_attempts_per_request(attempt.tenant):
        return "request_attempt_limit"

    cap = total_attempt_cap(attempt.tenant)
    if cap is not None and used("")[0] >= cap:
        return "total_attempt_cap"

    daily = "and usage_day = ? and capability = ?"
    if policy.session_attempts is not None and attempt.session_id is not None:
        if used(f"{daily} and session_id = ?", day, attempt.capability, attempt.session_id)[0] \
                >= policy.session_attempts:
            return "session_attempt_limit"

    deployment_attempts, deployment_units = used(daily, day, attempt.capability)
    user_attempts, user_units = used(f"{daily} and user_id = ?", day, attempt.capability, attempt.user_id)
    if deployment_attempts >= policy.deployment_attempts:
        return "deployment_attempt_limit"
    if user_attempts >= policy.user_attempts:
        return "user_attempt_limit"
    if policy.deployment_units is not None and deployment_units + attempt.reserved_units > policy.deployment_units:
        return "deployment_unit_limit"
    if policy.user_units is not None and user_units + attempt.reserved_units > policy.user_units:
        return "user_unit_limit"
    return None


def _tenant_params(tenant: TenantContext) -> tuple[str, str, str]:
    return tenant.tenant_id, tenant.product_id, tenant.deployment_id


def _tenant_fields(tenant: TenantContext) -> dict[str, str]:
    return {"tenant_id": tenant.tenant_id, "product_id": tenant.product_id, "deployment_id": tenant.deployment_id}


def _optional_user(user_id: str | None) -> tuple[str, tuple[str, ...]]:
    return ("and user_id = ?", (user_id,)) if user_id else ("", ())


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> str:
    return _now().date().isoformat()


def _short(value: str | None) -> str | None:
    return value[:60] if value else value


def _log(event: str, **fields) -> None:
    """Metadata only: never prompts, generated audio, credentials or provider error bodies."""
    logger.info(json.dumps({"event": event, **{k: v for k, v in fields.items() if v is not None}}))
