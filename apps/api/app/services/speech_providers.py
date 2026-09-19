"""Neural speech providers. Only the speech service may call these, after reserving usage."""
from __future__ import annotations

import base64
import json
import struct
from dataclasses import dataclass
from html import escape
from typing import Protocol

from app.services import http_client
from app.services.env import env_value
from app.tenancy import ProductContext

PROVIDER_TIMEOUT_SECONDS = 4.0


@dataclass(frozen=True)
class SynthesizedSpeech:
    audio: bytes
    media_type: str
    engine: str
    voice: str | None = None


class SpeechProviderError(Exception):
    """A dispatched attempt that produced no audio."""

    def __init__(self, status: str, reason: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(reason)
        self.status = status  # "failed" or "timeout"
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds


class SpeechProvider(Protocol):
    name: str
    model: str

    def synthesize(self, text: str) -> SynthesizedSpeech: ...


SPEECH_PROVIDER_NAMES = ("azure", "gemini", "openai")
# Azure alone speaks unless another voice is listed on purpose. A configured key is not consent:
# the Gemini key is also the reasoning key, and a second voice mid-conversation is a different
# person, not a fallback. When Azure cannot answer, the browser's own voice takes over for free.
DEFAULT_SPEECH_PROVIDERS = ("azure",)


def speech_provider_names() -> list[str]:
    """The cloud voices allowed to speak, in order (`PIXEL_SPEECH_PROVIDERS`, comma-separated)."""
    listed = env_value("PIXEL_SPEECH_PROVIDERS")
    names = [name.strip().lower() for name in listed.split(",")] if listed else DEFAULT_SPEECH_PROVIDERS
    return [name for name in dict.fromkeys(names) if name in SPEECH_PROVIDER_NAMES]


def configured_speech_providers(owner: ProductContext, voice_style: str) -> list[SpeechProvider]:
    """Providers in fallback order for one product: the allowed voices that have credentials.

    `voice_style` comes from the product's pinned definition. Credentials and voices still
    come from deployment configuration; `owner` is the seam for per-product provider settings.
    """
    providers: list[SpeechProvider] = []
    for name in speech_provider_names():
        if name == "azure":
            azure_key, azure_region = env_value("AZURE_SPEECH_KEY"), env_value("AZURE_SPEECH_REGION")
            if azure_key and azure_region:
                providers.append(AzureSpeech(
                    key=azure_key,
                    region=azure_region,
                    voice=env_value("AZURE_SPEECH_VOICE_NAME") or "en-US-AvaMultilingualNeural",
                    output_format=env_value("AZURE_SPEECH_OUTPUT_FORMAT") or "audio-24khz-48kbitrate-mono-mp3",
                ))
        elif name == "gemini":
            if gemini_key := env_value("GEMINI_API_KEY"):
                providers.append(GeminiSpeech(key=gemini_key, style=voice_style))
        elif name == "openai":
            if openai_key := env_value("OPENAI_API_KEY"):
                providers.append(OpenAISpeech(key=openai_key))
    return providers


def _post(url: str, headers: dict[str, str], body: bytes) -> http_client.HttpResponse:
    try:
        return http_client.post(url, headers=headers, body=body, timeout_seconds=PROVIDER_TIMEOUT_SECONDS)
    except http_client.ProviderTimeout as error:
        raise SpeechProviderError("timeout", "timeout") from error
    except http_client.ProviderUnreachable as error:
        raise SpeechProviderError("failed", "unreachable") from error


@dataclass(frozen=True)
class AzureSpeech:
    key: str
    region: str
    voice: str
    output_format: str
    name: str = "azure"

    @property
    def model(self) -> str:
        return self.voice

    def synthesize(self, text: str) -> SynthesizedSpeech:
        response = _post(
            f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1",
            {
                "Content-Type": "application/ssml+xml",
                "Ocp-Apim-Subscription-Key": self.key,
                "X-Microsoft-OutputFormat": self.output_format,
                "User-Agent": "Pixel",
            },
            self.ssml(text).encode("utf-8"),
        )
        if not response.ok:
            raise SpeechProviderError("failed", f"http_{response.status}")
        return SynthesizedSpeech(response.body, "audio/mpeg", "azure-speech", self.voice)

    def ssml(self, text: str) -> str:
        voice, spoken = escape(self.voice, quote=True), escape(text, quote=True)
        if ":DragonHD" in self.voice:
            return (
                '<speak version="1.0" xml:lang="en-US">'
                f'<voice xml:lang="en-US" xml:gender="Female" name="{voice}">'
                f'<prosody rate="-2%" pitch="+0%">{spoken}</prosody></voice></speak>'
            )
        return (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            'xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="en-US">'
            f'<voice name="{voice}"><mstts:express-as style="chat">'
            f'<prosody rate="-4%" pitch="+0%">{spoken}</prosody>'
            "</mstts:express-as></voice></speak>"
        )


@dataclass(frozen=True)
class GeminiSpeech:
    key: str
    style: str
    name: str = "gemini"
    model: str = "gemini-2.5-flash-preview-tts"
    voice: str = "Aoede"
    sample_rate: int = 24_000

    def synthesize(self, text: str) -> SynthesizedSpeech:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": f"{self.style}\n\n{text}"}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}},
            },
        }
        response = _post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            {"Content-Type": "application/json", "x-goog-api-key": self.key},
            json.dumps(payload).encode("utf-8"),
        )
        if response.status == 429:
            raise SpeechProviderError("failed", "http_429", retry_after_seconds=5.0)
        if not response.ok:
            raise SpeechProviderError("failed", f"http_{response.status}")
        try:
            encoded = response.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            pcm = base64.b64decode(encoded)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise SpeechProviderError("failed", "malformed_response") from error
        return SynthesizedSpeech(pcm_to_wav(pcm, self.sample_rate), "audio/wav", "gemini-2.5-flash", self.voice)


@dataclass(frozen=True)
class OpenAISpeech:
    key: str
    name: str = "openai"
    model: str = "tts-1"
    voice: str = "coral"

    def synthesize(self, text: str) -> SynthesizedSpeech:
        response = _post(
            "https://api.openai.com/v1/audio/speech",
            {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
            json.dumps({"model": self.model, "voice": self.voice, "input": text}).encode("utf-8"),
        )
        if not response.ok:
            raise SpeechProviderError("failed", f"http_{response.status}")
        return SynthesizedSpeech(response.body, "audio/mpeg", "openai-tts", self.voice)


def pcm_to_wav(pcm: bytes, sample_rate: int, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Wrap raw little-endian PCM samples in a WAV header."""
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, channels,
        sample_rate, byte_rate, block_align, bits_per_sample, b"data", len(pcm),
    )
    return header + pcm
