from __future__ import annotations

import re
from difflib import get_close_matches


PRODUCT_VOCABULARY = {
    "assignee",
    "assign",
    "assigned",
    "assignment",
    "bug",
    "bugs",
    "capacity",
    "cycle",
    "cycles",
    "developer",
    "github",
    "integration",
    "integrations",
    "issue",
    "issues",
    "jira",
    "linear",
    "maya",
    "planning",
    "project",
    "projects",
    "roadmap",
    "slack",
    "sprint",
    "team",
    "ticket",
    "tickets",
    "triage",
    "workload",
}

DIRECT_REPLACEMENTS = {
    "assigne": "assignee",
    "assigneee": "assignee",
    "cicle": "cycle",
    "cicles": "cycles",
    "git hub": "github",
    "issus": "issues",
    "jiraa": "jira",
    "mayas": "maya",
    "planing": "planning",
    "projet": "project",
    "projets": "projects",
    "sprit": "sprint",
    "tikcet": "ticket",
    "tiket": "ticket",
    "tikit": "ticket",
    "tkt": "ticket",
}

CORRECTION_MARKERS = (
    "actually",
    "instead",
    "rather",
    "i mean",
    "sorry",
    "scratch that",
)

NEGATED_FEATURE_TERMS = (
    "cycle",
    "cycles",
    "sprint",
    "planning",
    "issue",
    "issues",
    "ticket",
    "tickets",
    "project",
    "projects",
    "team",
    "teams",
    "integration",
    "integrations",
    "github",
)


def normalize_for_intent(message: str) -> str:
    text = _basic_normalize(message)
    text = _prefer_correction_clause(text)
    text = _drop_negated_feature_terms(text)
    text = _correct_words(text)
    return re.sub(r"\s+", " ", text).strip()


def _basic_normalize(message: str) -> str:
    text = message.lower().replace("'", "")
    for source, target in DIRECT_REPLACEMENTS.items():
        text = re.sub(rf"\b{re.escape(source)}\b", target, text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _prefer_correction_clause(text: str) -> str:
    selected = text
    for marker in CORRECTION_MARKERS:
        pattern = rf"\b{re.escape(marker)}\b"
        matches = list(re.finditer(pattern, selected))
        if matches:
            selected = selected[matches[-1].end() :].strip()

    if selected.startswith("no ") and len(selected.split()) > 2:
        selected = selected[3:].strip()

    return selected or text


def _drop_negated_feature_terms(text: str) -> str:
    feature_pattern = "|".join(re.escape(term) for term in NEGATED_FEATURE_TERMS)
    return re.sub(
        rf"\b(?:no|not|dont|do not)\s+(?:the\s+)?(?:{feature_pattern})\b",
        " ",
        text,
    )


def _correct_words(text: str) -> str:
    corrected_words: list[str] = []
    for word in text.split():
        if word in PRODUCT_VOCABULARY or word.isdigit() or len(word) <= 2:
            corrected_words.append(word)
            continue

        match = get_close_matches(word, PRODUCT_VOCABULARY, n=1, cutoff=0.84)
        corrected_words.append(match[0] if match else word)

    return " ".join(corrected_words)
