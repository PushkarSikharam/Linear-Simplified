from __future__ import annotations

from app.schemas import IntentTrace, Signal
from app.services.language_normalizer import normalize_for_intent


class ReasoningPolicy:
    """Lightweight reasoning pass that enriches intent without authorizing actions."""

    def refine(
        self,
        message: str,
        intent_trace: IntentTrace,
        signals: list[Signal],
    ) -> tuple[IntentTrace, list[Signal]]:
        text = normalize_for_intent(message)
        refined = intent_trace.model_copy()
        refined_signals = [*signals]

        if self._mentions_conversation_control(text):
            refined.goal = "Live demo control"
            refined.current_intent = "Understand voice interaction"
            refined.relevant_feature = "Voice"
            refined.reason = "The visitor is asking how interruption or live voice control works."
            refined.confidence = max(refined.confidence, 0.82)
            refined_signals.append(
                Signal(type="feature_interest", value="voice", confidence=0.82)
            )

        if self._mentions_team_process(text):
            refined.goal = refined.goal or "Team workflow"
            refined.current_intent = refined.current_intent or "Understand workflow"
            refined.reason = (
                "The visitor is exploring how team work moves through the product."
            )
            refined.confidence = max(refined.confidence, 0.78)

        return refined, refined_signals

    def _mentions_conversation_control(self, text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "interrupt",
                "stop speaking",
                "while you are speaking",
                "listen to me",
                "voice interaction",
                "live voice",
            )
        )

    def _mentions_team_process(self, text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "how should my team",
                "best practice",
                "process",
                "workflow",
                "handoff",
            )
        )
