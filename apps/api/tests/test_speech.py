"""Milestone 2: speech synthesis owned by the API. Fake providers only; no network calls."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app import main
from app.auth import create_token
from app.services import http_client
from app.services import usage_ledger as ledger_module
from app.services.session_manager import SessionManager
from app.services.speech_providers import (
    AzureSpeech,
    GeminiSpeech,
    OpenAISpeech,
    SpeechProviderError,
    SynthesizedSpeech,
    configured_speech_providers,
    pcm_to_wav,
)
from app.services.speech_service import SpeechService, SpeechUnavailable
from test_usage_ledger import LedgerFixture, OTHER_TENANT, SECRET_MESSAGE


@dataclass
class FakeProvider:
    name: str
    outcomes: list = field(default_factory=list)  # SynthesizedSpeech or exception per call
    model: str = "fake-model"
    calls: list[str] = field(default_factory=list)

    def synthesize(self, text: str) -> SynthesizedSpeech:
        self.calls.append(text)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def audio(engine: str) -> SynthesizedSpeech:
    return SynthesizedSpeech(b"ID3-fake", "audio/mpeg", engine, "fake-voice")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class SpeechServiceTest(LedgerFixture):
    def service(self, *providers: FakeProvider, clock=None) -> SpeechService:
        return SpeechService(self.ledger, providers=lambda tenant: list(providers), clock=clock or Clock())

    def synthesize(self, service: SpeechService, tenant=None, text="Hello there"):
        return service.synthesize(tenant=tenant or self.tenant, user_id="demo-product-eng",
                                  session_id="session-1", text=text)

    def test_success_is_reserved_first_and_attributed(self):
        azure = FakeProvider("azure", [audio("azure-speech")])
        speech = self.synthesize(self.service(azure))
        self.assertEqual(speech.engine, "azure-speech")
        row = self.rows()[0]
        self.assertEqual((row["status"], row["capability"], row["unit"]), ("succeeded", "speech", "characters"))
        self.assertEqual((row["reserved_units"], row["session_id"], row["tenant_id"]), (11, "session-1", "pixel-dev"))
        self.assertIsNone(row["actual_units"], "providers report no usage, so none is recorded")

    def test_fallback_attempts_are_each_reserved(self):
        azure = FakeProvider("azure", [SpeechProviderError("failed", "http_500")])
        gemini = FakeProvider("gemini", [audio("gemini-2.5-flash")])
        speech = self.synthesize(self.service(azure, gemini))
        self.assertEqual(speech.engine, "gemini-2.5-flash")
        self.assertEqual([(row["provider"], row["status"]) for row in self.rows()],
                         [("azure", "failed"), ("gemini", "succeeded")])

    def test_third_provider_is_never_called(self):
        failing = SpeechProviderError("failed", "http_500")
        providers = [FakeProvider(name, [failing]) for name in ("azure", "gemini", "openai")]
        with self.assertRaises(SpeechUnavailable) as unavailable:
            self.synthesize(self.service(*providers))
        self.assertEqual((unavailable.exception.status_code, unavailable.exception.reason),
                         (429, "request_attempt_limit"))
        self.assertEqual(providers[2].calls, [])

    def test_timeouts_are_recorded_as_consumed(self):
        azure = FakeProvider("azure", [SpeechProviderError("timeout", "timeout")])
        with self.assertRaises(SpeechUnavailable) as unavailable:
            self.synthesize(self.service(azure))
        self.assertEqual(unavailable.exception.status_code, 502)
        self.assertEqual(self.statuses(), ["timeout"])

    def test_kill_switch_refuses_before_any_dispatch(self):
        os.environ["PIXEL_PAID_PROVIDERS_ENABLED"] = "false"
        azure = FakeProvider("azure", [audio("azure-speech")])
        with self.assertRaises(SpeechUnavailable) as unavailable:
            self.synthesize(self.service(azure))
        self.assertEqual((unavailable.exception.status_code, unavailable.exception.reason),
                         (429, "providers_disabled"))
        self.assertEqual(azure.calls, [])

    def test_accounting_outage_refuses_before_any_dispatch(self):
        azure = FakeProvider("azure", [audio("azure-speech")])

        def broken_connection():
            raise sqlite3.OperationalError("disk I/O error")

        with patch.object(ledger_module, "get_connection", broken_connection):
            with self.assertRaises(SpeechUnavailable) as unavailable:
                self.synthesize(self.service(azure))
        self.assertEqual(unavailable.exception.status_code, 503)
        self.assertEqual(azure.calls, [])

    def test_oversized_text_is_refused_before_any_dispatch(self):
        azure = FakeProvider("azure", [audio("azure-speech")])
        with self.assertRaises(SpeechUnavailable) as unavailable:
            self.synthesize(self.service(azure), text="x" * 2001)
        self.assertEqual(unavailable.exception.reason, "attempt_too_large")
        self.assertEqual(azure.calls, [])

    def test_provider_backoff_is_honoured_per_tenant(self):
        clock = Clock()
        gemini = FakeProvider("gemini", [
            SpeechProviderError("failed", "http_429", retry_after_seconds=5),
            audio("gemini-2.5-flash"),
            audio("gemini-2.5-flash"),
        ])
        service = self.service(gemini, clock=clock)
        with self.assertRaises(SpeechUnavailable):
            self.synthesize(service)
        with self.assertRaises(SpeechUnavailable) as cooling:
            self.synthesize(service)
        self.assertEqual(cooling.exception.reason, "no_provider_available")
        self.synthesize(service, tenant=OTHER_TENANT)  # other tenants are unaffected
        clock.now += 6
        self.synthesize(service)
        self.assertEqual(len(gemini.calls), 3)

    def test_blocked_external_call_fails_loudly_and_is_recorded(self):
        azure = FakeProvider("azure", [http_client.ExternalCallBlocked("blocked")])
        with self.assertRaises(http_client.ExternalCallBlocked):
            self.synthesize(self.service(azure))
        self.assertEqual(self.statuses(), ["failed"])


class SpeechProvidersTest(LedgerFixture):
    """Real provider classes, with outbound HTTP blocked or faked."""

    def test_real_providers_cannot_reach_the_network_in_tests(self):
        for provider in (AzureSpeech("k", "eastus", "voice", "fmt"), GeminiSpeech("k", "style"), OpenAISpeech("k")):
            with self.assertRaises(http_client.ExternalCallBlocked):
                provider.synthesize("Hello")

    def test_configured_providers_follow_fallback_order(self):
        os.environ.update({"AZURE_SPEECH_KEY": "a", "AZURE_SPEECH_REGION": "eastus",
                           "GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o"})
        providers = configured_speech_providers(self.tenant)
        self.assertEqual([provider.name for provider in providers], ["azure", "gemini", "openai"])
        self.assertIn("Edith", providers[1].style, "the voice persona comes from the product profile")

    def test_azure_escapes_text_into_ssml(self):
        ssml = AzureSpeech("k", "eastus", "en-US-Ava:DragonHDLatestNeural", "fmt").ssml('<break/> & "quotes"')
        self.assertIn("&lt;break/&gt; &amp; &quot;quotes&quot;", ssml)

    def test_gemini_keeps_the_key_out_of_the_url_and_returns_wav(self):
        sent = {}

        def fake_post(url, *, headers, body, timeout_seconds):
            sent.update(url=url, headers=headers)
            pcm = struct.pack("<4h", 0, 1, 2, 3)
            payload = {"candidates": [{"content": {"parts": [{"inlineData": {
                "data": __import__("base64").b64encode(pcm).decode()}}]}}]}
            return http_client.HttpResponse(200, json.dumps(payload).encode())

        with patch.object(http_client, "post", fake_post):
            speech = GeminiSpeech("secret-key", "style").synthesize("Hello")
        self.assertNotIn("secret-key", sent["url"])
        self.assertEqual(sent["headers"]["x-goog-api-key"], "secret-key")
        self.assertEqual((speech.media_type, speech.audio[:4]), ("audio/wav", b"RIFF"))

    def test_gemini_rate_limit_asks_for_backoff(self):
        with patch.object(http_client, "post", lambda *args, **kwargs: http_client.HttpResponse(429, b"")):
            with self.assertRaises(SpeechProviderError) as error:
                GeminiSpeech("k", "style").synthesize("Hello")
        self.assertEqual(error.exception.retry_after_seconds, 5.0)

    def test_provider_timeouts_are_classified(self):
        def timing_out(*args, **kwargs):
            raise http_client.ProviderTimeout("timed out")

        with patch.object(http_client, "post", timing_out):
            with self.assertRaises(SpeechProviderError) as error:
                OpenAISpeech("k").synthesize("Hello")
        self.assertEqual(error.exception.status, "timeout")

    def test_wav_header_describes_the_samples(self):
        wav = pcm_to_wav(b"\x00\x00" * 10, 24_000)
        self.assertEqual((wav[:4], wav[8:12], len(wav)), (b"RIFF", b"WAVE", 44 + 20))


class SpeechEndpointTest(LedgerFixture):
    def setUp(self):
        super().setUp()
        self.azure = FakeProvider("azure", [audio("azure-speech")])
        service_patch = patch.object(
            main, "speech_service", SpeechService(self.ledger, providers=lambda tenant: [self.azure])
        )
        service_patch.start()
        self.addCleanup(service_patch.stop)
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def post(self, body, user_id="demo-product-eng"):
        headers = {"Authorization": f"Bearer {create_token(user_id)}"}
        return self.client.post("/api/speech", json=body, headers=headers)

    def test_returns_private_audio_with_provider_headers(self):
        response = self.post({"text": "  Hello there  "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ID3-fake")
        self.assertEqual(response.headers["content-type"], "audio/mpeg")
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual((response.headers["x-tts-engine"], response.headers["x-tts-voice"]),
                         ("azure-speech", "fake-voice"))
        self.assertEqual(self.azure.calls, ["Hello there"])

    def test_requires_authentication(self):
        self.assertEqual(self.client.post("/api/speech", json={"text": "Hello"}).status_code, 401)

    def test_rejects_blank_or_oversized_text(self):
        self.assertEqual(self.post({"text": "   "}).status_code, 422)
        self.assertEqual(self.post({"text": "x" * 2001}).status_code, 422)
        self.assertEqual(self.azure.calls, [])

    def test_refusals_are_reported_without_audio(self):
        os.environ["PIXEL_PAID_PROVIDERS_ENABLED"] = "false"
        response = self.post({"text": "Hello"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["reason"], "providers_disabled")

    def test_only_the_callers_own_session_is_attributed(self):
        sessions = SessionManager()
        sessions.ensure_session("mine", "linear_simplified", user_id="demo-product-eng", tenant_id="pixel-dev")
        sessions.ensure_session("theirs", "linear_simplified", user_id="demo-platform", tenant_id="pixel-dev")
        self.azure.outcomes.append(audio("azure-speech"))
        self.post({"text": "Hello", "session_id": "mine"})
        self.post({"text": "Hello", "session_id": "theirs"})
        self.assertEqual([row["session_id"] for row in self.rows()], ["mine", None])

    def test_spoken_text_never_reaches_the_logs(self):
        with self.assertLogs("pixel.usage", level="INFO") as logs:
            self.post({"text": SECRET_MESSAGE})
        self.assertNotIn(SECRET_MESSAGE, "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
