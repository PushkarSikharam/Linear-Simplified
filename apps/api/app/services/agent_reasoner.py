from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.product_config import PRODUCTS_BY_ID
from app.schemas import IntentTrace, ProposedAction
from app.services.demo_data import load_demo_issues
from app.services.env import env_bool, env_int, env_value
from app.services.product_data_store import ProductDataStore
from app.services.retriever import RetrievedDocument
from app.workspace_config import WorkspaceScope


GeminiTransport = Callable[[str, dict[str, Any], int], dict[str, Any]]


class ReasonedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentReasoningResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speech: str = Field(min_length=1, max_length=700)
    proposed_action: ReasonedAction | None = None
    clarification_question: str | None = Field(default=None, max_length=220)
    intent_trace: IntentTrace


@dataclass(frozen=True)
class AgentReasoningContext:
    product_id: str
    message: str
    current_page: str | None
    selected_issue_id: str | None
    workspace_scope: WorkspaceScope
    retrieved_docs: list[RetrievedDocument]


class AgentReasoner:
    def __init__(self, transport: GeminiTransport | None = None) -> None:
        self.transport = transport or self._default_transport

    def enabled(self) -> bool:
        provider = (env_value("LLM_PROVIDER") or "gemini").lower()
        return (
            provider == "gemini"
            and env_bool("LLM_ENABLED", default=True)
            and bool(env_value("GEMINI_API_KEY"))
        )

    def reason(self, context: AgentReasoningContext) -> AgentReasoningResult | None:
        api_key = env_value("GEMINI_API_KEY")
        if not self.enabled() or not api_key:
            return None

        timeout_ms = env_int("LLM_TIMEOUT_MS", 15000)
        payload = self._payload(context)
        try:
            response = self.transport(api_key, payload, timeout_ms)
        except (OSError, TimeoutError, urllib.error.URLError, socket.timeout, ValueError):
            return None

        return self._parse_response(response)

    def _payload(self, context: AgentReasoningContext) -> dict[str, Any]:
        response_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "speech": {"type": "string"},
                "proposed_action": {
                    "nullable": True,
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "payload": {"type": "object"},
                    },
                    "required": ["type", "payload"],
                },
                "clarification_question": {"nullable": True, "type": "string"},
                "intent_trace": {
                    "type": "object",
                    "properties": {
                        "role": {"nullable": True, "type": "string"},
                        "team_size": {"nullable": True, "type": "integer"},
                        "current_tool": {"nullable": True, "type": "string"},
                        "goal": {"nullable": True, "type": "string"},
                        "pain_point": {"nullable": True, "type": "string"},
                        "current_intent": {"nullable": True, "type": "string"},
                        "relevant_feature": {"nullable": True, "type": "string"},
                        "reason": {"nullable": True, "type": "string"},
                        "confidence": {"type": "number"},
                        "status": {"type": "string"},
                    },
                    "required": ["confidence", "status"],
                },
            },
            "required": ["speech", "proposed_action", "clarification_question", "intent_trace"],
        }

        model = self._model_name()
        generation_config: dict[str, Any] = {
            "temperature": 0.1,
            "maxOutputTokens": 700,
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
        }
        if model.startswith("gemini-3"):
            generation_config["thinkingConfig"] = {
                "thinkingLevel": env_value("LLM_THINKING_LEVEL") or "minimal",
            }
        elif model.startswith("gemini-2.5"):
            generation_config["thinkingConfig"] = {
                "thinkingBudget": env_int("LLM_THINKING_BUDGET", 0),
            }

        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": self._prompt(context)}],
                }
            ],
            "generationConfig": generation_config,
        }

    def _prompt(self, context: AgentReasoningContext) -> str:
        product = PRODUCTS_BY_ID[context.product_id]
        visible = self._visible_workspace_data(context.workspace_scope)
        docs = "\n".join(
            f"- {doc.title}: {doc.snippet}"
            for doc in context.retrieved_docs[:2]
        ) or "- No retrieved product docs matched. Use the visible workspace data and allowed actions only."

        return (
            "You are Edith, the conversational demo agent for Pixel.\n"
            "Understand the visitor's intent and return only the requested JSON schema.\n"
            "Never claim you completed an action. Say what you will open, show, update, or ask next.\n"
            "You may propose exactly one action, or null if a clarification is better.\n"
            "Do not expose private reasoning. intent_trace must be short and UI-safe.\n"
            "Stay inside the active workspace. If the visitor asks for other workspaces or external apps, propose no action and explain the boundary.\n\n"
            f"Product: {product.name}\n"
            f"Current page: {context.current_page or 'unknown'}\n"
            f"Selected issue: {context.selected_issue_id or 'none'}\n"
            f"Workspace: {context.workspace_scope.name} - {context.workspace_scope.description}\n"
            f"Allowed actions: {', '.join(sorted(product.allowed_actions))}\n"
            f"Visible projects: {', '.join(visible['projects']) or 'none'}\n"
            f"Visible team members: {', '.join(visible['team']) or 'none'}\n"
            f"Visible issues: {', '.join(visible['issues']) or 'none'}\n"
            f"Product docs:\n{docs}\n\n"
            "Action hints:\n"
            "- Weekly planning, sprint planning, time-boxed work, capacity planning -> OPEN_CYCLES.\n"
            "- Customer bugs, tickets, work items, triage, assignment -> OPEN_ISSUES or issue actions.\n"
            "- Roadmap, initiatives, project progress -> OPEN_PROJECTS.\n"
            "- People, team members, capacity, workload -> OPEN_TEAMS.\n"
            "- GitHub, Slack, PRs, commits, connected tools -> integrations actions.\n"
            "- Architecture, system design, how Pixel works -> OPEN_SYSTEM_ARCHITECTURE.\n"
            "- Salesforce, Gmail, external CRM/email -> no action; explain Pixel-only boundary.\n\n"
            f"Visitor message: {context.message}"
        )

    def _visible_workspace_data(self, workspace_scope: WorkspaceScope) -> dict[str, list[str]]:
        allowed_project_ids = set(workspace_scope.allowed_project_ids)
        allowed_issue_projects = set(workspace_scope.allowed_issue_projects)
        data = ProductDataStore().load()

        projects = [
            str(project["name"])
            for project in data["projects"]
            if project.get("id") in allowed_project_ids
        ]
        team = [
            str(member["name"])
            for member in data["team"]
            if set(member.get("projectIds") or []).intersection(allowed_project_ids)
        ]
        issues = [
            f"{issue.id} {issue.title} ({issue.assignee}, {issue.project})"
            for issue in load_demo_issues()
            if (issue.projectId and issue.projectId in allowed_project_ids)
            or issue.project in allowed_issue_projects
        ]

        return {"projects": projects[:8], "team": team[:8], "issues": issues[:10]}

    def _parse_response(self, response: dict[str, Any]) -> AgentReasoningResult | None:
        text = response.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text")
        if not isinstance(text, str):
            return None

        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return None
            try:
                raw = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

        try:
            return AgentReasoningResult.model_validate(self._normalize_result(raw))
        except ValidationError:
            return None

    def _normalize_result(self, raw: dict[str, Any]) -> dict[str, Any]:
        normalized = {**raw}
        intent_trace = normalized.get("intent_trace")
        if isinstance(intent_trace, dict):
            normalized_trace = {**intent_trace}
            if normalized_trace.get("status") not in {"active", "interrupted", "denied"}:
                normalized_trace["status"] = "active"

            feature = normalized_trace.get("relevant_feature")
            if isinstance(feature, str):
                normalized_trace["relevant_feature"] = self._canonical_feature(feature)

            normalized["intent_trace"] = normalized_trace
        return normalized

    def _canonical_feature(self, feature: str) -> str:
        normalized = feature.strip().lower()
        return {
            "architecture": "Architecture",
            "cycles": "Cycles",
            "cycle": "Cycles",
            "issues": "Issues",
            "issue": "Issues",
            "tickets": "Issues",
            "ticket": "Issues",
            "projects": "Projects",
            "project": "Projects",
            "teams": "Teams",
            "team": "Teams",
            "integrations": "Integrations",
            "integration": "Integrations",
            "voice": "Voice",
        }.get(normalized, feature)

    def _default_transport(
        self,
        api_key: str,
        payload: dict[str, Any],
        timeout_ms: int,
    ) -> dict[str, Any]:
        model = self._model_name()
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_ms / 1000) as response:
            body = response.read().decode("utf-8")
        return json.loads(body)

    def _model_name(self) -> str:
        return env_value("GEMINI_MODEL") or "gemini-3.5-flash-lite"
