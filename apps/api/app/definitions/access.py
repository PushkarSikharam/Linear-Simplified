"""Resolves which product's Pixel a request may use.

A client naming a product is never trusted on its own. The organization comes from the
authenticated principal; the product must be an active product of that organization, owned by
an active team, and the principal must be allowed to use it:

- organization admins may use every product of their organization;
- team admins and team members may use the products their team owns;
- visitors may use only the one product their visitor session was issued for, and only while
  that product accepts visitors.

Denials never reveal whether a product exists in another organization or team.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.definitions.organizations import OrganizationDirectory, ProductBinding
from app.definitions.vocabulary import TEAM_ROLES
from app.tenancy import ProductContext, deployment_id


class Principal(Protocol):
    kind: str  # "member" or "visitor"
    user_id: str
    tenant_id: str
    role: str | None
    team_id: str | None
    product_id: str | None


class AccessDenied(Exception):
    """The principal may not use the requested product; `reason` is UI-safe."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ProductAccess:
    context: ProductContext
    binding: ProductBinding


def authorize_product(
    principal: Principal,
    product_id: str,
    directory: OrganizationDirectory | None = None,
) -> ProductAccess:
    directory = directory or OrganizationDirectory()
    organization = directory.organization(principal.tenant_id)
    if organization is None or organization.state != "active":
        raise AccessDenied("organization_unavailable")
    binding = directory.product(principal.tenant_id, product_id)
    if binding is None or not _may_use(principal, binding):
        raise AccessDenied("product_not_found")
    if binding.state != "active":
        raise AccessDenied("product_disabled")
    team = directory.team(principal.tenant_id, binding.team_id)
    if team is None or team.state != "active":
        raise AccessDenied("team_disabled")
    return ProductAccess(
        context=ProductContext(
            tenant_id=binding.tenant_id,
            team_id=binding.team_id,
            product_id=binding.product_id,
            deployment_id=deployment_id(),
        ),
        binding=binding,
    )


def _may_use(principal: Principal, binding: ProductBinding) -> bool:
    if principal.kind == "visitor":
        return principal.product_id == binding.product_id and binding.visitor_access
    if principal.role == "org_admin":
        return True
    return principal.role in TEAM_ROLES and principal.team_id == binding.team_id
