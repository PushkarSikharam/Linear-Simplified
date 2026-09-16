from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductConfig:
    id: str
    name: str
    docs_path: str
    allowed_actions: frozenset[str]
    # Speaking style given to style-steerable speech models for this product's assistant.
    voice_style: str


LINEAR_SIMPLIFIED = ProductConfig(
    id="linear_simplified",
    name="Pixel",
    docs_path="docs/product",
    voice_style=(
        "You are Edith, a soft-spoken, warm, gentle, and natural conversational assistant for Pixel. "
        "Speak in a soft, calm, friendly female voice with unhurried conversational cadence:"
    ),
    allowed_actions=frozenset(
        {
            "OPEN_DASHBOARD",
            "OPEN_ISSUES",
            "OPEN_PROJECTS",
            "OPEN_CYCLES",
            "OPEN_TEAMS",
            "OPEN_INTEGRATIONS",
            "OPEN_SYSTEM_ARCHITECTURE",
            "OPEN_DEMO_ISSUE",
            "CREATE_DEMO_ISSUE",
            "UPDATE_DEMO_ISSUE",
            "FILTER_ISSUES_BY_ASSIGNEE",
            "HIGHLIGHT_ASSIGNMENT_CONTROL",
            "HIGHLIGHT_CREATE_TICKET_BUTTON",
            "HIGHLIGHT_ADD_MEMBER_BUTTON",
            "HIGHLIGHT_CYCLE_PROGRESS",
            "OPEN_GITHUB_SETUP",
            "HIGHLIGHT_GITHUB_CARD",
            "HIGHLIGHT_SLACK_CARD",
        }
    ),
)

PRODUCTS_BY_ID = {
    LINEAR_SIMPLIFIED.id: LINEAR_SIMPLIFIED,
}
