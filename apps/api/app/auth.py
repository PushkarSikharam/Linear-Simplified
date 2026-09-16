"""Token authentication for organization members and product visitors.

Two security domains:
- Members belong to an organization (organization admin, team admin or team member). Their
  organization comes from their membership, never from deployment configuration.
- Visitors are not organization members. A visitor token is issued for exactly one product and
  grants nothing else.

Tokens are signed with itsdangerous and must also match an active login row. In production the
member login would come from an OIDC provider; the passwordless demo login exists only for
isolated synthetic demos.

`scope_ids` and `is_admin` are record-level grants inside the demo product's data (its own
workspaces). They are product data permissions, not Pixel organization roles.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, Header, HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.db import get_connection
from app.definitions.access import authorize_product
from app.definitions.organizations import OrganizationDirectory
from app.services.env import env_bool, env_value

# The secret rotates per process; tokens don't survive a server restart,
# which is fine for the demo.  Set PIXEL_AUTH_SECRET for stable tokens.
_SECRET = env_value("PIXEL_AUTH_SECRET") or os.urandom(32).hex()
_SERIALIZER = URLSafeTimedSerializer(_SECRET)
_TOKEN_MAX_AGE_SECONDS = int(os.environ.get("PIXEL_TOKEN_MAX_AGE", "86400"))

# Demo users and their record grants inside the demo product. Their organization memberships
# come from product seed packages.
DEMO_USERS: tuple[dict, ...] = (
    {"user_id": "demo-product-eng", "scope_ids": ["workspace-product-eng"], "is_admin": False},
    {"user_id": "demo-platform", "scope_ids": ["workspace-platform"], "is_admin": False},
    {"user_id": "demo-admin", "scope_ids": ["workspace-product-eng", "workspace-platform"], "is_admin": True},
)


@dataclass(frozen=True)
class AuthUser:
    kind: str  # "member" or "visitor"
    user_id: str
    tenant_id: str
    role: str | None = None
    team_id: str | None = None
    product_id: str | None = None
    scope_ids: frozenset[str] = frozenset()
    is_admin: bool = False


def demo_login_enabled() -> bool:
    """Passwordless demo login, including the admin identity, is only for deployments
    explicitly marked as isolated synthetic demos. It is never customer access."""
    return env_bool("PIXEL_SYNTHETIC_DEMO", default=False)


def seed_demo_users() -> None:
    """Insert demo users' record grants if they don't already exist."""
    with get_connection() as connection:
        for user in DEMO_USERS:
            connection.execute(
                "insert or ignore into access_grants(user_id, scope_ids, is_admin) values (?, ?, ?)",
                (user["user_id"], json.dumps(sorted(user["scope_ids"])), 1 if user["is_admin"] else 0),
            )


def create_token(user_id: str, tenant_id: str | None = None) -> str:
    """Create a member token for one organization the user belongs to.

    Without an explicit organization, the user must belong to exactly one.
    """
    directory = OrganizationDirectory()
    if tenant_id is None:
        organizations = directory.organizations_of(user_id)
        if len(organizations) != 1:
            raise ValueError(f"{user_id} must name one of their organizations")
        tenant_id = organizations[0]
    if directory.membership(tenant_id, user_id) is None:
        raise ValueError(f"{user_id} is not a member of {tenant_id}")

    # The nonce keeps two logins in the same second from producing identical tokens.
    token = _SERIALIZER.dumps({"k": "member", "uid": user_id, "tid": tenant_id, "n": secrets.token_hex(8)})
    with get_connection() as connection:
        # login_sessions references access_grants; members without record grants get an empty one.
        connection.execute(
            "insert or ignore into access_grants(user_id, scope_ids, is_admin) values (?, '[]', 0)",
            (user_id,),
        )
        connection.execute("delete from login_sessions where user_id = ? and expires_at < ?", (user_id, time.time()))
        # The login_sessions.customer_id column holds the organization (tenant) ID.
        connection.execute(
            "insert into login_sessions(token_hash, user_id, customer_id, expires_at) values (?, ?, ?, ?)",
            (_hash(token), user_id, tenant_id, time.time() + _TOKEN_MAX_AGE_SECONDS),
        )
    return token


def create_visitor_token(tenant_id: str, product_id: str) -> tuple[str, str]:
    """Start a visitor session for one product. Returns (token, visitor_id).

    Raises AccessDenied unless the product exists, is active, and accepts visitors.
    """
    visitor_id = f"visitor-{uuid4()}"
    authorize_product(_visitor(visitor_id, tenant_id, product_id), product_id)
    token = _SERIALIZER.dumps(
        {"k": "visitor", "vid": visitor_id, "tid": tenant_id, "pid": product_id, "n": secrets.token_hex(8)}
    )
    with get_connection() as connection:
        connection.execute("delete from visitor_logins where expires_at < ?", (time.time(),))
        connection.execute(
            "insert into visitor_logins(token_hash, visitor_id, tenant_id, product_id, expires_at) "
            "values (?, ?, ?, ?, ?)",
            (_hash(token), visitor_id, tenant_id, product_id, time.time() + _TOKEN_MAX_AGE_SECONDS),
        )
    return token, visitor_id


def require_auth(authorization: str | None = Header(default=None)) -> AuthUser:
    """FastAPI dependency: validate a member or visitor bearer token.

    Raises 401 for missing, malformed, expired or revoked tokens, and 403 when the
    organization is suspended.
    """
    payload, token = _decode(authorization)
    kind = payload.get("k", "member")
    if kind == "visitor":
        user = _visitor_from(payload, token)
    elif kind == "member":
        user = _member_from(payload, token)
    else:
        raise HTTPException(status_code=401, detail="Invalid token payload.")

    organization = OrganizationDirectory().organization(user.tenant_id)
    if organization is None:
        raise HTTPException(status_code=401, detail="Organization no longer exists.")
    if organization.state != "active":
        raise HTTPException(status_code=403, detail="This organization is suspended.")
    return user


def require_member(user: AuthUser = Depends(require_auth)) -> AuthUser:
    """FastAPI dependency: organization members only; visitors are refused."""
    if user.kind != "member":
        raise HTTPException(status_code=403, detail="This operation requires an organization member.")
    return user


def require_org_admin(user: AuthUser) -> None:
    if user.kind != "member" or user.role != "org_admin":
        raise HTTPException(status_code=403, detail="This operation requires an organization administrator.")


def visible_scope_ids(user: AuthUser) -> frozenset[str] | None:
    """Record scopes the user may see inside the demo product; None means every scope."""
    return None if user.is_admin else user.scope_ids


def require_any_scope(scope_ids: set[str], user: AuthUser) -> None:
    """Raise 403 unless the user can access at least one of the record's scopes."""
    if user.is_admin:
        return
    if not scope_ids & user.scope_ids:
        raise HTTPException(status_code=403, detail="You do not have access to this workspace.")


