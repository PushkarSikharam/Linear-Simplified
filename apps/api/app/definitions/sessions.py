"""Pins conversations to one product and its exact definition and knowledge versions.

A session resolves its product binding once, when it starts, and keeps those values. It can
never switch to another product. Publishing or selecting a new version affects only new
sessions. A session ends when its definition version is revoked, its product or team is
disabled, its organization is suspended, the product moves to another team, the definition
content no longer matches the pinned checksum, or it reaches the platform's maximum age.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.definitions.access import ProductAccess
from app.definitions.loader import DefinitionError, file_checksum
from app.definitions.organizations import OrganizationDirectory
from app.definitions.registry import DefinitionRegistry
from app.services.env import env_int
from app.tenancy import ProductContext, deployment_id


class DefinitionUnavailable(Exception):
    """No new session can start for this product; `reason` is UI-safe."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SessionEnded(Exception):
    """An existing session may not continue; `reason` is UI-safe."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SessionPin:
    tenant_id: str
    team_id: str
    product_id: str
    definition_id: str
    definition_version: int
    definition_checksum: str
    knowledge_version: int
    expires_at: datetime

    @property
    def context(self) -> ProductContext:
        return ProductContext(self.tenant_id, self.team_id, self.product_id, deployment_id())


def session_max_age() -> timedelta:
    """Platform session policy; product definitions cannot change it."""
    return timedelta(seconds=env_int("PIXEL_SESSION_MAX_AGE_SECONDS", 24 * 60 * 60))


def pin_new_session(
    access: ProductAccess,
    registry: DefinitionRegistry | None = None,
    now: datetime | None = None,
) -> SessionPin:
    registry = registry or DefinitionRegistry()
    binding = access.binding
    version = registry.get(binding.definition_id, binding.definition_version)
    if version is None or version.state != "published":
        raise DefinitionUnavailable("definition_not_published")
    if version.checksum != binding.definition_checksum:
        raise DefinitionUnavailable("definition_checksum_mismatch")
    if not version.bindable_by(binding.tenant_id):
        raise DefinitionUnavailable("definition_not_available")
    try:
        registry.load(binding.definition_id, binding.definition_version, allowed_states=("published",))
    except (DefinitionError, ValueError) as error:
        raise DefinitionUnavailable("definition_invalid") from error
    started = now or datetime.now(UTC)
    return SessionPin(
        tenant_id=binding.tenant_id,
        team_id=binding.team_id,
        product_id=binding.product_id,
        definition_id=binding.definition_id,
        definition_version=binding.definition_version,
        definition_checksum=version.checksum,
        knowledge_version=binding.knowledge_version,
        expires_at=started + session_max_age(),
    )


def check_pinned_session(
    pin: SessionPin | None,
    directory: OrganizationDirectory | None = None,
    now: datetime | None = None,
) -> SessionPin:
    """Return the pin if the session may continue on its pinned product and definition.

    Raises SessionEnded otherwise.
    """
    directory = directory or OrganizationDirectory()
    registry = directory.definitions
    if pin is None:
        raise SessionEnded("session_not_pinned")
    if (now or datetime.now(UTC)) >= pin.expires_at:
        raise SessionEnded("session_expired")
    organization = directory.organization(pin.tenant_id)
    if organization is None or organization.state != "active":
        raise SessionEnded("organization_unavailable")
    binding = directory.product(pin.tenant_id, pin.product_id)
    if binding is None or binding.state != "active":
        raise SessionEnded("product_disabled")
    if binding.team_id != pin.team_id:
        raise SessionEnded("product_transferred")
    team = directory.team(pin.tenant_id, pin.team_id)
    if team is None or team.state != "active":
        raise SessionEnded("team_disabled")
    version = registry.get(pin.definition_id, pin.definition_version)
    if version is None or version.state == "revoked":
        raise SessionEnded("definition_revoked")
    if version.checksum != pin.definition_checksum:
        raise SessionEnded("definition_checksum_mismatch")
    try:
        current = file_checksum(registry.source, pin.definition_id, pin.definition_version)
    except DefinitionError as error:
        raise SessionEnded("definition_missing") from error
    if current != pin.definition_checksum:
        raise SessionEnded("definition_changed")
    return pin
