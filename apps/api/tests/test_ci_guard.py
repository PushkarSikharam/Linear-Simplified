"""CI evidence that paid providers cannot be reached. Runs only when CI=true."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import http_client
from app.services.env import env_bool
from app.services.speech_providers import AzureSpeech, GeminiSpeech, OpenAISpeech


@unittest.skipUnless(os.environ.get("CI") == "true", "CI-only guard")
class CiProviderGuardTest(unittest.TestCase):
    def test_paid_providers_are_switched_off(self):
        self.assertFalse(env_bool("PIXEL_PAID_PROVIDERS_ENABLED", default=True))
        self.assertFalse(env_bool("LLM_ENABLED", default=True))

    def test_no_provider_credentials_are_present(self):
        for name in ("AZURE_SPEECH_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
            self.assertFalse(os.environ.get(name), f"{name} must not be set in CI")

    def test_outbound_provider_requests_fail_loudly(self):
        self.assertTrue(env_bool("PIXEL_BLOCK_EXTERNAL_HTTP", default=False))
        for provider in (AzureSpeech("k", "eastus", "voice", "fmt"), GeminiSpeech("k", "style"), OpenAISpeech("k")):
            with self.assertRaises(http_client.ExternalCallBlocked):
                provider.synthesize("CI guard")


if __name__ == "__main__":
    unittest.main()
