"""Tenant ownership for the running deployment.

Each customer runs an isolated Pixel deployment that serves exactly one tenant and one
product. Ownership therefore comes from deployment configuration, never from request
input. Every tenant-owned record (usage, sessions, logins) is stamped with this context.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.env import env_value

DEV_TENANT_ID = "pixel-dev"
DEV_PRODUCT_ID = "linear_simplified"
DEV_DEPLOYMENT_ID = "local-dev"


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    product_id: str
    deployment_id: str


def deployment_tenant() -> TenantContext:
    return TenantContext(
        tenant_id=env_value("PIXEL_TENANT_ID") or DEV_TENANT_ID,
        product_id=env_value("PIXEL_PRODUCT_ID") or DEV_PRODUCT_ID,
        deployment_id=env_value("PIXEL_DEPLOYMENT_ID") or DEV_DEPLOYMENT_ID,
    )
