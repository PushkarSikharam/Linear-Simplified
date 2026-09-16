"""String rules for untrusted definition content.

Definitions are validated as untrusted input even while they live in Git: tenant-editable
definitions are a future step, and definition text reaches model prompts and the browser.
The rules are allowlists, so anything that could act as a URL, path, selector, markup or
pattern is rejected rather than escaped.
"""
from __future__ import annotations

import re

from app.definitions.vocabulary import RESPONSE_PLACEHOLDERS

# Literal matching terms: lowercase words separated by single spaces, apostrophes or hyphens.
_TERM = re.compile(r"[a-z0-9]+(?:[ '-][a-z0-9]+)*")
# Keys that name definition elements: views, entities, fields, controls, actions.
_KEY = re.compile(r"[a-z][a-z0-9_]{0,47}")
# Organization, team and product identifiers (lowercase, hyphenated).
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
# Enumerated field values shown to people.
_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 -]{0,39}")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_PATH_LIKE = re.compile(r"(?:^|\s)(?:\.{1,2}/|~/|/)")
_FORBIDDEN_FRAGMENTS = ("://", "www.", "\\", "<", ">", "`", "javascript:", "data:", "file:")


def check_key(value: str) -> str:
    if not _KEY.fullmatch(value):
        raise ValueError("must be a lowercase key of letters, digits and underscores")
    return value


def check_slug(value: str) -> str:
    if not _SLUG.fullmatch(value):
        raise ValueError("must be a lowercase identifier of letters, digits and hyphens")
    return value


def check_term(value: str) -> str:
    """A literal term. No patterns, wildcards, selectors, paths or URLs can pass."""
    if len(value) > 60 or not _TERM.fullmatch(value):
        raise ValueError("must be a literal lowercase term (letters, digits, spaces, apostrophes, hyphens)")
    return value


def check_value(value: str) -> str:
    if not _VALUE.fullmatch(value):
        raise ValueError("must be a short value of letters, digits, spaces and hyphens")
    return value


def check_text(value: str) -> str:
    """Plain display or prompt text without placeholders."""
    _check_plain(value)
    if "{" in value or "}" in value:
        raise ValueError("must not contain braces")
    return value


def check_template(value: str) -> str:
    """Plain text whose only markup is placeholders from the platform vocabulary."""
    _check_plain(value)
    unknown = set(_PLACEHOLDER.findall(value)) - RESPONSE_PLACEHOLDERS
    if unknown:
        raise ValueError(f"uses unknown placeholders: {', '.join(sorted(unknown))}")
    if "{" in _PLACEHOLDER.sub("", value) or "}" in _PLACEHOLDER.sub("", value):
        raise ValueError("has unbalanced braces")
    return value


def _check_plain(value: str) -> None:
    if not value.strip():
        raise ValueError("must not be blank")
    if _CONTROL_CHARACTERS.search(value):
        raise ValueError("must not contain control characters")
    lowered = value.lower()
    for fragment in _FORBIDDEN_FRAGMENTS:
        if fragment in lowered:
            raise ValueError(f"must not contain {fragment!r} (no URLs, paths or markup)")
    if _PATH_LIKE.search(value):
        raise ValueError("must not contain file or route paths")