def require_scope(scope_id: str, user: AuthUser) -> None:
    """Raise 403 if the authenticated user does not have access to the scope."""
    if user.is_admin:
        return
    if scope_id not in user.scope_ids:
        raise HTTPException(status_code=403, detail="You do not have access to this workspace.")


def require_admin(user: AuthUser) -> None:
    """Raise 403 unless the user administers the demo product's records."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="This operation requires administrator access.")


def _decode(authorization: str | None) -> tuple[dict, str]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Missing or malformed bearer token.")
    try:
        payload = _SERIALIZER.loads(token, max_age=_TOKEN_MAX_AGE_SECONDS)
    except SignatureExpired:
        raise HTTPException(status_code=401, detail="Token has expired.")
    except BadSignature:
        raise HTTPException(status_code=401, detail="Invalid token.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="Invalid token payload.")
    return payload, token


def _member_from(payload: dict, token: str) -> AuthUser:
    user_id, tenant_id = payload.get("uid"), payload.get("tid")
    if not user_id or not tenant_id:
        raise HTTPException(status_code=401, detail="Invalid token payload.")
    with get_connection() as connection:
        active = connection.execute(
            "select 1 from login_sessions where token_hash = ? and customer_id = ? and expires_at > ?",
            (_hash(token), tenant_id, time.time()),
        ).fetchone()
        grant = connection.execute(
            "select scope_ids, is_admin from access_grants where user_id = ?", (user_id,)
        ).fetchone()
    if active is None:
        raise HTTPException(status_code=401, detail="Token is not active.")
    membership = OrganizationDirectory().membership(tenant_id, user_id)
    if membership is None:
        raise HTTPException(status_code=401, detail="User is no longer a member of this organization.")
    return AuthUser(
        kind="member",
        user_id=user_id,
        tenant_id=tenant_id,
        role=membership.role,
        team_id=membership.team_id,
        scope_ids=frozenset(json.loads(grant["scope_ids"])) if grant else frozenset(),
        is_admin=bool(grant["is_admin"]) if grant else False,
    )


def _visitor_from(payload: dict, token: str) -> AuthUser:
    visitor_id, tenant_id, product_id = payload.get("vid"), payload.get("tid"), payload.get("pid")
    if not visitor_id or not tenant_id or not product_id:
        raise HTTPException(status_code=401, detail="Invalid token payload.")
    with get_connection() as connection:
        active = connection.execute(
            "select 1 from visitor_logins where token_hash = ? and visitor_id = ? and tenant_id = ? "
            "and product_id = ? and expires_at > ?",
            (_hash(token), visitor_id, tenant_id, product_id, time.time()),
        ).fetchone()
    if active is None:
        raise HTTPException(status_code=401, detail="Visitor session is not active.")
    return _visitor(visitor_id, tenant_id, product_id)


def _visitor(visitor_id: str, tenant_id: str, product_id: str) -> AuthUser:
    return AuthUser(kind="visitor", user_id=visitor_id, tenant_id=tenant_id, product_id=product_id)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

