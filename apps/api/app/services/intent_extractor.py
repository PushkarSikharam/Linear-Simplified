from __future__ import annotations

import re

from app.schemas import IntentTrace, Signal
from app.services.language_normalizer import normalize_for_intent


class IntentExtractor:
    def extract(self, message: str) -> tuple[IntentTrace, list[Signal]]:
        text = normalize_for_intent(message)
        trace = IntentTrace(
            role=self._role(text),
            team_size=self._team_size(text),
            current_tool=self._current_tool(text),
            goal=self._goal(text),
            pain_point=self._pain_point(text),
            current_intent=self._current_intent(text),
            relevant_feature=self._relevant_feature(text),
            confidence=0.72,
        )
        trace.reason = self._reason(trace)
        signals = self._signals(trace)
        return trace, signals

    def _role(self, text: str) -> str | None:
        if (
            "engineering manager" in text
            or "i manage" in text
            or "i'm a manager" in text
            or "i am a manager" in text
        ):
            return "Engineering Manager"
        if (
            "i'm a developer" in text
            or "i am a developer" in text
            or "i'm a software developer" in text
            or "i am a software developer" in text
            or "as a developer" in text
            or "as an engineer" in text
        ):
            return "Software Developer"
        if "product manager" in text or "i'm a pm" in text or "i am a pm" in text:
            return "Product Manager"
        return None

    def _team_size(self, text: str) -> int | None:
        match = re.search(r"\b(\d{1,3})[- ]?(person|people|dev|developer|engineer|member|team)", text)
        if not match:
            return None
        return int(match.group(1))

    def _current_tool(self, text: str) -> str | None:
        if "jira" in text:
            return "Jira"
        if "pixel" in text:
            return "Pixel"
        if "asana" in text:
            return "Asana"
        if "trello" in text:
            return "Trello"
        return None

    def _goal(self, text: str) -> str | None:
        if self._mentions_cycle(text):
            return "Sprint planning"
        if self._mentions_issue(text):
            return "Bug tracking"
        if "project" in text or "roadmap" in text:
            return "Project tracking"
        if "integration" in text or "github" in text or "slack" in text:
            return "Connected workflow"
        return None

    def _pain_point(self, text: str) -> str | None:
        if "messy" in text or "complex" in text or "too much" in text or "confusing" in text:
            return "Workflow complexity"
        if "migration" in text or "migrate" in text or "switching" in text:
            return "Migration effort"
        return None

    def _current_intent(self, text: str) -> str | None:
        if "show" in text or "open" in text:
            return "Navigate demo"
        if "how" in text or "explain" in text:
            return "Understand workflow"
        return "Discovery"

    def _relevant_feature(self, text: str) -> str | None:
        if self._mentions_cycle(text):
            return "Cycles"
        if self._mentions_issue(text):
            return "Issues"
        if "project" in text or "roadmap" in text:
            return "Projects"
        if "team" in text or "capacity" in text or "workload" in text:
            return "Teams"
        if "integration" in text or "github" in text or "slack" in text:
            return "Integrations"
        return None

    def _reason(self, trace: IntentTrace) -> str:
        if trace.relevant_feature == "Cycles":
            return "Showing Cycles because the visitor asked about sprint planning."
        if trace.relevant_feature == "Issues":
            return "Showing Issues because the visitor asked about bug or issue tracking."
        if trace.relevant_feature == "Projects":
            return "Showing Projects because the visitor asked about roadmap or project work."
        if trace.relevant_feature == "Teams":
            return "Showing Teams because the visitor asked about people, workload, or capacity."
        if trace.relevant_feature == "Integrations":
            return "Showing Integrations because the visitor asked about connected tools."
        return "Staying on the current view until a product workflow is clear."

    def _signals(self, trace: IntentTrace) -> list[Signal]:
        signals: list[Signal] = []
        if trace.relevant_feature:
            signals.append(
                Signal(
                    type="feature_interest",
                    value=trace.relevant_feature.lower(),
                    confidence=max(trace.confidence, 0.7),
                )
            )
        if trace.pain_point:
            signals.append(
                Signal(
                    type="pain_point",
                    value=trace.pain_point.lower(),
                    confidence=0.78,
                )
            )
        return signals

    def _mentions_cycle(self, text: str) -> bool:
        return any(term in text for term in ("sprint", "cycle", "planning", "burndown"))

    def _mentions_issue(self, text: str) -> bool:
        return any(term in text for term in ("bug", "issue", "ticket", "triage", "assign"))
