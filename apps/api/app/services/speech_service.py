"""Speech synthesis with provider fallback, owned by the API.

Every provider attempt, fallbacks included, reserves usage first. Nothing is sent when
reservation is refused or accounting is unavailable. Dispatched attempts stay counted.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from uuid import uuid4

from app.services.speech_providers import (
    SpeechProvider,
    SpeechProviderError,
    SynthesizedSpeech,
    configured_speech_providers,
)
from app.services.usage_ledger import (
    AccountingUnavailable,
    AttemptRequest,
    BudgetExceeded,
    UsageLedger,
    logger as usage_logger,
)
from app.tenancy import TenantContext


class SpeechUnavailable(Exception):
    """No audio could be produced; ``reason`` is a stable, UI-safe code."""

    def __init__(self, status_code: int, reason: str) -> None:
        super().__init__(reason)
        self.status_code = status_code
        self.reason = reason


class SpeechService:
    def __init__(
        self,
        ledger: UsageLedger | None = None,
        providers: Callable[[TenantContext], list[SpeechProvider]] = configured_speech_providers,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ledger = ledger or UsageLedger()
        self._providers = providers
        self._clock = clock
        # Providers that asked us to back off, keyed by tenant and provider.
        self._cooldown_until: dict[tuple[str, str], float] = {}

    def synthesize(
        self,
        *,
        tenant: TenantContext,
        user_id: str,
        session_id: str | None,
        text: str,
    ) -> SynthesizedSpeech:
        providers = [provider for provider in self._providers(tenant) if not self._cooling_down(tenant, provider)]
        if not providers:
            raise SpeechUnavailable(503, "no_provider_available")

        request_id = str(uuid4())
        for provider in providers:
            attempt_id = self._reserve(tenant, user_id, session_id, request_id, provider, len(text))
            started = self._clock()
            try:
                speech = provider.synthesize(text)
            except SpeechProviderError as error:
                self._settle(attempt_id, tenant, error.status, started, error.reason)
                if error.retry_after_seconds:
                    self._cooldown_until[(tenant.tenant_id, provider.name)] = self._clock() + error.retry_after_seconds
                continue
            except BaseException as error:
                self._settle(attempt_id, tenant, "failed", started, type(error).__name__)
                raise
            self._settle(attempt_id, tenant, "succeeded", started)
            return speech

        raise SpeechUnavailable(502, "all_providers_failed")

    def _reserve(
        self,
        tenant: TenantContext,
        user_id: str,
        session_id: str | None,
        request_id: str,
        provider: SpeechProvider,
        characters: int,
    ) -> str:
        try:
            return self._ledger.reserve(AttemptRequest(
                tenant=tenant,
                user_id=user_id,
                request_id=request_id,
                capability="speech",
                provider=provider.name,
                model=provider.model,
                session_id=session_id,
                reserved_units=characters,
            ))
        except BudgetExceeded as refusal:
            raise SpeechUnavailable(429, refusal.reason) from refusal
        except AccountingUnavailable as error:
            raise SpeechUnavailable(503, "accounting_unavailable") from error

    def _settle(self, attempt_id: str, tenant: TenantContext, status: str, started: float,
                reason: str | None = None) -> None:
        # Providers report no character usage, so actual units stay empty rather than
        # repeating our own count as if the provider had reported it.
        try:
            self._ledger.settle(
                attempt_id,
                tenant,
                status,
                duration_ms=int((self._clock() - started) * 1000),
                reason=reason,
            )
        except Exception as error:
            # The attempt was dispatched; an unsettled reservation simply stays consumed.
            usage_logger.warning(json.dumps({
                "event": "settle_failed", "attempt_id": attempt_id, "error": type(error).__name__,
            }))

    def _cooling_down(self, tenant: TenantContext, provider: SpeechProvider) -> bool:
        return self._clock() < self._cooldown_until.get((tenant.tenant_id, provider.name), 0.0)
