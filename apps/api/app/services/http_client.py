"""The single path platform code uses to call external providers.

Keeping outbound HTTP in one place lets tests and CI block every real provider call:
with ``PIXEL_BLOCK_EXTERNAL_HTTP=true`` any attempt raises ``ExternalCallBlocked``.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.services.env import env_bool


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

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return HttpResponse(status=response.status, body=response.read())
    except urllib.error.HTTPError as error:
        return HttpResponse(status=error.code, body=error.read())
    except (TimeoutError, socket.timeout) as error:
        raise ProviderTimeout(str(error)) from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise ProviderTimeout(str(error.reason)) from error
        raise ProviderUnreachable(type(error.reason).__name__) from error
