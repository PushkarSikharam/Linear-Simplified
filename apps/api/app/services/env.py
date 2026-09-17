from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


PLACEHOLDER_VALUES = {
    "your_gemini_api_key_here",
    "your_azure_speech_key_here",
    "your_openai_api_key_here",
}

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]


# Only the API's own developer files. The web app's env files are never read, so provider
# credentials cannot live next to browser configuration.
API_ENV_FILES = (REPO_ROOT / ".env.local", REPO_ROOT / ".env")


@lru_cache(maxsize=1)
def _env_files() -> tuple[dict[str, str], ...]:
    return tuple(_read_env_file(path) for path in API_ENV_FILES)


def env_value(name: str) -> str | None:
    value = _clean(os.getenv(name))
    if value:
        return value

    # Hermetic runs (tests, CI) must not pick up a developer's local files or keys.
    if _clean(os.getenv("PIXEL_IGNORE_ENV_FILES")) in {"1", "true", "yes", "on"}:
        return None

    for env_file in _env_files():
        value = _clean(env_file.get(name))
        if value:
            return value

    return None


def env_bool(name: str, default: bool = False) -> bool:
    value = env_value(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = env_value(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _clean(value: str | None) -> str | None:
    cleaned = value.strip().strip('"').strip("'") if value else ""
    if not cleaned or cleaned in PLACEHOLDER_VALUES:
        return None
    return cleaned


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()
    except OSError:
        return {}
    return values
