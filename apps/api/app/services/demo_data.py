from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services.language_normalizer import normalize_for_intent


@dataclass(frozen=True)
class DemoIssue:
    id: str
    title: str
    priority: str
    assignee: str
    project: str
    status: str


ROOT_DIR = Path(__file__).resolve().parents[4]
ISSUES_PATH = ROOT_DIR / "packages" / "shared" / "demo-data" / "issues.json"


@lru_cache(maxsize=1)
def load_demo_issues() -> tuple[DemoIssue, ...]:
    raw_issues = json.loads(ISSUES_PATH.read_text(encoding="utf-8"))
    return tuple(DemoIssue(**issue) for issue in raw_issues)


def issue_exists(issue_id: str) -> bool:
    return any(issue.id == issue_id for issue in load_demo_issues())


def find_issues_by_person(message: str) -> tuple[DemoIssue, ...]:
    normalized_message = normalize_for_intent(message)
    matched_issues: list[DemoIssue] = []
    for issue in load_demo_issues():
        assignee_parts = _name_parts(issue.assignee)
        if any(part in normalized_message for part in assignee_parts):
            matched_issues.append(issue)
    return tuple(matched_issues)


def find_issue_by_person(message: str) -> DemoIssue | None:
    issues = find_issues_by_person(message)
    return issues[0] if issues else None


def extract_unknown_person(message: str) -> str | None:
    patterns = (
        r"\b(?:for|assigned to|assign to|created for|ticket for|issue for)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)",
        r"\b([a-zA-Z]+)'s\s+(?:ticket|issue|bug)",
    )
    stop_words = {"about", "regarding", "named", "with", "on", "for", "to", "in", "at", "login", "bug", "issue", "ticket", "fresh", "new"}
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            words = candidate.split()
            filtered_words = []
            for w in words:
                if w.lower() in stop_words:
                    break
                filtered_words.append(w)
            if filtered_words:
                result = " ".join(filtered_words).title()
                if result.lower() not in {"jira", "linear", "salesforce", "github", "slack", "me", "us", "a", "the", "user", "users"}:
                    return result
    return None


def extract_requested_assignee(message: str) -> str:
    issue = find_issue_by_person(message)
    if issue:
        return issue.assignee

    unknown = extract_unknown_person(message)
    if unknown:
        return unknown

    return "Maya Chen"


def _name_parts(name: str) -> set[str]:
    normalized_name = _normalize(name)
    parts = set(normalized_name.split())
    parts.add(normalized_name)
    return parts


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", value.lower()).strip()
