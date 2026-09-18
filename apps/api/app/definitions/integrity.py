"""Can every active product start a conversation right now? (deployment readiness)

On 2026-09-18 production reported itself healthy while it could not start a single conversation.
Its database had registered the product definition from a Windows checkout, whose line endings
give the file a different checksum from the Linux copy inside the container. Published versions
are immutable and startup never rewrites them, so every new session was refused with
`definition_invalid` — while `/health` checked only that the database opened.

So readiness now asks the question that actually matters, using **the same code a real request
runs**: for every active product, would `pin_new_session` succeed? It is side-effect free, so
health can call it without creating anything, and the check cannot drift from reality because
it *is* the reality.

What a public caller learns is deliberately minimal — a count, never tenant or product
identifiers. The details go to the operator log, where they belong on a multi-tenant platform.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass

from app import db
from app.definitions.access import ProductAccess
from app.definitions.organizations import OrganizationDirectory
from app.definitions.sessions import DefinitionUnavailable, pin_new_session
from app.tenancy import ProductContext, deployment_id

logger = logging.getLogger("pixel.readiness")

# Health is polled often; resolving every definition re-reads and re-parses its file. Definition
# files cannot change inside a running container, but registry rows can, so the answer is kept
# briefly rather than forever.
CACHE_SECONDS = 30.0


@dataclass(frozen=True)
class StartProblem:
    """One active product that cannot start a new conversation, and the platform's reason."""

    tenant_id: str
    product_id: str
    definition_id: str
    definition_version: int
    reason: str


def session_start_problems(directory: OrganizationDirectory | None = None) -> tuple[StartProblem, ...]:
    """Every active product whose next conversation would be refused, right now."""
    directory = directory or OrganizationDirectory()
    problems: list[StartProblem] = []
    for binding in directory.active_products():
        access = ProductAccess(
            context=ProductContext(
                tenant_id=binding.tenant_id,
                team_id=binding.team_id,
                product_id=binding.product_id,
                deployment_id=deployment_id(),
            ),
            binding=binding,
        )
        try:
            pin_new_session(access, directory.definitions)
        except DefinitionUnavailable as unavailable:
            problems.append(StartProblem(
                tenant_id=binding.tenant_id,
                product_id=binding.product_id,
                definition_id=binding.definition_id,
                definition_version=binding.definition_version,
                reason=unavailable.reason,
            ))
    return tuple(problems)


class ReadinessCheck:
    """A short-lived cache of `session_start_problems`, safe to call from concurrent requests."""

    def __init__(self, ttl_seconds: float = CACHE_SECONDS, clock=time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._checked_at: float | None = None
        self._checked_database: str | None = None
        self._problems: tuple[StartProblem, ...] = ()

    def problems(self) -> tuple[StartProblem, ...]:
        # The answer belongs to one database. A different one (a test, a restored backup) never
        # reuses it, however recently it was computed.
        database = str(db.DB_PATH)
        with self._lock:
            now = self._clock()
            stale = self._checked_at is None or now - self._checked_at >= self._ttl
            if stale or database != self._checked_database:
                self._problems = session_start_problems()
                self._checked_at = now
                self._checked_database = database
                for problem in self._problems:
                    # Operator log only: identifiers never leave through the public endpoint.
                    logger.warning(json.dumps({
                        "event": "session_start_unavailable",
                        "tenant_id": problem.tenant_id,
                        "product_id": problem.product_id,
                        "definition_id": problem.definition_id,
                        "definition_version": problem.definition_version,
                        "reason": problem.reason,
                    }))
            return self._problems

    def invalidate(self) -> None:
        """Forget the cached answer, so the next call checks again (tests and operator actions)."""
        with self._lock:
            self._checked_at = None
