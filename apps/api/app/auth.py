"""Token-based authentication for the Pixel demo API.

Uses itsdangerous signed tokens bound to access_grants rows.  In production
this would be replaced by an OIDC provider flow; the demo login endpoint
issues tokens without a password so automated tests and the browser can
authenticate without external infrastructure.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.db import get_connection
from app.services.env import env_bool, env_value

# The secret rotates per process; tokens don't survive a server restart,
# which is fine for the demo.  Set PIXEL_AUTH_SECRET for stable tokens.
_SECRET = env_value("PIXEL_AUTH_SECRET") or os.urandom(32).hex()
_SERIALIZER = URLSafeTimedSerializer(_SECRET)
_TOKEN_MAX_AGE_SECONDS = int(os.environ.get("PIXEL_TOKEN_MAX_AGE", "86400"))

# Demo users — seeded by migrate().
DEMO_USERS: tuple[dict, ...] = (
    {
        "user_id": "demo-product-eng",
        "scope_ids": ["workspace-product-eng"],
        "is_admin": False,
    },
    {
        "user_id": "demo-platform",
        "scope_ids": ["workspace-platform"],
        "is_admin": False,
    },
    {
        "user_id": "demo-admin",
        "scope_ids": ["workspace-product-eng", "workspace-platform"],
        "is_admin": True,
    },
)

DEFAULT_DEMO_USER_ID = "demo-product-eng"
DEFAULT_DEMO_CUSTOMER_ID = "pixel-demo"


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    customer_id: str
    scope_ids: frozenset[str]
    is_admin: bool


def demo_login_enabled() -> bool:
    """Passwordless demo login, including the admin identity, is only for deployments
    explicitly marked as isolated synthetic demos. It is never customer access."""
    return env_bool("PIXEL_SYNTHETIC_DEMO", default=False)


def seed_demo_users() -> None:
    """Insert demo users into access_grants if they don't already exist."""
    with get_connection() as connection:
        for user in DEMO_USERS:
            existing = connection.execute(
                "select 1 from access_grants where user_id = ?",
                (user["user_id"],),
            ).fetchone()
            if existing:
                continue
            connection.execute(
                "insert into access_grants(user_id, scope_ids, is_admin) values (?, ?, ?)",
                (
                    user["user_id"],
                    json.dumps(sorted(user["scope_ids"])),
                    1 if user["is_admin"] else 0,
                ),
            )


def create_token(user_id: str, customer_id: str = DEFAULT_DEMO_CUSTOMER_ID) -> str:
    """Create a signed bearer token for the given user.

    Looks up the user in access_grants, creates a login_sessions row,
    and returns the signed token string.
    """
    with get_connection() as connection:
        grant = connection.execute(
            "select scope_ids, is_admin from access_grants where user_id = ?",
            (user_id,),
        ).fetchone()
        if grant is None:
            raise ValueError(f"Unknown user: {user_id}")

        # The nonce keeps two logins in the same second from producing identical tokens.
        token = _SERIALIZER.dumps({"uid": user_id, "cid": customer_id, "n": secrets.token_hex(8)})
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = time.time() + _TOKEN_MAX_AGE_SECONDS

        # Remove stale sessions for this user before inserting.
        connection.execute(
            "delete from login_sessions where user_id = ? and expires_at < ?",
            (user_id, time.time()),
        )
        connection.execute(
            "insert into login_sessions(token_hash, user_id, customer_id, expires_at) "
            "values (?, ?, ?, ?)",
            (token_hash, user_id, customer_id, expires_at),
        )
    return token


def require_auth(authorization: str | None = Header(default=None)) -> AuthUser:
    """FastAPI dependency — validates bearer token and returns AuthUser.

    Raises 401 for missing, malformed, expired, or revoked tokens.
    """
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

    user_id = payload.get("uid")
    customer_id = payload.get("cid", DEFAULT_DEMO_CUSTOMER_ID)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload.")

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with get_connection() as connection:
        session = connection.execute(
            "select 1 from login_sessions where token_hash = ? and expires_at > ?",
            (token_hash, time.time()),
        ).fetchone()
        if session is None:
            raise HTTPException(status_code=401, detail="Token is not active.")

        grant = connection.execute(
            "select scope_ids, is_admin from access_grants where user_id = ?",
            (user_id,),
        ).fetchone()
        if grant is None:
            raise HTTPException(status_code=401, detail="User no longer exists.")

    scope_ids = frozenset(json.loads(grant["scope_ids"]))
    return AuthUser(
        user_id=user_id,
        customer_id=customer_id,
        scope_ids=scope_ids,
        is_admin=bool(grant["is_admin"]),
    )


def visible_scope_ids(user: AuthUser) -> frozenset[str] | None:
    """Scopes the user may see; None means every scope (administrators)."""
    return None if user.is_admin else user.scope_ids


def require_any_scope(scope_ids: set[str], user: AuthUser) -> None:
    """Raise 403 unless the user can access at least one of the record's scopes."""
    if user.is_admin:
        return
    if not scope_ids & user.scope_ids:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this workspace.",
        )


def require_scope(scope_id: str, user: AuthUser) -> None:
    """Raise 403 if the authenticated user does not have access to the scope."""
    if user.is_admin:
        return
    if scope_id not in user.scope_ids:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this workspace.",
        )


def require_admin(user: AuthUser) -> None:
    """Raise 403 if the authenticated user is not an admin."""
    if not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="This operation requires administrator access.",
        )
