"""The single path platform code uses to call external providers.

Keeping outbound HTTP in one place lets tests and CI block every real provider call:
with ``PIXEL_BLOCK_EXTERNAL_HTTP=true`` any attempt raises ``ExternalCallBlocked``.

Connections are kept open and reused. Opening a new TLS connection to a provider costs more
than the provider's own work: measured against Azure Speech, a warm connection returned a whole
spoken reply in about 0.2 s, while a fresh one spent 0.15 to 0.45 s on the handshake alone.
"""
from __future__ import annotations

import http.client
import json
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.services.env import env_bool

# Idle connections kept per host, and how long one may sit unused before it is dropped rather
# than reused. Providers close idle connections on their side after a while; a connection that
# was closed anyway is retried once on a fresh one (see `post`).
MAX_IDLE_PER_HOST = 4
MAX_IDLE_SECONDS = 50.0

_TLS = ssl.create_default_context()
_DEFAULT_PORTS = {"https": 443, "http": 80}
_idle: dict[tuple[str, str, int], list[tuple[http.client.HTTPConnection, float]]] = {}
_idle_lock = threading.Lock()

# The connection was closed by the other side before it answered. On a reused connection this
# means the provider had already dropped it while idle, so the request never arrived.
_STALE_CONNECTION = (http.client.RemoteDisconnected, ConnectionResetError, ConnectionAbortedError,
                     BrokenPipeError)


class ExternalCallBlocked(BaseException):
    """An external request was attempted while external HTTP is blocked.

    Derives from BaseException so provider error handling cannot swallow it: a blocked
    call must fail the test or CI run that caused it.
    """


class ProviderTimeout(TimeoutError):
    pass


class ProviderUnreachable(OSError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def post(url: str, *, headers: dict[str, str], body: bytes, timeout_seconds: float) -> HttpResponse:
    """POST and return the response, including non-2xx responses.

    Raises ProviderTimeout on timeout and ProviderUnreachable when no response arrives.
    """
    if env_bool("PIXEL_BLOCK_EXTERNAL_HTTP", default=False):
        # Only the host is reported; URLs can carry credentials in query strings.
        raise ExternalCallBlocked(f"External HTTP is blocked: {urlsplit(url).hostname}")

    parts = urlsplit(url)
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
        raise ProviderUnreachable("InvalidURL")
    host = (parts.scheme, parts.hostname, parts.port or _DEFAULT_PORTS[parts.scheme])
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")

    for attempt in (1, 2):
        connection, reused = _checkout(host, timeout_seconds)
        try:
            connection.request("POST", target, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read()
        except (TimeoutError, socket.timeout) as error:
            connection.close()
            raise ProviderTimeout(str(error)) from error
        except _STALE_CONNECTION as error:
            connection.close()
            if reused and attempt == 1:
                continue
            raise ProviderUnreachable(type(error).__name__) from error
        except (OSError, http.client.HTTPException) as error:
            connection.close()
            raise ProviderUnreachable(type(error).__name__) from error
        _checkin(host, connection, closing=response.will_close)
        return HttpResponse(status=response.status, body=data)
    raise ProviderUnreachable("RemoteDisconnected")  # pragma: no cover - the loop always returns or raises


def _checkout(host: tuple[str, str, int], timeout_seconds: float) -> tuple[http.client.HTTPConnection, bool]:
    """An idle connection to `host` if a recent one exists, otherwise a new one."""
    now = time.monotonic()
    with _idle_lock:
        idle = _idle.get(host, [])
        while idle:
            connection, since = idle.pop()
            if now - since <= MAX_IDLE_SECONDS:
                connection.timeout = timeout_seconds
                if connection.sock is not None:
                    connection.sock.settimeout(timeout_seconds)
                return connection, True
            connection.close()
    scheme, hostname, port = host
    if scheme == "https":
        return http.client.HTTPSConnection(hostname, port, timeout=timeout_seconds, context=_TLS), False
    return http.client.HTTPConnection(hostname, port, timeout=timeout_seconds), False


def _checkin(host: tuple[str, str, int], connection: http.client.HTTPConnection, *, closing: bool) -> None:
    if closing:
        connection.close()
        return
    with _idle_lock:
        idle = _idle.setdefault(host, [])
        if len(idle) >= MAX_IDLE_PER_HOST:
            connection.close()
            return
        idle.append((connection, time.monotonic()))


def close_idle_connections() -> None:
    """Drop every kept connection (used by tests, and safe to call at shutdown)."""
    with _idle_lock:
        for idle in _idle.values():
            for connection, _ in idle:
                connection.close()
        _idle.clear()
