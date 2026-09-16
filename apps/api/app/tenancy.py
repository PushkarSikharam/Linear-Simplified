"""Logical tenancy and physical deployment identity.

Logical tenancy is Organization → Team → Product. In code the organization's identifier is
`tenant_id`. Physical deployment is a separate concept: one shared deployment serves many
organizations, and a dedicated deployment is only a hosting choice. Organization, team and
product identity therefore always come from the authenticated request and the product
registry, never from deployment configuration.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.env import env_value

DEFAULT_DEPLOYMENT_ID = "local-dev"


@dataclass(frozen=True)
class ProductContext:
    """The owner of one product's Pixel: who a session, a record or a usage row belongs to."""

    tenant_id: str
    team_id: str
    product_id: str
    deployment_id: str


def deployment_id() -> str:
    return env_value("PIXEL_DEPLOYMENT_ID") or DEFAULT_DEPLOYMENT_ID
