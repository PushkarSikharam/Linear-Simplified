import { executeDemoAction } from "@/lib/action-executor";
import type { DemoAction, SessionUiState } from "@/types/demo";
import { describe, expect, it } from "vitest";

const baseState: SessionUiState = {
  current_page: "dashboard",
  active_turn_id: null
};

type ActionCase = {
  name: string;
  action: DemoAction;
  expectedPage: SessionUiState["current_page"];
  expectedHighlight?: string;
  expectedIssueId?: string;
};

const actionCases: ActionCase[] = [
  { name: "opens dashboard", action: { type: "OPEN_DASHBOARD" }, expectedPage: "dashboard" },
  { name: "opens issues", action: { type: "OPEN_ISSUES" }, expectedPage: "issues" },
  { name: "opens projects", action: { type: "OPEN_PROJECTS" }, expectedPage: "projects" },
  { name: "opens cycles", action: { type: "OPEN_CYCLES" }, expectedPage: "cycles" },
  { name: "opens teams", action: { type: "OPEN_TEAMS" }, expectedPage: "teams" },
  {
    name: "opens integrations",
    action: { type: "OPEN_INTEGRATIONS" },
    expectedPage: "integrations"
  },
  {
    name: "opens a demo issue",
    action: { type: "OPEN_DEMO_ISSUE", payload: { issue_id: "LIN-142" } },
    expectedPage: "issue_detail",
    expectedIssueId: "LIN-142"
  },
  {
    name: "opens an updated demo issue",
    action: { type: "UPDATE_DEMO_ISSUE", payload: { issue_id: "LIN-142", assignee: "Noah Patel" } },
    expectedPage: "issue_detail",
    expectedHighlight: "updated_issue",
    expectedIssueId: "LIN-142"
  },
  {
    name: "opens GitHub setup",
    action: { type: "OPEN_GITHUB_SETUP" },
    expectedPage: "integrations",
    expectedHighlight: "github_setup"
  },
  {
    name: "highlights GitHub card",
    action: { type: "HIGHLIGHT_GITHUB_CARD" },
    expectedPage: "integrations",
    expectedHighlight: "github_card"
  },
  {
    name: "highlights Slack card",
    action: { type: "HIGHLIGHT_SLACK_CARD" },
    expectedPage: "integrations",
    expectedHighlight: "slack_card"
  },
  {
    name: "highlights create ticket button",
    action: { type: "HIGHLIGHT_CREATE_TICKET_BUTTON" },
    expectedPage: "issues",
    expectedHighlight: "create_ticket_button"
  },
  {
    name: "highlights add member button",
    action: { type: "HIGHLIGHT_ADD_MEMBER_BUTTON", payload: { name: "Lucifer" } },
    expectedPage: "teams",
    expectedHighlight: "add_member_button"
  },
  {
    name: "highlights assignment control",
    action: { type: "HIGHLIGHT_ASSIGNMENT_CONTROL", payload: { issue_id: "LIN-142" } },
    expectedPage: "issue_detail",
    expectedHighlight: "assignment_control",
    expectedIssueId: "LIN-142"
  },
  {
    name: "highlights cycle progress",
    action: { type: "HIGHLIGHT_CYCLE_PROGRESS" },
    expectedPage: "cycles",
    expectedHighlight: "cycle_progress"
  }
];

describe("executeDemoAction", () => {
  actionCases.forEach(({ action, expectedHighlight, expectedIssueId, expectedPage, name }) => {
    it(name, () => {
      const result = executeDemoAction(baseState, action);

      expect(result.event.status).toBe("executed");
      expect(result.nextState.current_page).toBe(expectedPage);
      expect(result.nextState.highlighted_target).toBe(expectedHighlight);
      expect(result.nextState.selected_issue_id).toBe(expectedIssueId);
    });
  });

  it("rejects unknown issue IDs", () => {
    const result = executeDemoAction(baseState, {
      type: "OPEN_DEMO_ISSUE",
      payload: { issue_id: "LIN-999" }
    });

    expect(result.event.status).toBe("rejected");
    expect(result.nextState).toEqual(baseState);
  });

  it("creates a demo issue and selects it", () => {
    const issue = {
      id: "PIX-143",
      title: "Investigate login issue",
      priority: "Medium" as const,
      assignee: "Maya Chen",
      project: "Issue Triage",
      status: "Todo"
    };

    const result = executeDemoAction(
      baseState,
      {
        type: "CREATE_DEMO_ISSUE",
        payload: issue
      },
      { issues: [issue] }
    );

    expect(result.event.status).toBe("executed");
    expect(result.nextState.current_page).toBe("issue_detail");
    expect(result.nextState.selected_issue_id).toBe("PIX-143");
    expect(result.nextState.highlighted_target).toBe("created_issue");
  });

  it("accepts the system architecture action without mutating product view state", () => {
    const result = executeDemoAction(baseState, { type: "OPEN_SYSTEM_ARCHITECTURE" });

    expect(result.event.status).toBe("executed");
    expect(result.event.description).toBe("Opened system architecture.");
    expect(result.nextState.current_page).toBe("dashboard");
  });
});
