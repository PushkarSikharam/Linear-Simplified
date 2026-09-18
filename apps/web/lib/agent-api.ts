import { productConfig } from "@/lib/product-config";
import { authorizedFetch, RateLimitedError } from "@/lib/product-data-api";
import type { DemoAction, DemoActionType, DemoIssue, IntentTrace } from "@/types/demo";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  (typeof window !== "undefined" ? "/api/agent" : "http://127.0.0.1:8001/api");

export type AgentTurnResponse = {
  session_id: string;
  turn_id: number;
  status: "completed" | "cancelled" | "stale" | "denied";
  speech: string;
  proposed_action: { type: string; payload: Record<string, unknown> } | null;
  validated_action: DemoAction | null;
  intent_trace: IntentTrace;
  signals: Array<{
    type: string;
    value: string;
    confidence: number;
  }>;
  retrieved_context: Array<{
    title: string;
    source: string;
    snippet: string;
  }>;
  session_summary: {
    interests: string[];
    pain_points: string[];
    last_person?: string | null;
    last_feature?: string | null;
    clarification_pending?: string | null;
  };
};

export async function sendAgentTurn(input: {
  sessionId: string;
  turnId: number;
  productId: string;
  message: string;
  inputMode: "text" | "voice";
  currentPage: string;
  workspaceScopeId: string;
  selectedIssueId?: string;
}): Promise<AgentTurnResponse> {
  const endpoint = apiEndpoint("turn");
  const response = await authorizedFetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      session_id: input.sessionId,
      turn_id: input.turnId,
      product_id: input.productId,
      message: input.message,
      input_mode: input.inputMode,
      current_page: input.currentPage,
      workspace_scope_id: input.workspaceScopeId,
      selected_issue_id: input.selectedIssueId
    })
  });

  if (response.status === 429) throw new RateLimitedError();
  if (!response.ok) {
    throw new Error(`Agent request failed with ${response.status}`);
  }

  const body = (await response.json()) as AgentTurnResponse;
  return {
    ...body,
    validated_action: parseValidatedAction(body.validated_action)
  };
}

export async function cancelAgentTurn(input: {
  sessionId: string;
  turnId: number;
}): Promise<void> {
  const endpoint = apiEndpoint(`turn/${input.turnId}/cancel`);
  const response = await authorizedFetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      session_id: input.sessionId
    })
  });

  if (!response.ok) {
    throw new Error(`Agent cancellation failed with ${response.status}`);
  }
}

function apiEndpoint(path: string): string {
  const baseUrl = API_BASE_URL.replace(/\/$/, "");
  const apiBaseUrl =
    baseUrl.endsWith("/api") || baseUrl.endsWith("/api/agent") ? baseUrl : `${baseUrl}/api`;
  return `${apiBaseUrl}/${path}`;
}

function parseValidatedAction(action: DemoAction | null): DemoAction | null {
  if (!action || !isAllowedActionType(action.type)) {
    return null;
  }

  if (
    action.type === "OPEN_DEMO_ISSUE"
    || action.type === "HIGHLIGHT_ASSIGNMENT_CONTROL"
  ) {
    const issueId = action.payload?.issue_id;
    if (issueId === undefined && action.type === "HIGHLIGHT_ASSIGNMENT_CONTROL") {
      return { type: action.type, payload: {} };
    }
    if (typeof issueId === "string") {
      return { type: action.type, payload: { issue_id: issueId } };
    }
    return null;
  }

  if (action.type === "FILTER_ISSUES_BY_ASSIGNEE") {
    const assignee = action.payload?.assignee;
    if (typeof assignee === "string") {
      return { type: action.type, payload: { assignee } };
    }
    return null;
  }

  if (action.type === "CREATE_DEMO_ISSUE") {
    if (isDemoIssue(action.payload)) {
      return { type: action.type, payload: action.payload };
    }
    return null;
  }

  if (action.type === "UPDATE_DEMO_ISSUE") {
    const issueId = action.payload?.issue_id;
    if (typeof issueId !== "string") {
      return null;
    }
    return {
      type: action.type,
      payload: {
        issue_id: issueId,
        assignee:
          typeof action.payload.assignee === "string" ? action.payload.assignee : undefined,
        priority: isPriority(action.payload.priority) ? action.payload.priority : undefined,
        status: typeof action.payload.status === "string" ? action.payload.status : undefined
      }
    };
  }

  if (action.type === "CREATE_DEMO_TEAM_MEMBER") {
    return null;
  }

  if (action.type === "HIGHLIGHT_ADD_MEMBER_BUTTON") {
    const name = action.payload?.name;
    return typeof name === "string"
      ? { type: action.type, payload: { name } }
      : { type: action.type };
  }

  return { type: action.type };
}

function isAllowedActionType(value: string): value is DemoActionType {
  return productConfig.allowedActions.includes(value as DemoActionType);
}

function isDemoIssue(value: unknown): value is DemoIssue {
  if (!value || typeof value !== "object") return false;
  const issue = value as Partial<DemoIssue>;
  return (
    typeof issue.id === "string"
    && typeof issue.title === "string"
    && typeof issue.assignee === "string"
    && typeof issue.project === "string"
    && typeof issue.status === "string"
    && (issue.priority === "Low" || issue.priority === "Medium" || issue.priority === "High")
  );
}

function isPriority(value: unknown): value is DemoIssue["priority"] {
  return value === "Low" || value === "Medium" || value === "High";
}
