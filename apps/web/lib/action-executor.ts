import { demoIssues } from "@/lib/demo-data";
import { productConfig } from "@/lib/product-config";
import type {
  DemoAction,
  DemoActionType,
  DemoIssue,
  DemoPage,
  NavigableDemoPage,
  SessionUiState,
  UiEvent
} from "@/types/demo";

const pageByAction: Partial<Record<DemoActionType, DemoPage>> = {
  OPEN_DASHBOARD: "dashboard",
  OPEN_ISSUES: "issues",
  OPEN_PROJECTS: "projects",
  OPEN_CYCLES: "cycles",
  OPEN_TEAMS: "teams",
  OPEN_INTEGRATIONS: "integrations"
};

export const actionByPage: Record<NavigableDemoPage, DemoAction> = {
  dashboard: { type: "OPEN_DASHBOARD" },
  issues: { type: "OPEN_ISSUES" },
  projects: { type: "OPEN_PROJECTS" },
  cycles: { type: "OPEN_CYCLES" },
  teams: { type: "OPEN_TEAMS" },
  integrations: { type: "OPEN_INTEGRATIONS" }
};

export function executeDemoAction(
  state: SessionUiState,
  action: DemoAction,
  options: { issues?: DemoIssue[] } = {}
): { nextState: SessionUiState; event: UiEvent } {
  if (!productConfig.allowedActions.includes(action.type)) {
    return {
      nextState: state,
      event: createUiEvent(action.type, "rejected", "Action is not allowed for this product.")
    };
  }

  const issues = options.issues ?? demoIssues;
  const page = pageByAction[action.type];

  if (page) {
    return {
      nextState: {
        ...state,
        current_page: page,
        highlighted_target: undefined,
        issue_filter_assignee: undefined
      },
      event: createUiEvent(action.type, "executed", `Opened ${page}.`)
    };
  }

  if (action.type === "OPEN_DEMO_ISSUE") {
    const issue = issues.find((item) => item.id === action.payload.issue_id);

    if (!issue) {
      return {
        nextState: state,
        event: createUiEvent(action.type, "rejected", "Issue does not exist in demo data.")
      };
    }

    return {
      nextState: {
        ...state,
        current_page: "issue_detail",
        selected_issue_id: issue.id,
        highlighted_target: undefined,
        issue_filter_assignee: undefined
      },
      event: createUiEvent(action.type, "executed", `Opened ${issue.id}.`)
    };
  }

  if (action.type === "OPEN_SYSTEM_ARCHITECTURE") {
    return {
      nextState: {
        ...state,
        highlighted_target: undefined,
        issue_filter_assignee: undefined
      },
      event: createUiEvent(action.type, "executed", "Opened system architecture.")
    };
  }

  if (action.type === "CREATE_DEMO_ISSUE") {
    if (!isDemoIssue(action.payload)) {
      return {
        nextState: state,
        event: createUiEvent(action.type, "rejected", "Demo issue payload is incomplete.")
      };
    }

    return {
      nextState: {
        ...state,
        current_page: "issue_detail",
        selected_issue_id: action.payload.id,
        highlighted_target: "created_issue",
        issue_filter_assignee: undefined
      },
      event: createUiEvent(action.type, "executed", `Created demo issue ${action.payload.id}.`)
    };
  }

  if (action.type === "UPDATE_DEMO_ISSUE") {
    const issue = issues.find((item) => item.id === action.payload.issue_id);

    if (!issue) {
      return {
        nextState: state,
        event: createUiEvent(action.type, "rejected", "Issue update target was not found.")
      };
    }

    return {
      nextState: {
        ...state,
        current_page: "issue_detail",
        selected_issue_id: issue.id,
        highlighted_target: "updated_issue",
        issue_filter_assignee: undefined
      },
      event: createUiEvent(action.type, "executed", `Updated issue ${issue.id}.`)
    };
  }

  if (action.type === "FILTER_ISSUES_BY_ASSIGNEE") {
    const matchingIssues = issues.filter((issue) => issue.assignee === action.payload.assignee);

    if (matchingIssues.length === 0) {
      return {
        nextState: state,
        event: createUiEvent(action.type, "rejected", "No demo issues match that assignee.")
      };
    }

    return {
      nextState: {
        ...state,
        current_page: "issues",
        highlighted_target: undefined,
        issue_filter_assignee: action.payload.assignee
      },
      event: createUiEvent(
        action.type,
        "executed",
        `Filtered issues assigned to ${action.payload.assignee}.`
      )
    };
  }

  if (action.type === "HIGHLIGHT_ASSIGNMENT_CONTROL") {
    const requestedIssueId = action.payload.issue_id ?? state.selected_issue_id ?? issues[0]?.id;
    const issue = issues.find((item) => item.id === requestedIssueId);

    if (!issue) {
      return {
        nextState: state,
        event: createUiEvent(action.type, "rejected", "Assignment control target was not found.")
      };
    }

    return {
      nextState: {
        ...state,
        current_page: "issue_detail",
        selected_issue_id: issue.id,
        highlighted_target: "assignment_control",
        issue_filter_assignee: undefined
      },
      event: createUiEvent(action.type, "executed", `Highlighted assignee control on ${issue.id}.`)
    };
  }

  if (action.type === "OPEN_GITHUB_SETUP") {
    return {
      nextState: {
        ...state,
        current_page: "integrations",
        highlighted_target: "github_setup",
        issue_filter_assignee: undefined
      },
      event: createUiEvent(action.type, "executed", "Opened GitHub setup workflow.")
    };
  }

  if (action.type === "HIGHLIGHT_GITHUB_CARD") {
    return {
      nextState: {
        ...state,
        current_page: "integrations",
        highlighted_target: "github_card",
        issue_filter_assignee: undefined
      },
      event: createUiEvent(action.type, "executed", "Highlighted GitHub integration.")
    };
  }

  if (action.type === "HIGHLIGHT_SLACK_CARD") {
    return {
      nextState: {
        ...state,
        current_page: "integrations",
        highlighted_target: "slack_card",
        issue_filter_assignee: undefined
      },
      event: createUiEvent(action.type, "executed", "Highlighted Slack integration.")
    };
  }

  if (action.type === "HIGHLIGHT_CREATE_TICKET_BUTTON") {
    return {
      nextState: {
        ...state,
        current_page: "issues",
        highlighted_target: "create_ticket_button",
        issue_filter_assignee: undefined
      },
      event: createUiEvent(action.type, "executed", "Highlighted create ticket.")
    };
  }

  if (action.type === "HIGHLIGHT_ADD_MEMBER_BUTTON") {
    return {
      nextState: {
        ...state,
        current_page: "teams",
        highlighted_target: "add_member_button",
        issue_filter_assignee: undefined
      },
      event: createUiEvent(action.type, "executed", "Highlighted add member.")
    };
  }

  if (action.type === "HIGHLIGHT_CYCLE_PROGRESS") {
    return {
      nextState: {
        ...state,
        current_page: "cycles",
        highlighted_target: "cycle_progress",
        issue_filter_assignee: undefined
      },
      event: createUiEvent(action.type, "executed", "Highlighted cycle progress.")
    };
  }

  return {
    nextState: state,
    event: createUiEvent(action.type, "rejected", "Action has no frontend handler.")
  };
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

function createUiEvent(
  actionType: DemoActionType,
  status: UiEvent["status"],
  description: string
): UiEvent {
  return {
    id: crypto.randomUUID(),
    action_type: actionType,
    status,
    description,
    created_at: new Date().toISOString()
  };
}
