"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { actionByPage, executeDemoAction } from "@/lib/action-executor";
import { cancelAgentTurn, type AgentTurnResponse, sendAgentTurn } from "@/lib/agent-api";
import { demoIssues, demoProjects, demoCycle, demoTeam, integrations } from "@/lib/demo-data";
import { productConfig } from "@/lib/product-config";
import { HybridVoiceEngine, VoiceEngineMode, VoiceEngineStatus } from "@/lib/hybrid-voice-engine";
import type { SpectrumData } from "@/lib/voice-analyzer";
import type {
  DemoAction,
  DemoCycle,
  DemoIssue,
  DemoProject,
  DemoTeamMember,
  IntentTrace,
  SessionUiState,
  UiEvent
} from "@/types/demo";

const navItems = productConfig.pages;

const initialTrace: IntentTrace = {
  role: "Unknown",
  current_tool: "Not detected",
  goal: "Waiting for visitor",
  pain_point: "None yet",
  current_intent: "Discovery",
  relevant_feature: "Dashboard",
  reason: "The demo is ready for the visitor's first request.",
  confidence: 0,
  status: "active"
};

type TranscriptMessage = {
  speaker: "Agent" | "Visitor";
  text: string;
};

type SessionSummary = AgentTurnResponse["session_summary"];
type InputMode = "text" | "voice";
type VoiceStatus = "Idle" | "Listening" | "Processing" | "Speaking" | "Unavailable";
const DEFAULT_VOICE_SILENCE_TIMEOUT_MS = 3500;

type DraftPrefill = {
  issue?: {
    assignee?: string;
    priority?: DemoIssue["priority"];
    title?: string;
  };
  teamMember?: {
    name?: string;
  };
  issueUpdate?: {
    issueId: string;
    assignee?: string;
    priority?: DemoIssue["priority"];
    status?: string;
  };
};

type SpeechRecognitionResultLike = {
  readonly isFinal: boolean;
  readonly 0: {
    readonly transcript: string;
  };
};

type SpeechRecognitionEventLike = {
  readonly resultIndex: number;
  readonly results: {
    readonly length: number;
    readonly [index: number]: SpeechRecognitionResultLike;
  };
};

type BrowserSpeechRecognition = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onstart: (() => void) | null;
  abort: () => void;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

type SpeechRecognitionWindow = Window &
  typeof globalThis & {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
    __demoVoiceSilenceTimeoutMs?: number;
    __disableAutoGreetingSpeech?: boolean;
    __emitVoiceTranscript?: (transcript: string) => void;
  };

const initialTranscript: TranscriptMessage[] = [
  {
    speaker: "Agent",
    text: "Welcome to Pixel. I'm Edith, your guide to planning work, tracking tickets, and connecting your team's tools. What brought you to check us out today?"
  }
];

const initialSessionSummary: SessionSummary = {
  interests: [],
  pain_points: [],
  last_person: null,
  last_feature: null,
  clarification_pending: null
};

const demoPrompts = [
  "Back to GitHub integrations",
  "Show me issue assignment",
  "What can Pixel do with Slack?"
];

const demoPathPrompts = [
  "Show sprint planning",
  "Open Maya's ticket",
  "Assign it to Noah",
  "Create a ticket for Lucifer",
  "Open Salesforce"
];

const connectedIntegrationCount = integrations.filter((integration) => integration.connected).length;
type TurnStatus = "Ready" | "Thinking" | "Interrupted" | "Action blocked";
const issueStatuses = ["Todo", "In progress", "Review", "Done"] as const;
const priorities = ["Low", "Medium", "High"] as const;

export default function Home() {
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const activeTurnIdRef = useRef<number | null>(null);
  const nextTurnIdRef = useRef(1);
  const [uiState, setUiState] = useState<SessionUiState>({
    current_page: "dashboard",
    active_turn_id: null
  });
  const [uiEvents, setUiEvents] = useState<UiEvent[]>([]);
  const [intentTrace, setIntentTrace] = useState<IntentTrace>(initialTrace);
  const [sessionSummary, setSessionSummary] = useState<SessionSummary>(initialSessionSummary);
  const [messages, setMessages] = useState<TranscriptMessage[]>(initialTranscript);
  const [issues, setIssues] = useState<DemoIssue[]>(demoIssues);
  const [projects, setProjects] = useState<DemoProject[]>(demoProjects);
  const [cycles, setCycles] = useState<DemoCycle[]>([demoCycle]);
  const [team, setTeam] = useState<DemoTeamMember[]>(demoTeam);
  const [draftPrefill, setDraftPrefill] = useState<DraftPrefill>({});
  const [isAssistantCollapsed, setIsAssistantCollapsed] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [turnStatus, setTurnStatus] = useState<TurnStatus>("Ready");
  const currentPage = uiState.current_page;
  const activeNavItem = useMemo(
    () => navItems.find((item) => item.id === currentPage),
    [currentPage]
  );

  function runAction(action: DemoAction) {
    setUiState((currentState) => {
      const nextIssues =
        action.type === "CREATE_DEMO_ISSUE"
          ? upsertIssue(issues, action.payload)
          : issues;
      const result = executeDemoAction(currentState, action, { issues: nextIssues });
      if (action.type === "CREATE_DEMO_ISSUE" && result.event.status === "executed") {
        setIssues(nextIssues);
      }
      setUiEvents((events) => [result.event, ...events].slice(0, 6));
      return result.nextState;
    });
  }

  function recordUiEvent(event: UiEvent) {
    setUiEvents((events) => [event, ...events].slice(0, 6));
  }

  function resetDemoSession() {
    const activeTurnId = activeTurnIdRef.current;
    if (activeTurnId !== null) {
      void cancelAgentTurn({ sessionId, turnId: activeTurnId }).catch(() => undefined);
    }

    activeTurnIdRef.current = null;
    nextTurnIdRef.current = 1;
    setSessionId(crypto.randomUUID());
    setUiState({
      current_page: "dashboard",
      active_turn_id: null
    });
    setUiEvents([]);
    setIntentTrace(initialTrace);
    setSessionSummary(initialSessionSummary);
    setMessages(initialTranscript);
    setIssues(demoIssues);
    setProjects(demoProjects);
    setCycles([demoCycle]);
    setTeam(demoTeam);
    setDraftPrefill({});
    setIsSending(false);
    setTurnStatus("Ready");
  }

  function createIssue(issue: DemoIssue) {
    const nextIssues = upsertIssue(issues, issue);
    setIssues(nextIssues);
    setDraftPrefill((currentPrefill) => ({
      ...currentPrefill,
      issue: undefined,
      issueUpdate: undefined
    }));
    runAction({ type: "CREATE_DEMO_ISSUE", payload: issue });
  }

  function createTeamMember(member: DemoTeamMember) {
    const pendingIssueDraft = draftPrefill.issue;
    const pendingIssueUpdate = draftPrefill.issueUpdate;
    setTeam((currentTeam) => [...currentTeam, member]);
    setDraftPrefill((currentPrefill) => ({
      ...currentPrefill,
      teamMember: undefined,
      issue: currentPrefill.issue
        ? {
            ...currentPrefill.issue,
            assignee: member.name
          }
        : undefined
    }));

    if (pendingIssueUpdate) {
      const issue = issues.find((item) => item.id === pendingIssueUpdate.issueId);
      if (issue) {
        const updatedIssue = {
          ...issue,
          assignee: pendingIssueUpdate.assignee ?? member.name,
          priority: pendingIssueUpdate.priority ?? issue.priority,
          status: pendingIssueUpdate.status ?? issue.status
        };
        updateIssue(updatedIssue);
        setDraftPrefill({});
        setUiState((currentState) => ({
          ...currentState,
          current_page: "issue_detail",
          selected_issue_id: issue.id,
          highlighted_target: "updated_issue",
          issue_filter_assignee: undefined
        }));
        setMessages((currentMessages) => [
          ...currentMessages,
          {
            speaker: "Agent",
            text: `${member.name} has been added. I assigned ${issue.id} to ${member.name}.`
          }
        ]);
      }
    } else if (pendingIssueDraft) {
      setUiState((currentState) => ({
        ...currentState,
        current_page: "issues",
        highlighted_target: "create_ticket_button",
        issue_filter_assignee: undefined
      }));
      setMessages((currentMessages) => [
        ...currentMessages,
        {
          speaker: "Agent",
          text: `${member.name} has been added. I'll open the ticket form with ${member.name} selected.`
        }
      ]);
    }
    recordUiEvent({
      id: crypto.randomUUID(),
      action_type: "CREATE_DEMO_TEAM_MEMBER",
      status: "executed",
      description: `Added team member ${member.name} (${member.role}).`,
      created_at: new Date().toISOString()
    });
  }

  function updateIssue(updatedIssue: DemoIssue) {
    setIssues((currentIssues) =>
      currentIssues.map((item) => (item.id === updatedIssue.id ? updatedIssue : item))
    );
    recordUiEvent({
      id: crypto.randomUUID(),
      action_type: "UPDATE_DEMO_ISSUE",
      status: "executed",
      description: `Updated issue ${updatedIssue.id} details (Assignee: ${updatedIssue.assignee}, Priority: ${updatedIssue.priority}, Status: ${updatedIssue.status}).`,
      created_at: new Date().toISOString()
    });
  }

  function createProject(project: DemoProject) {
    setProjects((currentProjects) => [project, ...currentProjects]);
    setUiState((currentState) => ({
      ...currentState,
      current_page: "projects",
      highlighted_target: `project_${project.id}`,
      issue_filter_assignee: undefined
    }));
    recordUiEvent({
      id: crypto.randomUUID(),
      action_type: "CREATE_DEMO_PROJECT",
      status: "executed",
      description: `Created demo project ${project.name}.`,
      created_at: new Date().toISOString()
    });
  }

  function createCycle(cycle: DemoCycle) {
    setCycles((currentCycles) => [cycle, ...currentCycles]);
    setUiState((currentState) => ({
      ...currentState,
      current_page: "cycles",
      highlighted_target: `cycle_${cycle.id}`,
      issue_filter_assignee: undefined
    }));
    recordUiEvent({
      id: crypto.randomUUID(),
      action_type: "CREATE_DEMO_CYCLE",
      status: "executed",
      description: `Created demo cycle ${cycle.name}.`,
      created_at: new Date().toISOString()
    });
  }

  async function sendMessage(message: string, inputMode: InputMode = "text") {
    const trimmedMessage = message.trim();
    if (!trimmedMessage) return null;

    const localConversationResponse = handleLocalConversationIntent(trimmedMessage);
    if (localConversationResponse) {
      return localConversationResponse;
    }

    const localDraftResponse = handleLocalDraftIntent(trimmedMessage);
    if (localDraftResponse) {
      return localDraftResponse;
    }

    const previousTurnId = activeTurnIdRef.current;
    if (previousTurnId !== null) {
      void cancelAgentTurn({ sessionId, turnId: previousTurnId }).catch(() => undefined);
    }

    const turnId = nextTurnIdRef.current;
    nextTurnIdRef.current += 1;
    activeTurnIdRef.current = turnId;
    setIsSending(true);
    setTurnStatus("Thinking");
    setUiState((currentState) => ({
      ...currentState,
      active_turn_id: turnId
    }));
    setMessages((currentMessages) => [
      ...currentMessages,
      { speaker: "Visitor", text: trimmedMessage }
    ]);

    try {
      const result = await sendAgentTurn({
        sessionId,
        turnId,
        productId: productConfig.id,
        message: trimmedMessage,
        inputMode,
        currentPage,
        selectedIssueId: uiState.selected_issue_id
      });

      if (activeTurnIdRef.current !== turnId) {
        return null;
      }

      if (result.status === "stale" || result.status === "cancelled") {
        setTurnStatus("Interrupted");
        setIntentTrace(result.intent_trace);
        setSessionSummary(result.session_summary);
        return null;
      }

      setIntentTrace(result.intent_trace);
      setSessionSummary(result.session_summary);
      setMessages((currentMessages) => [
        ...currentMessages,
        { speaker: "Agent", text: result.speech }
      ]);

      const validatedAction = result.validated_action;
      if (validatedAction) {
        if (validatedAction.type === "HIGHLIGHT_ADD_MEMBER_BUTTON") {
          setDraftPrefill((currentPrefill) => ({
            ...currentPrefill,
            teamMember: {
              name: validatedAction.payload?.name
            }
          }));
        }
        runAction(validatedAction);
      } else if (result.proposed_action) {
        recordUiEvent({
          id: crypto.randomUUID(),
          action_type: result.proposed_action.type,
          status: "rejected",
          description: result.intent_trace.reason ?? "The backend did not validate this action.",
          created_at: new Date().toISOString()
        });
      }

      setTurnStatus(result.status === "denied" ? "Action blocked" : "Ready");
      return result;
    } catch {
      if (activeTurnIdRef.current !== turnId) {
        return null;
      }

      setTurnStatus("Action blocked");
      setIntentTrace((currentTrace) => ({
        ...currentTrace,
        status: "denied",
        reason: "The frontend could not reach the backend turn API."
      }));
      setMessages((currentMessages) => [
        ...currentMessages,
        {
          speaker: "Agent",
          text: "I could not reach the demo agent service. Please check that the backend is running."
        }
      ]);
      return null;
    } finally {
      if (activeTurnIdRef.current === turnId) {
        activeTurnIdRef.current = null;
        setIsSending(false);
        setUiState((currentState) => ({
          ...currentState,
          active_turn_id: null
        }));
      }
    }
  }

  function handleLocalDraftIntent(message: string): AgentTurnResponse | null {
    const draftRequest = parseTicketDraftRequest(message);
    if (!draftRequest) return null;

    const requestedName = draftRequest.assignee;
    const matchingMember = requestedName ? findTeamMember(team, requestedName) : undefined;
    const turnId = nextTurnIdRef.current;
    nextTurnIdRef.current += 1;

    setMessages((currentMessages) => [
      ...currentMessages,
      { speaker: "Visitor", text: message }
    ]);

    if (requestedName && !matchingMember) {
      const speech = `${requestedName} is not in the team directory yet. I'll open Teams so you can add ${requestedName} first.`;
      setDraftPrefill({
        teamMember: { name: requestedName },
        issue: {
          assignee: requestedName,
          priority: draftRequest.priority,
          title: draftRequest.title
        }
      });
      setUiState((currentState) => ({
        ...currentState,
        current_page: "teams",
        highlighted_target: "add_member_button",
        issue_filter_assignee: undefined,
        active_turn_id: null
      }));
      setTurnStatus("Ready");
      setMessages((currentMessages) => [...currentMessages, { speaker: "Agent", text: speech }]);

      return localTurnResponse({
        action: { type: "HIGHLIGHT_ADD_MEMBER_BUTTON", payload: { name: requestedName } },
        message: speech,
        sessionId,
        turnId
      });
    }

    const assignee = matchingMember?.name ?? team[0]?.name ?? "Maya Chen";
    const speech = `I'll open the ticket form and prefill ${assignee}. Review the details, then create the ticket.`;
    setDraftPrefill({
      issue: {
        assignee,
        priority: draftRequest.priority,
        title: draftRequest.title
      }
    });
    setUiState((currentState) => ({
      ...currentState,
      current_page: "issues",
      highlighted_target: "create_ticket_button",
      issue_filter_assignee: undefined,
      active_turn_id: null
    }));
    setTurnStatus("Ready");
    setMessages((currentMessages) => [...currentMessages, { speaker: "Agent", text: speech }]);

    return localTurnResponse({
      action: { type: "HIGHLIGHT_CREATE_TICKET_BUTTON" },
      message: speech,
      sessionId,
      turnId
    });
  }

  function handleLocalConversationIntent(message: string): AgentTurnResponse | null {
    const text = normalizeText(message);
    const turnId = nextTurnIdRef.current;
    const sayAndReturn = (speech: string, action: DemoAction | null = null) => {
      nextTurnIdRef.current += 1;
      setMessages((currentMessages) => [
        ...currentMessages,
        { speaker: "Visitor", text: message },
        { speaker: "Agent", text: speech }
      ]);
      setTurnStatus("Ready");
      if (action) {
        runAction(action);
      }
      return localTurnResponse({
        action,
        message: speech,
        sessionId,
        turnId
      });
    };

    if (asksForEvaluatorDemo(text)) {
      return sayAndReturn(
        "Here is the strongest demo path: start with sprint planning, open Maya's ticket, assign it to Noah, create a ticket for a new teammate, then try Salesforce to prove guardrails.",
        { type: "OPEN_DASHBOARD" }
      );
    }

    if (asksCapabilities(text)) {
      return sayAndReturn(
        "I can guide this Pixel demo through planning, issues, projects, teams, and integrations. I can open views, find tickets, update issue fields, create demo records, and block actions outside Pixel."
      );
    }

    if (asksWhatChanged(text)) {
      const latestEvent = uiEvents[0];
      const speech = latestEvent
        ? `Most recently, ${lowercaseFirst(latestEvent.description)}`
        : "We have not changed anything in the workspace yet.";
      return sayAndReturn(speech);
    }

    const correctionAction = correctionActionFor(text);
    if (correctionAction) {
      return sayAndReturn(correctionSpeech(correctionAction), correctionAction);
    }

    const updateDraft = parseIssueUpdateRequest(message);
    if (!updateDraft) return null;

    const issue = resolveIssueForMessage(message, issues, uiState.selected_issue_id);
    if (!issue) {
      return sayAndReturn(
        "Which ticket should I update: Maya's ticket, Noah's ticket, or the issue currently open?"
      );
    }

    if (updateDraft.assignee) {
      const member = findTeamMember(team, updateDraft.assignee);
      if (!member) {
        setDraftPrefill({
          teamMember: { name: updateDraft.assignee },
          issueUpdate: {
            issueId: issue.id,
            assignee: updateDraft.assignee,
            priority: updateDraft.priority,
            status: updateDraft.status
          }
        });
        setUiState((currentState) => ({
          ...currentState,
          current_page: "teams",
          highlighted_target: "add_member_button",
          issue_filter_assignee: undefined,
          active_turn_id: null
        }));
        return sayAndReturn(
          `${updateDraft.assignee} is not in the team directory yet. I'll open Teams so you can add ${updateDraft.assignee} before assigning ${issue.id}.`,
          { type: "HIGHLIGHT_ADD_MEMBER_BUTTON", payload: { name: updateDraft.assignee } }
        );
      }
      updateDraft.assignee = member.name;
    }

    const updatedIssue = {
      ...issue,
      assignee: updateDraft.assignee ?? issue.assignee,
      priority: updateDraft.priority ?? issue.priority,
      status: updateDraft.status ?? issue.status
    };
    updateIssue(updatedIssue);
    setUiState((currentState) => ({
      ...currentState,
      current_page: "issue_detail",
      selected_issue_id: issue.id,
      highlighted_target: "updated_issue",
      issue_filter_assignee: undefined
    }));
    const changes = describeIssueChanges(issue, updatedIssue);
    return sayAndReturn(`Done. I updated ${issue.id}: ${changes}.`, {
      type: "UPDATE_DEMO_ISSUE",
      payload: {
        issue_id: issue.id,
        assignee: updateDraft.assignee,
        priority: updateDraft.priority,
        status: updateDraft.status
      }
    });
  }

  return (
    <main className={isAssistantCollapsed ? "app-shell assistant-collapsed" : "app-shell"}>
      <aside className="sidebar" aria-label="Product navigation">
        <div className="brand-block">
          <div className="brand-mark">P</div>
          <div>
            <p className="brand-name">{productConfig.name}</p>
            <p className="brand-meta">Adaptive Demo</p>
          </div>
        </div>

        <nav className="nav-list">
          {navItems.map((item) => (
            <button
              className={item.id === currentPage ? "nav-item active" : "nav-item"}
              data-testid={`nav-${item.id}`}
              key={item.id}
              onClick={() => runAction(actionByPage[item.id])}
              type="button"
            >
              <span className="nav-shortcut">{item.shortcut}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="section-kicker">Current View</p>
            <h1 data-testid="current-view-title">{activeNavItem?.label ?? "Issue Detail"}</h1>
          </div>
          <div className="status-strip">
            <span className="status-dot" />
            <span>Controlled demo environment</span>
          </div>
        </header>

        <ProductSurface
          createCycle={createCycle}
          createIssue={createIssue}
          createProject={createProject}
          createTeamMember={createTeamMember}
          cycles={cycles}
          draftPrefill={draftPrefill}
          issues={issues}
          projects={projects}
          runAction={runAction}
          team={team}
          uiState={uiState}
          updateIssue={updateIssue}
        />
      </section>

      <aside
        className={isAssistantCollapsed ? "assistant-panel collapsed" : "assistant-panel"}
        aria-label="Assistant"
      >
        {isAssistantCollapsed ? (
          <button
            className="assistant-rail"
            data-testid="assistant-expand"
            onClick={() => setIsAssistantCollapsed(false)}
            type="button"
          >
            Ask Edith
          </button>
        ) : (
          <ConversationCard
            demoPrompts={demoPrompts}
            isSending={isSending}
            messages={messages}
            onCollapse={() => setIsAssistantCollapsed(true)}
            onReset={resetDemoSession}
            onSend={sendMessage}
            turnStatus={turnStatus}
          />
        )}
      </aside>
    </main>
  );
}

function ProductSurface({
  createCycle,
  createIssue,
  createProject,
  createTeamMember,
  cycles,
  draftPrefill,
  issues,
  projects,
  team,
  uiState,
  runAction,
  updateIssue
}: {
  createCycle: (cycle: DemoCycle) => void;
  createIssue: (issue: DemoIssue) => void;
  createProject: (project: DemoProject) => void;
  createTeamMember: (member: DemoTeamMember) => void;
  cycles: DemoCycle[];
  draftPrefill: DraftPrefill;
  issues: DemoIssue[];
  projects: DemoProject[];
  team: DemoTeamMember[];
  uiState: SessionUiState;
  runAction: (action: DemoAction) => void;
  updateIssue: (issue: DemoIssue) => void;
}) {
  if (uiState.current_page === "issues") {
    return (
      <IssuesView
        assigneeFilter={uiState.issue_filter_assignee}
        createIssue={createIssue}
        cycles={cycles}
        draftPrefill={draftPrefill.issue}
        issues={issues}
        projects={projects}
        runAction={runAction}
        team={team}
        highlightedTarget={uiState.highlighted_target}
      />
    );
  }
  if (uiState.current_page === "issue_detail") {
    return (
      <IssueDetailView
        issues={issues}
        onUpdateIssue={updateIssue}
        runAction={runAction}
        team={team}
        uiState={uiState}
      />
    );
  }
  if (uiState.current_page === "projects") {
    return (
      <ProjectsView
        createProject={createProject}
        highlightedTarget={uiState.highlighted_target}
        projects={projects}
      />
    );
  }
  if (uiState.current_page === "cycles") {
    return (
      <CyclesView
        createCycle={createCycle}
        cycles={cycles}
        highlightedTarget={uiState.highlighted_target}
      />
    );
  }
  if (uiState.current_page === "teams") {
    return (
      <TeamsView
        createTeamMember={createTeamMember}
        draftPrefill={draftPrefill.teamMember}
        highlightedTarget={uiState.highlighted_target}
        team={team}
      />
    );
  }
  if (uiState.current_page === "integrations") {
    return <IntegrationsView highlightedTarget={uiState.highlighted_target} />;
  }
  return <DashboardView cycles={cycles} issues={issues} projects={projects} runAction={runAction} />;
}

function DashboardView({
  cycles,
  issues,
  projects,
  runAction
}: {
  cycles: DemoCycle[];
  issues: DemoIssue[];
  projects: DemoProject[];
  runAction: (action: DemoAction) => void;
}) {
  const activeCycle = cycles[0] ?? demoCycle;
  const atRiskProjects = projects.filter((project) => project.status === "At risk").length;

  return (
    <div className="content-grid">
      <section className="panel wide">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Engineering Overview</p>
            <h2>Product development pulse</h2>
          </div>
          <span className="quiet-badge">Demo data</span>
        </div>
        <div className="metric-grid">
          <Metric label="Open issues" value={`${issues.length}`} delta="sample workspace" />
          <Metric label="Cycle progress" value={`${activeCycle.progress}%`} delta={`${activeCycle.daysLeft} days left`} />
          <Metric label="Active projects" value={`${projects.length}`} delta={`${atRiskProjects} at risk`} />
          <Metric label="Team workload" value="81%" delta="balanced" />
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Priority work</h2>
        </div>
        <IssueList issues={issues} limit={4} runAction={runAction} />
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Current cycle</h2>
        </div>
        <CycleProgress compact cycle={activeCycle} />
      </section>
    </div>
  );
}

function IssuesView({
  assigneeFilter,
  createIssue,
  cycles,
  draftPrefill,
  highlightedTarget,
  issues,
  projects,
  runAction,
  team
}: {
  assigneeFilter?: string;
  createIssue: (issue: DemoIssue) => void;
  cycles: DemoCycle[];
  draftPrefill?: DraftPrefill["issue"];
  highlightedTarget?: string;
  issues: DemoIssue[];
  projects: DemoProject[];
  runAction: (action: DemoAction) => void;
  team: DemoTeamMember[];
}) {
  const [isCreating, setIsCreating] = useState(false);
  const visibleIssueCount = assigneeFilter
    ? issues.filter((issue) => issue.assignee === assigneeFilter).length
    : issues.length;

  useEffect(() => {
    if (draftPrefill || highlightedTarget === "create_ticket_button") {
      setIsCreating(true);
    }
  }, [draftPrefill, highlightedTarget]);

  return (
    <div className="surface-stack">
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Issue Tracking</p>
            <h2>Open issues</h2>
          </div>
          <div className="panel-actions">
            <button
              className={
                highlightedTarget === "create_ticket_button"
                  ? "primary-button highlighted-action"
                  : "primary-button"
              }
              data-testid="create-ticket-button"
              onClick={() => setIsCreating((isOpen) => !isOpen)}
              type="button"
            >
              Create ticket
            </button>
            <span className="quiet-badge" data-testid="issue-count-badge">
              {visibleIssueCount} open
            </span>
          </div>
        </div>
        {assigneeFilter && (
          <div className="filter-bar" data-testid="issue-filter">
            <span>Assignee</span>
            <strong>{assigneeFilter}</strong>
          </div>
        )}
        {isCreating && (
          <IssueCreatePanel
            cycles={cycles}
            issues={issues}
            onCancel={() => setIsCreating(false)}
            onCreate={(issue) => {
              createIssue(issue);
              setIsCreating(false);
            }}
            projects={projects}
            prefill={draftPrefill}
            team={team}
          />
        )}
        <IssueList assigneeFilter={assigneeFilter} issues={issues} runAction={runAction} />
      </section>
    </div>
  );
}

function IssueCreatePanel({
  cycles,
  issues,
  onCancel,
  onCreate,
  prefill,
  projects,
  team
}: {
  cycles: DemoCycle[];
  issues: DemoIssue[];
  onCancel: () => void;
  onCreate: (issue: DemoIssue) => void;
  prefill?: DraftPrefill["issue"];
  projects: DemoProject[];
  team: DemoTeamMember[];
}) {
  const [title, setTitle] = useState(prefill?.title ?? "Investigate customer onboarding issue");
  const [assignee, setAssignee] = useState(prefill?.assignee ?? team[0]?.name ?? "Maya Chen");
  const [priority, setPriority] = useState<DemoIssue["priority"]>(prefill?.priority ?? "Medium");
  const [status, setStatus] = useState("Todo");
  const [project, setProject] = useState(projects[0]?.name ?? "Issue Triage");
  const [cycle, setCycle] = useState(cycles[0]?.name ?? demoCycle.name);
  const [estimate, setEstimate] = useState("2 pts");
  const [label, setLabel] = useState("Customer");
  const [description, setDescription] = useState(
    "Capture the request, assign an owner, and track it through the current cycle."
  );

  useEffect(() => {
    if (!prefill) return;
    if (prefill.title) setTitle(prefill.title);
    if (prefill.assignee) setAssignee(prefill.assignee);
    if (prefill.priority) setPriority(prefill.priority);
  }, [prefill]);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedTitle = title.trim();
    if (!trimmedTitle) return;

    onCreate({
      id: nextDemoIssueId(issues),
      title: trimmedTitle,
      priority,
      assignee,
      project,
      status,
      cycle,
      estimate,
      label,
      description: description.trim()
    });
  }

  return (
    <form className="creation-panel" data-testid="issue-create-panel" onSubmit={handleSubmit}>
      <div className="creation-header">
        <div>
          <p className="section-kicker">New Ticket</p>
          <h3>Create issue</h3>
        </div>
        <div className="panel-actions">
          <button className="secondary-button compact" onClick={onCancel} type="button">
            Cancel
          </button>
          <button className="primary-button" data-testid="submit-create-ticket" type="submit">
            Create
          </button>
        </div>
      </div>
      <div className="form-grid">
        <label className="field wide">
          <span>Title</span>
          <input
            data-testid="ticket-title-input"
            onChange={(event) => setTitle(event.target.value)}
            value={title}
          />
        </label>
        <label className="field">
          <span>Assignee</span>
          <select
            data-testid="ticket-assignee-select"
            onChange={(event) => setAssignee(event.target.value)}
            value={assignee}
          >
            {team.map((member) => (
              <option key={member.name} value={member.name}>
                {member.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Priority</span>
          <select onChange={(event) => setPriority(event.target.value as DemoIssue["priority"])} value={priority}>
            {priorities.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Status</span>
          <select onChange={(event) => setStatus(event.target.value)} value={status}>
            {issueStatuses.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Project</span>
          <select onChange={(event) => setProject(event.target.value)} value={project}>
            {projects.map((item) => (
              <option key={item.id} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Cycle</span>
          <select onChange={(event) => setCycle(event.target.value)} value={cycle}>
            {cycles.map((item) => (
              <option key={item.id} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Estimate</span>
          <select onChange={(event) => setEstimate(event.target.value)} value={estimate}>
            {["1 pt", "2 pts", "3 pts", "5 pts", "8 pts"].map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Label</span>
          <select onChange={(event) => setLabel(event.target.value)} value={label}>
            {["Customer", "Bug", "Improvement", "Integration", "Planning"].map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="field wide">
          <span>Description</span>
          <textarea onChange={(event) => setDescription(event.target.value)} value={description} />
        </label>
      </div>
    </form>
  );
}

function IssueDetailView({
  issues,
  onUpdateIssue,
  runAction,
  team,
  uiState
}: {
  issues: DemoIssue[];
  onUpdateIssue: (issue: DemoIssue) => void;
  runAction: (action: DemoAction) => void;
  team: DemoTeamMember[];
  uiState: SessionUiState;
}) {
  const selectedIssueId = uiState.selected_issue_id ?? "LIN-142";
  const issue = issues.find((item) => item.id === selectedIssueId) ?? issues[0] ?? demoIssues[0];
  const isAssignmentHighlighted =
    uiState.highlighted_target === "assignment_control" ||
    uiState.highlighted_target === `assignee_${issue.id}`;
  const isCreatedIssue = uiState.highlighted_target === "created_issue";
  const isUpdatedIssue = uiState.highlighted_target === "updated_issue";

  return (
    <div className="surface-stack">
      <article className="panel" data-testid="issue-detail-panel">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Issue Detail</p>
            <h2>{issue.title}</h2>
          </div>
          <div className="panel-actions">
            <button
              className="secondary-button compact"
              onClick={() => runAction({ type: "OPEN_ISSUES" })}
              type="button"
            >
              Back to issues
            </button>
            {isCreatedIssue && <span className="quiet-badge active-status">Created now</span>}
            {isUpdatedIssue && <span className="quiet-badge active-status">Updated now</span>}
            <span className="quiet-badge" data-testid="selected-issue-id">
              {issue.id}
            </span>
          </div>
        </div>
        <div className="detail-layout">
          <div className="detail-main">
            <div className="detail-description">
              <h3>Description</h3>
              <p>
                {issue.description ||
                  "Capture the request, assign an owner, and track it through the current cycle."}
              </p>
            </div>
            <div className="detail-meta-grid">
              <div className="meta-item">
                <span>Project</span>
                <strong>{issue.project}</strong>
              </div>
              <div className="meta-item">
                <span>Cycle</span>
                <strong>{issue.cycle || "Unassigned"}</strong>
              </div>
              <div className="meta-item">
                <span>Estimate</span>
                <strong>{issue.estimate || "2 pts"}</strong>
              </div>
              <div className="meta-item">
                <span>Label</span>
                <strong>{issue.label || "Customer"}</strong>
              </div>
            </div>
          </div>

          <aside className="detail-sidebar">
            <div
              className={isAssignmentHighlighted ? "property-row highlighted" : "property-row"}
              data-testid="assignee-control"
            >
              <span>Assignee</span>
              <select
                className="property-select"
                data-testid="assignee-select"
                onChange={(event) => onUpdateIssue({ ...issue, assignee: event.target.value })}
                value={issue.assignee}
              >
                {team.map((member) => (
                  <option key={member.name} value={member.name}>
                    {member.name} ({member.role})
                  </option>
                ))}
                {!team.some((m) => m.name === issue.assignee) && (
                  <option value={issue.assignee}>
                    {issue.assignee} (External)
                  </option>
                )}
              </select>
            </div>
            <div className="property-row">
              <span>Priority</span>
              <select
                className="property-select"
                onChange={(event) =>
                  onUpdateIssue({ ...issue, priority: event.target.value as DemoIssue["priority"] })
                }
                value={issue.priority}
              >
                {priorities.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </div>
            <div className="property-row">
              <span>Status</span>
              <select
                className="property-select"
                onChange={(event) => onUpdateIssue({ ...issue, status: event.target.value })}
                value={issue.status}
              >
                {issueStatuses.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </div>
            <button
              className="secondary-button"
              data-testid="highlight-assignee-button"
              onClick={() =>
                runAction({
                  type: "HIGHLIGHT_ASSIGNMENT_CONTROL",
                  payload: { issue_id: issue.id }
                })
              }
              type="button"
            >
              Highlight assignee
            </button>
          </aside>
        </div>
      </article>
    </div>
  );
}

function ProjectsView({
  createProject,
  highlightedTarget,
  projects
}: {
  createProject: (project: DemoProject) => void;
  highlightedTarget?: string;
  projects: DemoProject[];
}) {
  const [isCreating, setIsCreating] = useState(false);

  return (
    <div className="surface-stack">
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Roadmap</p>
            <h2>Active projects</h2>
          </div>
          <div className="panel-actions">
            <button
              className={
                highlightedTarget === "create_project_button"
                  ? "primary-button highlighted-action"
                  : "primary-button"
              }
              data-testid="create-project-button"
              onClick={() => setIsCreating((isOpen) => !isOpen)}
              type="button"
            >
              Create project
            </button>
            <span className="quiet-badge">{projects.length} active</span>
          </div>
        </div>

        {isCreating && (
          <ProjectCreatePanel
            onCancel={() => setIsCreating(false)}
            onCreate={(project) => {
              createProject(project);
              setIsCreating(false);
            }}
            projects={projects}
          />
        )}

        <div className="project-list">
          {projects.map((project) => (
            <article className="project-row" key={project.id || project.name}>
              <div>
                <div className="project-header-line">
                  <h3>{project.name}</h3>
                  <span className={`status-tag status-${project.status.toLowerCase().replace(/\s+/g, "-")}`}>
                    {project.status}
                  </span>
                </div>
                <p>{project.description}</p>
                <div className="project-meta-line">
                  <span>Lead: <strong>{project.lead || "Avery Brooks"}</strong></span>
                  <span>Team: <strong>{project.team || "Engineering"}</strong></span>
                  {project.targetDate && <span>Target: <strong>{project.targetDate}</strong></span>}
                </div>
              </div>
              <div className="progress-cell">
                <div className="progress-bar">
                  <span style={{ width: `${project.progress}%` }} />
                </div>
                <strong>{project.progress}%</strong>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function ProjectCreatePanel({
  onCancel,
  onCreate,
  projects
}: {
  onCancel: () => void;
  onCreate: (project: DemoProject) => void;
  projects: DemoProject[];
}) {
  const [name, setName] = useState("Design System V2");
  const [description, setDescription] = useState(
    "Standardize dynamic tokens, accessible dark mode components, and responsive grid patterns across the product."
  );
  const [status, setStatus] = useState<DemoProject["status"]>("Active");
  const [lead, setLead] = useState(demoTeam[0]?.name ?? "Maya Chen");
  const [team, setTeam] = useState("Product Engineering");
  const [targetDate, setTargetDate] = useState("2026-11-15");
  const [progress, setProgress] = useState(25);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) return;

    const nextIdNumber =
      Math.max(
        ...projects
          .map((p) => Number(p.id.match(/\d+/)?.[0]))
          .filter(Number.isFinite),
        100
      ) + 1;

    onCreate({
      id: `PRJ-${nextIdNumber}`,
      name: trimmedName,
      description: description.trim() || "No description provided.",
      progress,
      status,
      lead,
      team,
      targetDate
    });
  }

  return (
    <form className="creation-panel" data-testid="project-create-panel" onSubmit={handleSubmit}>
      <div className="creation-header">
        <div>
          <p className="section-kicker">New Project</p>
          <h3>Create project</h3>
        </div>
        <div className="panel-actions">
          <button className="secondary-button compact" onClick={onCancel} type="button">
            Cancel
          </button>
          <button className="primary-button" data-testid="submit-create-project" type="submit">
            Create
          </button>
        </div>
      </div>
      <div className="form-grid">
        <label className="field wide">
          <span>Project Name</span>
          <input
            data-testid="project-name-input"
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Design System V2"
            required
            value={name}
          />
        </label>
        <label className="field wide">
          <span>Description</span>
          <textarea
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What is the goal of this project?"
            value={description}
          />
        </label>
        <label className="field">
          <span>Lead</span>
          <select onChange={(event) => setLead(event.target.value)} value={lead}>
            {demoTeam.map((member) => (
              <option key={member.name} value={member.name}>
                {member.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Status</span>
          <select onChange={(event) => setStatus(event.target.value as DemoProject["status"])} value={status}>
            <option value="Planned">Planned</option>
            <option value="Active">Active</option>
            <option value="At risk">At risk</option>
            <option value="Completed">Completed</option>
          </select>
        </label>
        <label className="field">
          <span>Team</span>
          <select onChange={(event) => setTeam(event.target.value)} value={team}>
            <option value="Product Engineering">Product Engineering</option>
            <option value="Platform">Platform</option>
            <option value="Design">Design</option>
          </select>
        </label>
        <label className="field">
          <span>Target Date</span>
          <input
            onChange={(event) => setTargetDate(event.target.value)}
            type="date"
            value={targetDate}
          />
        </label>
        <label className="field wide">
          <span>Initial Progress ({progress}%)</span>
          <input
            max="100"
            min="0"
            onChange={(event) => setProgress(Number(event.target.value))}
            type="range"
            value={progress}
          />
        </label>
      </div>
    </form>
  );
}

function CyclesView({
  createCycle,
  cycles,
  highlightedTarget
}: {
  createCycle: (cycle: DemoCycle) => void;
  cycles: DemoCycle[];
  highlightedTarget?: string;
}) {
  const [isCreating, setIsCreating] = useState(false);

  return (
    <div className="surface-stack">
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Sprint Planning</p>
            <h2>Cycles</h2>
          </div>
          <div className="panel-actions">
            <button
              className={
                highlightedTarget === "create_cycle_button"
                  ? "primary-button highlighted-action"
                  : "primary-button"
              }
              data-testid="create-cycle-button"
              onClick={() => setIsCreating((isOpen) => !isOpen)}
              type="button"
            >
              Create cycle
            </button>
            <span className="quiet-badge">{cycles.length} active</span>
          </div>
        </div>

        {isCreating && (
          <CycleCreatePanel
            cycles={cycles}
            onCancel={() => setIsCreating(false)}
            onCreate={(cycle) => {
              createCycle(cycle);
              setIsCreating(false);
            }}
          />
        )}

        <div className="cycles-stack">
          {cycles.map((cycle) => (
            <article className="cycle-card-item" key={cycle.id || cycle.name}>
              <div className="cycle-card-top">
                <div>
                  <div className="cycle-title-group">
                    <h3>{cycle.name}</h3>
                    <span className={`status-tag status-${cycle.status.toLowerCase()}`}>
                      {cycle.status}
                    </span>
                  </div>
                  <p className="cycle-meta-text">
                    {cycle.startDate} to {cycle.endDate} • <strong>{cycle.daysLeft} days left</strong>
                  </p>
                </div>
                <span className="quiet-badge">{cycle.team}</span>
              </div>
              <CycleProgress compact cycle={cycle} highlighted={highlightedTarget === "cycle_progress"} />
              <div className="focus-section">
                <span className="focus-label">Cycle focus:</span>
                <div className="focus-list">
                  {cycle.focus.map((item) => (
                    <span key={item}>{item}</span>
                  ))}
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function CycleCreatePanel({
  cycles,
  onCancel,
  onCreate
}: {
  cycles: DemoCycle[];
  onCancel: () => void;
  onCreate: (cycle: DemoCycle) => void;
}) {
  const [name, setName] = useState("Frontend Cycle 15");
  const [status, setStatus] = useState<DemoCycle["status"]>("Active");
  const [team, setTeam] = useState("Product Engineering");
  const [startDate, setStartDate] = useState("2026-09-09");
  const [endDate, setEndDate] = useState("2026-09-23");
  const [focusInput, setFocusInput] = useState("");
  const [focusTags, setFocusTags] = useState<string[]>([
    "Assignee Workflow",
    "Real-time Voice",
    "Ticket Reassignment"
  ]);

  function addFocusTag() {
    const trimmed = focusInput.trim();
    if (trimmed && !focusTags.includes(trimmed)) {
      setFocusTags([...focusTags, trimmed]);
      setFocusInput("");
    }
  }

  function removeFocusTag(tagToRemove: string) {
    setFocusTags(focusTags.filter((t) => t !== tagToRemove));
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) return;

    const nextIdNumber =
      Math.max(
        ...cycles
          .map((c) => Number(c.id.match(/\d+/)?.[0]))
          .filter(Number.isFinite),
        14
      ) + 1;

    const endMs = new Date(endDate).getTime();
    const nowMs = Date.now();
    const daysLeft = Math.max(0, Math.ceil((endMs - nowMs) / (1000 * 60 * 60 * 24)));

    onCreate({
      id: `CYC-${nextIdNumber}`,
      name: trimmedName,
      daysLeft: daysLeft || 14,
      progress: 0,
      completed: 0,
      inProgress: 0,
      remaining: 0,
      focus: focusTags.length > 0 ? focusTags : ["General development"],
      status,
      team,
      startDate,
      endDate
    });
  }

  return (
    <form className="creation-panel" data-testid="cycle-create-panel" onSubmit={handleSubmit}>
      <div className="creation-header">
        <div>
          <p className="section-kicker">New Sprint / Cycle</p>
          <h3>Create cycle</h3>
        </div>
        <div className="panel-actions">
          <button className="secondary-button compact" onClick={onCancel} type="button">
            Cancel
          </button>
          <button className="primary-button" data-testid="submit-create-cycle" type="submit">
            Create
          </button>
        </div>
      </div>
      <div className="form-grid">
        <label className="field wide">
          <span>Cycle Name</span>
          <input
            data-testid="cycle-name-input"
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Frontend Cycle 15"
            required
            value={name}
          />
        </label>
        <label className="field">
          <span>Status</span>
          <select onChange={(event) => setStatus(event.target.value as DemoCycle["status"])} value={status}>
            <option value="Planned">Planned</option>
            <option value="Active">Active</option>
            <option value="Completed">Completed</option>
          </select>
        </label>
        <label className="field">
          <span>Team</span>
          <select onChange={(event) => setTeam(event.target.value)} value={team}>
            <option value="Product Engineering">Product Engineering</option>
            <option value="Platform">Platform</option>
            <option value="Design">Design</option>
          </select>
        </label>
        <label className="field">
          <span>Start Date</span>
          <input
            onChange={(event) => setStartDate(event.target.value)}
            type="date"
            value={startDate}
          />
        </label>
        <label className="field">
          <span>End Date</span>
          <input
            onChange={(event) => setEndDate(event.target.value)}
            type="date"
            value={endDate}
          />
        </label>
        <div className="field wide">
          <span>Focus Areas (Tags)</span>
          <div className="tag-input-row">
            <input
              onChange={(e) => setFocusInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addFocusTag();
                }
              }}
              placeholder="Type a focus area and press Enter or Add..."
              value={focusInput}
            />
            <button
              className="secondary-button compact"
              onClick={(e) => {
                e.preventDefault();
                addFocusTag();
              }}
              type="button"
            >
              Add Tag
            </button>
          </div>
          <div className="tag-pill-cloud">
            {focusTags.map((tag) => (
              <span className="tag-pill" key={tag}>
                {tag}
                <button onClick={() => removeFocusTag(tag)} type="button">
                  x
                </button>
              </span>
            ))}
          </div>
        </div>
      </div>
    </form>
  );
}

function TeamsView({
  createTeamMember,
  draftPrefill,
  highlightedTarget,
  team
}: {
  createTeamMember: (member: DemoTeamMember) => void;
  draftPrefill?: DraftPrefill["teamMember"];
  highlightedTarget?: string;
  team: DemoTeamMember[];
}) {
  const [isCreating, setIsCreating] = useState(
    highlightedTarget === "add_member_button" || Boolean(draftPrefill)
  );

  useEffect(() => {
    if (highlightedTarget === "add_member_button" || draftPrefill) {
      setIsCreating(true);
    }
  }, [draftPrefill, highlightedTarget]);

  return (
    <div className="surface-stack">
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Team</p>
            <h2>Engineering capacity</h2>
          </div>
          <div className="panel-actions">
            <button
              className={
                highlightedTarget === "add_member_button" || isCreating
                  ? "primary-button highlighted-action"
                  : "primary-button"
              }
              data-testid="add-team-member-button"
              onClick={() => setIsCreating((isOpen) => !isOpen)}
              type="button"
            >
              + Add Member
            </button>
            <span className="quiet-badge" data-testid="team-member-count">
              {team.length} members
            </span>
          </div>
        </div>
        {isCreating && (
          <TeamMemberCreatePanel
            onCancel={() => setIsCreating(false)}
            onCreate={(member) => {
              createTeamMember(member);
              setIsCreating(false);
            }}
            prefill={draftPrefill}
          />
        )}
        <div className="team-grid">
          {team.map((member) => (
            <article className="member-card" key={member.name}>
              <div className="avatar">{member.initials}</div>
              <div>
                <h3>{member.name}</h3>
                <p>{member.role}</p>
                {member.email && <p>{member.email}</p>}
              </div>
              <strong>{member.load}%</strong>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function TeamMemberCreatePanel({
  onCancel,
  onCreate,
  prefill
}: {
  onCancel: () => void;
  onCreate: (member: DemoTeamMember) => void;
  prefill?: DraftPrefill["teamMember"];
}) {
  const [name, setName] = useState(prefill?.name ?? "");
  const [initials, setInitials] = useState(initialsForName(prefill?.name ?? ""));
  const [email, setEmail] = useState(emailForName(prefill?.name ?? ""));
  const [role, setRole] = useState("Product Engineer");
  const [load, setLoad] = useState(50);

  useEffect(() => {
    if (!prefill?.name) return;
    setName(prefill.name);
    setInitials(initialsForName(prefill.name));
    setEmail(emailForName(prefill.name));
  }, [prefill]);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) return;

    onCreate({
      name: trimmedName,
      initials: initials.trim().toUpperCase() || initialsForName(trimmedName),
      role,
      load: Number(load),
      email: email.trim() || emailForName(trimmedName)
    });
  }

  return (
    <form className="creation-panel" data-testid="team-member-create-panel" onSubmit={handleSubmit}>
      <div className="creation-header">
        <div>
          <p className="section-kicker">New Employee</p>
          <h3>Add team member</h3>
        </div>
        <div className="panel-actions">
          <button className="secondary-button compact" onClick={onCancel} type="button">
            Cancel
          </button>
          <button className="primary-button" data-testid="submit-create-member" type="submit">
            Add Member
          </button>
        </div>
      </div>
      <div className="form-grid">
        <label className="field wide">
          <span>Full Name</span>
          <input
            data-testid="member-name-input"
            onChange={(event) => {
              setName(event.target.value);
              setInitials(initialsForName(event.target.value));
              setEmail(emailForName(event.target.value));
            }}
            placeholder="e.g. Lucifer Morningstar"
            required
            value={name}
          />
        </label>
        <label className="field">
          <span>Initials</span>
          <input
            data-testid="member-initials-input"
            maxLength={3}
            onChange={(event) => setInitials(event.target.value)}
            placeholder="LM"
            value={initials}
          />
        </label>
        <label className="field">
          <span>Email</span>
          <input
            data-testid="member-email-input"
            onChange={(event) => setEmail(event.target.value)}
            placeholder="lucifer@pixel.demo"
            type="email"
            value={email}
          />
        </label>
        <label className="field">
          <span>Role</span>
          <select onChange={(event) => setRole(event.target.value)} value={role}>
            <option value="Product Engineer">Product Engineer</option>
            <option value="Frontend Lead">Frontend Lead</option>
            <option value="Backend Engineer">Backend Engineer</option>
            <option value="Engineering Manager">Engineering Manager</option>
            <option value="Product Designer">Product Designer</option>
            <option value="DevOps / Platform">DevOps / Platform</option>
          </select>
        </label>
        <label className="field">
          <span>Current Workload (%)</span>
          <input
            max="100"
            min="0"
            onChange={(event) => setLoad(Number(event.target.value))}
            type="number"
            value={load}
          />
        </label>
      </div>
    </form>
  );
}

function IntegrationsView({ highlightedTarget }: { highlightedTarget?: string }) {
  const showGithubSetup = highlightedTarget === "github_setup";
  const highlightGithub = showGithubSetup || highlightedTarget === "github_card";
  const highlightSlack = highlightedTarget === "slack_card";

  return (
    <div className="surface-stack">
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="section-kicker">Connected Workflow</p>
            <h2>Integrations</h2>
          </div>
          <span className="quiet-badge">{connectedIntegrationCount} connected</span>
        </div>
        <div className="integration-grid">
          {integrations.map((integration) => (
            <article
              className={
                integration.name === "GitHub" && highlightGithub
                  ? "integration-card highlighted-card"
                  : integration.name === "Slack" && highlightSlack
                    ? "integration-card highlighted-card"
                  : "integration-card"
              }
              data-testid={
                integration.name === "GitHub"
                  ? "github-integration-card"
                  : integration.name === "Slack"
                    ? "slack-integration-card"
                    : undefined
              }
              key={integration.name}
            >
              <div>
                <h3>{integration.name}</h3>
                <p>{integration.description}</p>
              </div>
              <span className={integration.connected ? "connected" : "available"}>
                {integration.connected ? "Connected" : "Available"}
              </span>
            </article>
          ))}
        </div>
        {showGithubSetup && (
          <div className="setup-panel" data-testid="github-setup-panel">
            <p className="section-kicker">GitHub Setup</p>
            <div className="setup-steps">
              <span>Authorize workspace</span>
              <span>Select repositories</span>
              <span>Sync PR activity</span>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function Metric({ label, value, delta }: { label: string; value: string; delta: string }) {
  return (
    <article className="metric-card">
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{delta}</span>
    </article>
  );
}

function IssueList({
  assigneeFilter,
  issues,
  limit,
  runAction
}: {
  assigneeFilter?: string;
  issues: DemoIssue[];
  limit?: number;
  runAction: (action: DemoAction) => void;
}) {
  const filteredIssues = assigneeFilter
    ? issues.filter((issue) => issue.assignee === assigneeFilter)
    : issues;
  const visibleIssues = typeof limit === "number" ? filteredIssues.slice(0, limit) : filteredIssues;

  return (
    <div className="issue-list">
      {visibleIssues.map((issue) => (
        <article className="issue-row" key={issue.id}>
          <div className="issue-main">
            <h3>{issue.title}</h3>
            <p>
              {issue.id} - {issue.assignee} - {issue.project}
            </p>
          </div>
          <div className="issue-controls">
            <span className={`priority ${issue.priority.toLowerCase()}`}>{issue.priority}</span>
            <span className="issue-status">{issue.status}</span>
            <button
              aria-label={`Open ${issue.id}`}
              className="row-button"
              onClick={() => runAction({ type: "OPEN_DEMO_ISSUE", payload: { issue_id: issue.id } })}
              type="button"
            >
              Open
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}

function CycleProgress({
  cycle = demoCycle,
  compact = false,
  highlighted = false
}: {
  cycle?: DemoCycle;
  compact?: boolean;
  highlighted?: boolean;
}) {
  return (
    <div className={compact ? "cycle compact" : "cycle"}>
      <div className="cycle-summary">
        <div>
          <p>Completed</p>
          <strong>{cycle.completed}</strong>
        </div>
        <div>
          <p>In progress</p>
          <strong>{cycle.inProgress}</strong>
        </div>
        <div>
          <p>Remaining</p>
          <strong>{cycle.remaining}</strong>
        </div>
      </div>
      <div
        className={highlighted ? "progress-bar large highlighted-bar" : "progress-bar large"}
        data-testid="cycle-progress-bar"
      >
        <span style={{ width: `${cycle.progress}%` }} />
      </div>
      {!compact && (
        <p className="body-copy">
          This screen is where the agent will land when a visitor asks about sprint planning,
          time-boxed work, cycle health, or replacing Jira sprint workflows.
        </p>
      )}
    </div>
  );
}

function IntentTraceCard({ trace }: { trace: IntentTrace }) {
  return (
    <section className="panel trace-card">
      <div className="panel-header">
        <div>
          <p className="section-kicker">Intent Trace</p>
          <h2>Understanding panel</h2>
        </div>
        <span className="quiet-badge" data-testid="trace-status">
          {trace.status}
        </span>
      </div>
      <dl className="trace-list">
        <TraceItem label="Role" testId="trace-role" value={trace.role} />
        <TraceItem label="Current tool" testId="trace-current-tool" value={trace.current_tool} />
        <TraceItem label="Goal" testId="trace-goal" value={trace.goal} />
        <TraceItem label="Pain point" testId="trace-pain-point" value={trace.pain_point} />
        <TraceItem
          label="Relevant feature"
          testId="trace-relevant-feature"
          value={trace.relevant_feature}
        />
        <TraceItem label="Why this view" testId="trace-reason" value={trace.reason} />
      </dl>
      <div className="confidence">
        <span>Confidence</span>
        <div className="progress-bar">
          <span style={{ width: `${Math.round((trace.confidence ?? 0) * 100)}%` }} />
        </div>
      </div>
    </section>
  );
}

function SessionSummaryCard({ summary }: { summary: SessionSummary }) {
  const interests = summary.interests.length > 0 ? summary.interests : ["None yet"];
  const painPoints = summary.pain_points.length > 0 ? summary.pain_points : ["None yet"];

  return (
    <section className="panel session-card" data-testid="session-summary">
      <div className="panel-header">
        <div>
          <p className="section-kicker">Session Intelligence</p>
          <h2>Visitor context</h2>
        </div>
      </div>
      <div className="session-grid">
        <SummaryGroup label="Interests" values={interests} />
        <SummaryGroup label="Pain points" values={painPoints} />
        <div className="summary-pair" data-testid="session-last-person">
          <span>Last person</span>
          <strong>{summary.last_person ?? "None"}</strong>
        </div>
        <div className="summary-pair" data-testid="session-last-feature">
          <span>Last feature</span>
          <strong>{summary.last_feature ?? "None"}</strong>
        </div>
        {summary.clarification_pending && (
          <div className="summary-pair wide" data-testid="session-clarification">
            <span>Clarifying</span>
            <strong>{summary.clarification_pending}</strong>
          </div>
        )}
      </div>
    </section>
  );
}

function SummaryGroup({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="summary-pair">
      <span>{label}</span>
      <strong>{values.join(", ")}</strong>
    </div>
  );
}

function TraceItem({
  label,
  testId,
  value
}: {
  label: string;
  testId: string;
  value?: string;
}) {
  return (
    <div className="trace-item" data-testid={testId}>
      <dt>{label}</dt>
      <dd>{value ?? "Not detected"}</dd>
    </div>
  );
}

function ActionConsole({ runAction }: { runAction: (action: DemoAction) => void }) {
  return (
    <div className="action-console">
      <p className="section-kicker">Action Registry</p>
      <div className="action-grid">
        <button
          data-testid="action-open-cycles"
          onClick={() => runAction({ type: "OPEN_CYCLES" })}
          type="button"
        >
          Open Cycles
        </button>
        <button
          data-testid="action-open-issues"
          onClick={() => runAction({ type: "OPEN_ISSUES" })}
          type="button"
        >
          Open Issues
        </button>
        <button
          data-testid="action-open-demo-issue"
          onClick={() => runAction({ type: "OPEN_DEMO_ISSUE", payload: { issue_id: "LIN-142" } })}
          type="button"
        >
          Open Demo Issue
        </button>
        <button
          data-testid="action-create-demo-issue"
          onClick={() =>
            runAction({
              type: "CREATE_DEMO_ISSUE",
              payload: {
                id: "PIX-143",
                title: "Investigate login issue",
                priority: "Medium",
                assignee: "Maya Chen",
                project: "Issue Triage",
                status: "Todo"
              }
            })
          }
          type="button"
        >
          Create Demo Issue
        </button>
        <button
          data-testid="action-open-github-setup"
          onClick={() => runAction({ type: "OPEN_GITHUB_SETUP" })}
          type="button"
        >
          GitHub Setup
        </button>
        <button
          data-testid="action-highlight-assignee"
          onClick={() =>
            runAction({ type: "HIGHLIGHT_ASSIGNMENT_CONTROL", payload: { issue_id: "LIN-142" } })
          }
          type="button"
        >
          Highlight Assignee
        </button>
        <button
          data-testid="action-highlight-cycle"
          onClick={() => runAction({ type: "HIGHLIGHT_CYCLE_PROGRESS" })}
          type="button"
        >
          Highlight Cycle
        </button>
      </div>
    </div>
  );
}

function UiEventLog({ events }: { events: UiEvent[] }) {
  return (
    <div className="event-log-card" data-testid="event-log">
      <p className="section-kicker">UI Events</p>
      {events.length === 0 ? (
        <p className="empty-state">No actions executed yet.</p>
      ) : (
        <div className="event-list">
          {events.map((event) => (
            <article className="event-row" key={event.id}>
              <span className={event.status}>{event.status}</span>
              <div>
                <strong>{event.action_type}</strong>
                <p>{event.description}</p>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function DiagnosticsPanel({
  events,
  runAction
}: {
  events: UiEvent[];
  runAction: (action: DemoAction) => void;
}) {
  return (
    <details className="diagnostics-panel" data-testid="diagnostics-panel">
      <summary>Developer diagnostics</summary>
      <ActionConsole runAction={runAction} />
      <UiEventLog events={events} />
    </details>
  );
}

function ConversationCard({
  demoPrompts,
  isSending,
  messages,
  onCollapse,
  onReset,
  onSend,
  turnStatus
}: {
  demoPrompts: string[];
  isSending: boolean;
  messages: TranscriptMessage[];
  onCollapse: () => void;
  onReset: () => void;
  onSend: (message: string, inputMode?: InputMode) => Promise<AgentTurnResponse | null>;
  turnStatus: TurnStatus;
}) {
  const [draft, setDraft] = useState("");
  const [voiceEngineStatus, setVoiceEngineStatus] = useState<VoiceEngineStatus>("Idle");
  const [voiceEngineMode, setVoiceEngineMode] = useState<VoiceEngineMode>("gemini");
  const [spectrum, setSpectrum] = useState<SpectrumData>([15, 20, 15, 18, 12]);
  const [liveTranscript, setLiveTranscript] = useState("");
  const [voiceError, setVoiceError] = useState("");
  const [isTTSEnabled, setIsTTSEnabled] = useState(true);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const voiceEngineRef = useRef<HybridVoiceEngine | null>(null);
  const onSendRef = useRef(onSend);
  const isTTSEnabledRef = useRef(isTTSEnabled);
  const mockVoiceTranscriptRef = useRef("");
  const mockVoiceTimerRef = useRef<number | null>(null);
  const hasAutoGreeted = useRef(false);
  const isSubmittingVoiceRef = useRef(false);
  const isAgentSpeakingRef = useRef(false);
  const isVoiceActive = voiceEngineStatus !== "Idle" && voiceEngineStatus !== "Error";

  useEffect(() => {
    onSendRef.current = onSend;
  }, [onSend]);

  useEffect(() => {
    isTTSEnabledRef.current = isTTSEnabled;
  }, [isTTSEnabled]);

  useEffect(() => {
    transcriptRef.current?.scrollTo({
      top: transcriptRef.current.scrollHeight,
      behavior: "smooth"
    });
  }, [messages, liveTranscript]);

  useEffect(() => {
    // Initialize Hybrid Voice Engine
    const engine = new HybridVoiceEngine({
      onStatusChange: (status, mode) => {
        setVoiceEngineStatus(status);
        setVoiceEngineMode(mode);
        if (status !== "Error") {
          setVoiceError("");
        }
        if (status === "Idle") {
          setLiveTranscript("");
        }
      },
      onSpectrumChange: (newSpectrum) => {
        setSpectrum(newSpectrum);
      },
      onUserTranscript: (text, isFinal) => {
        if (isAgentSpeakingRef.current || isSubmittingVoiceRef.current) return;

        // Discard any mic transcript that captured Edith's own greeting or response text
        const lower = text.toLowerCase().trim();
        const selfEchoKeywords = [
          "welcome",
          "pixel",
          "edith",
          "guide to planning",
          "planning work",
          "tracking tickets",
          "connecting your",
          "what brought you",
          "check us out",
          "created pix-",
          "assigned it to",
          "i'll open",
          "i found"
        ];
        if (selfEchoKeywords.some((kw) => lower.includes(kw))) {
          return;
        }

        setLiveTranscript(text);
        if (isFinal && text.trim()) {
          isSubmittingVoiceRef.current = true;
          setLiveTranscript("");
          engine.pauseListening();
          void (async () => {
            try {
              const result = await onSendRef.current(text, "voice");
              if (result?.speech && isTTSEnabledRef.current) {
                isAgentSpeakingRef.current = true;
                await engine.speakLocalResponse(result.speech, () => {
                  isAgentSpeakingRef.current = false;
                  engine.stop();
                }, false);
              } else {
                engine.stop();
              }
            } finally {
              isSubmittingVoiceRef.current = false;
              engine.stop();
              setLiveTranscript("");
            }
          })();
        }
      },
      onAgentSpeech: () => {
        isAgentSpeakingRef.current = true;
      },
      onError: (err) => {
        setVoiceError(err);
      }
    });

    voiceEngineRef.current = engine;

    // Speak initial introduction greeting on visit.
    // Browser autoplay policy blocks speechSynthesis until user interacts,
    // so we also register one-time gesture listeners as a fallback.
    if (!hasAutoGreeted.current && !shouldDisableAutoGreetingSpeech()) {
      hasAutoGreeted.current = true;
      const greetingText = initialTranscript[0]?.text;
      if (greetingText) {
        let greetingSpoken = false;

        const speakGreeting = () => {
          if (greetingSpoken) return;
          greetingSpoken = true;
          isAgentSpeakingRef.current = true;
          engine.speakOnly(greetingText, () => {
            isAgentSpeakingRef.current = false;
          });
        };

        // Try immediately (works if cloud TTS responds — cloud audio bypasses autoplay)
        speakGreeting();

        // Also register gesture listeners for browser voice fallback
        const onGesture = () => {
          speakGreeting();
          window.removeEventListener("pointerdown", onGesture);
          window.removeEventListener("click", onGesture);
          window.removeEventListener("keydown", onGesture);
        };
        window.addEventListener("pointerdown", onGesture, { once: true });
        window.addEventListener("click", onGesture, { once: true });
        window.addEventListener("keydown", onGesture, { once: true });
      }
    }

    if (isVoiceTestMode()) {
      const speechWindow = window as SpeechRecognitionWindow;
      speechWindow.__emitVoiceTranscript = (transcript: string) => {
        mockVoiceTranscriptRef.current = `${mockVoiceTranscriptRef.current} ${transcript}`.trim();
        setLiveTranscript(mockVoiceTranscriptRef.current);

        if (mockVoiceTimerRef.current !== null) {
          window.clearTimeout(mockVoiceTimerRef.current);
        }

        mockVoiceTimerRef.current = window.setTimeout(() => {
          const finalTranscript = mockVoiceTranscriptRef.current.trim();
          mockVoiceTranscriptRef.current = "";
          setLiveTranscript("");
          if (!finalTranscript) return;

          setVoiceEngineStatus("Thinking");
          void (async () => {
            const result = await onSendRef.current(finalTranscript, "voice");
            setVoiceEngineStatus(result?.speech ? "Speaking" : "Idle");
          })();
        }, getVoiceSilenceTimeoutMs());
      };
    }

    return () => {
      if (mockVoiceTimerRef.current !== null) {
        window.clearTimeout(mockVoiceTimerRef.current);
      }
      if (typeof window !== "undefined") {
        delete (window as SpeechRecognitionWindow).__emitVoiceTranscript;
      }
      engine.stop();
    };
  }, []);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = draft;
    setDraft("");
    setLiveTranscript("");
    voiceEngineRef.current?.cancelSpeech();
    void (async () => {
      const result = await onSend(message, "text");
      if (result?.speech && isTTSEnabledRef.current) {
        voiceEngineRef.current?.speakOnly(result.speech);
      }
    })();
  }

  function toggleVoiceInput() {
    if (isVoiceTestMode()) {
      if (voiceEngineStatus === "Listening") {
        if (mockVoiceTimerRef.current !== null) {
          window.clearTimeout(mockVoiceTimerRef.current);
        }
        mockVoiceTranscriptRef.current = "";
        setLiveTranscript("");
        setVoiceEngineStatus("Idle");
        return;
      }

      setVoiceError("");
      setVoiceEngineStatus("Listening");
      setVoiceEngineMode("local");
      return;
    }

    if (isVoiceActive) {
      hasAutoGreeted.current = true;
      voiceEngineRef.current?.stop();
    } else {
      hasAutoGreeted.current = true;
      isAgentSpeakingRef.current = false;
      voiceEngineRef.current?.cancelSpeech();
      setVoiceError("");
      void voiceEngineRef.current?.start();
    }
  }

  return (
    <section className="panel conversation-card" aria-busy={isSending}>
      <div className="conversation-topbar">
        <div className="guide-brand">
          <span className="guide-mark" aria-hidden="true">P</span>
          <strong>Pixel</strong>
        </div>
        <div className="conversation-actions">
          <button
            className="reset-button"
            data-testid="assistant-collapse"
            onClick={onCollapse}
            type="button"
          >
            Hide
          </button>
          <button className="reset-button" data-testid="reset-demo" onClick={onReset} type="button">
            Reset
          </button>
          <span
            className={turnStatus === "Ready" ? "quiet-badge" : "quiet-badge active-status"}
            data-testid="turn-status"
          >
            {turnStatus}
          </span>
        </div>
      </div>

      <div className="guide-intro">
        <div className="guide-title-row">
          <div>
            <p className="section-kicker">Live Demo Guide</p>
            <h2>Edith</h2>
          </div>
          <span className={`voice-mode-badge ${voiceEngineMode}`}>
            {voiceEngineMode === "gemini"
              ? "Gemini Voice"
              : voiceEngineMode === "webrtc"
                ? "OpenAI WebRTC"
                : "Enhanced Voice"}
          </span>
        </div>
      </div>

      <div className="transcript" data-testid="transcript" ref={transcriptRef}>
        {messages.map((message, index) => (
          <article
            className={message.speaker === "Visitor" ? "message visitor-message" : "message"}
            key={`${message.speaker}-${index}`}
          >
            <span>{message.speaker}</span>
            <p>{message.text}</p>
          </article>
        ))}
        {liveTranscript && (
          <article className="message visitor-message live-transcript-message">
            <span>Visitor (Speaking...)</span>
            <p>{liveTranscript}</p>
          </article>
        )}
      </div>

      <div className="demo-prompt-strip" aria-label="Suggested demo turns">
        {demoPrompts.map((prompt) => (
          <button
            data-testid={`demo-prompt-${prompt.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`}
            key={prompt}
            onClick={() => {
              setLiveTranscript("");
              voiceEngineRef.current?.cancelSpeech();
              void (async () => {
                const result = await onSend(prompt, "text");
                if (result?.speech && isTTSEnabledRef.current) {
                  voiceEngineRef.current?.speakOnly(result.speech);
                }
              })();
            }}
            type="button"
          >
            {prompt}
          </button>
        ))}
      </div>

      <form className="chat-form" onSubmit={handleSubmit}>
        <span className="input-mark" aria-hidden="true">P</span>
        <input
          data-testid="chat-input"
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask Edith"
          suppressHydrationWarning
          value={draft}
        />
        <button data-testid="chat-send" disabled={!draft.trim()} type="submit">
          Send
        </button>
      </form>

      {/* Voice Control Card */}
      <div className={`voice-control-card ${isVoiceActive ? "active" : ""}`}>
        <div className="voice-control-top">
          <button
            aria-pressed={isVoiceActive}
            className={`voice-toggle-btn ${isVoiceActive ? "active" : ""}`}
            data-testid="voice-toggle"
            onClick={toggleVoiceInput}
            type="button"
          >
            <span className={`voice-dot ${voiceEngineStatus.toLowerCase()}`} />
            {isVoiceActive ? "End Voice" : "Start Realtime Voice"}
          </button>

          <button
            aria-pressed={isTTSEnabled}
            className={`tts-toggle-btn ${isTTSEnabled ? "active" : ""}`}
            data-testid="tts-toggle"
            onClick={() => {
              const nextState = !isTTSEnabled;
              setIsTTSEnabled(nextState);
              if (!nextState) {
                voiceEngineRef.current?.cancelSpeech();
              }
            }}
            title={isTTSEnabled ? "Mute agent voice" : "Unmute agent voice"}
            type="button"
          >
            {isTTSEnabled ? "🔊 Voice On" : "🔇 Voice Off"}
          </button>
        </div>

        <div className="voice-status-line">
          <span className="voice-status-label" data-testid="voice-status">
            Voice: <strong>{voiceEngineStatus}</strong>
          </span>

          {/* 5-Bar Audio Equalizer Spectrum Visualizer */}
          <div className="voice-spectrum-bar" aria-label="Audio Spectrum Visualizer">
            {spectrum.map((height, i) => (
              <span
                className={`spectrum-bar ${isVoiceActive ? "animating" : ""}`}
                key={i}
                style={{ height: `${isVoiceActive ? height : 15}%` }}
              />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function getSpeechRecognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const speechWindow = window as SpeechRecognitionWindow;
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null;
}

function getVoiceSilenceTimeoutMs(): number {
  if (typeof window === "undefined") return DEFAULT_VOICE_SILENCE_TIMEOUT_MS;
  const configuredTimeout = (window as SpeechRecognitionWindow).__demoVoiceSilenceTimeoutMs;
  return typeof configuredTimeout === "number"
    ? configuredTimeout
    : DEFAULT_VOICE_SILENCE_TIMEOUT_MS;
}

function isVoiceTestMode(): boolean {
  return (
    typeof window !== "undefined"
    && typeof (window as SpeechRecognitionWindow).__demoVoiceSilenceTimeoutMs === "number"
  );
}

function shouldDisableAutoGreetingSpeech(): boolean {
  return (
    typeof window !== "undefined"
    && (window as SpeechRecognitionWindow).__disableAutoGreetingSpeech === true
  );
}

function voiceControlTitle(status: VoiceStatus): string {
  if (status === "Listening") return "Stop listening";
  if (status === "Speaking") return "Stop agent voice";
  if (status === "Processing") return "Processing voice input";
  return "Start voice input";
}

function upsertIssue(issues: DemoIssue[], issue: DemoIssue): DemoIssue[] {
  const existingIssueIndex = issues.findIndex((item) => item.id === issue.id);
  if (existingIssueIndex === -1) {
    return [issue, ...issues];
  }

  return issues.map((item, index) => (index === existingIssueIndex ? issue : item));
}

function findTeamMember(team: DemoTeamMember[], name: string): DemoTeamMember | undefined {
  const normalizedName = normalizeText(name);
  return team.find((member) => {
    const memberName = normalizeText(member.name);
    return (
      memberName === normalizedName
      || memberName.split(" ").includes(normalizedName)
      || normalizedName.split(" ").some((part) => memberName.split(" ").includes(part))
    );
  });
}

function asksForEvaluatorDemo(text: string): boolean {
  return (
    /\b(evaluator|judge|reviewer|demo path|demo script|test script)\b/.test(text)
    || text === "run the evaluator demo"
  );
}

function asksWhatChanged(text: string): boolean {
  return /\b(what did we .*change|what changed|what just happened|what did you update)\b/.test(text);
}

function asksCapabilities(text: string): boolean {
  return /\b(are you capable|what can you do|what are you able|what can this do|can you do)\b/.test(text);
}

function correctionActionFor(text: string): DemoAction | null {
  if (!/\b(no|not|instead|rather)\b/.test(text)) return null;
  if (/\b(issue|issues|ticket|tickets|bug|bugs)\b/.test(text)) return { type: "OPEN_ISSUES" };
  if (/\b(cycle|cycles|sprint|planning)\b/.test(text)) return { type: "OPEN_CYCLES" };
  if (/\b(github)\b/.test(text)) return { type: "HIGHLIGHT_GITHUB_CARD" };
  if (/\b(slack)\b/.test(text)) return { type: "HIGHLIGHT_SLACK_CARD" };
  if (/\b(project|projects)\b/.test(text)) return { type: "OPEN_PROJECTS" };
  if (/\b(team|teams|members|people)\b/.test(text)) return { type: "OPEN_TEAMS" };
  return null;
}

function correctionSpeech(action: DemoAction): string {
  if (action.type === "OPEN_ISSUES") return "Got it. I'll switch to Issues.";
  if (action.type === "OPEN_CYCLES") return "Got it. I'll switch to Cycles.";
  if (action.type === "HIGHLIGHT_GITHUB_CARD") return "Got it. I'll show GitHub instead.";
  if (action.type === "HIGHLIGHT_SLACK_CARD") return "Got it. I'll show Slack instead.";
  if (action.type === "OPEN_PROJECTS") return "Got it. I'll switch to Projects.";
  if (action.type === "OPEN_TEAMS") return "Got it. I'll switch to Teams.";
  return "Got it. I'll switch views.";
}

function parseIssueUpdateRequest(message: string): {
  assignee?: string;
  priority?: DemoIssue["priority"];
  status?: string;
} | null {
  const text = normalizeText(message);
  const asksForCreation =
    /\b(create|make|add|raise|file)\b/.test(text) && /\b(ticket|issue|bug)\b/.test(text);
  if (asksForCreation) {
    return null;
  }

  if (
    /\b(how do i assign|how to assign|show assignment|issue assignment)\b/.test(text)
    || (text.includes("where") && text.includes("assign"))
  ) {
    return null;
  }

  const update: {
    assignee?: string;
    priority?: DemoIssue["priority"];
    status?: string;
  } = {};

  if (/\b(assign|owner|reassign)\b/.test(text)) {
    update.assignee = extractAssignmentTarget(message);
  }

  if (/\b(priority|urgent|critical|high|medium|low)\b/.test(text)) {
    update.priority = extractPriority(text);
  }

  const status = extractStatus(text);
  if (status) {
    update.status = status;
  }

  return update.assignee || update.priority || update.status ? update : null;
}

function extractAssignmentTarget(message: string): string | undefined {
  const match = message.match(
    /\b(?:to|for|owner is|assignee is|assigned to|assign it to|assign this to)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)/i
  );
  if (!match?.[1]) return undefined;

  return titleCase(
    match[1]
      .replace(/\b(ticket|issue|bug|priority|status|review|done|todo)\b/gi, "")
      .trim()
  );
}

function extractStatus(text: string): string | undefined {
  if (/\b(done|complete|completed|closed|resolved)\b/.test(text)) return "Done";
  if (/\b(review|qa)\b/.test(text)) return "Review";
  if (/\b(in progress|doing|started|working)\b/.test(text)) return "In progress";
  if (/\b(todo|to do|backlog)\b/.test(text)) return "Todo";
  return undefined;
}

function resolveIssueForMessage(
  message: string,
  issues: DemoIssue[],
  selectedIssueId?: string
): DemoIssue | undefined {
  const explicitId = message.match(/\b(?:LIN|PIX)-\d+\b/i)?.[0]?.toUpperCase();
  if (explicitId) {
    return issues.find((issue) => issue.id.toUpperCase() === explicitId);
  }

  if (/\b(this|that|it|current|same)\b/.test(normalizeText(message))) {
    return issues.find((issue) => issue.id === selectedIssueId);
  }

  const assigneeName = extractAssigneeName(message);
  if (assigneeName) {
    const normalizedAssignee = normalizeText(assigneeName);
    const matchingIssue = issues.find((issue) => {
      const issueAssignee = normalizeText(issue.assignee);
      return (
        issueAssignee === normalizedAssignee
        || issueAssignee.split(" ").includes(normalizedAssignee)
        || normalizedAssignee.split(" ").some((part) => issueAssignee.split(" ").includes(part))
      );
    });
    if (matchingIssue) return matchingIssue;
  }

  if (/\b(her|his)\b/.test(normalizeText(message))) {
    return issues.find((issue) => issue.id === selectedIssueId);
  }

  return selectedIssueId ? issues.find((issue) => issue.id === selectedIssueId) : undefined;
}

function describeIssueChanges(previousIssue: DemoIssue, updatedIssue: DemoIssue): string {
  const changes = [];
  if (previousIssue.assignee !== updatedIssue.assignee) {
    changes.push(`assignee is now ${updatedIssue.assignee}`);
  }
  if (previousIssue.priority !== updatedIssue.priority) {
    changes.push(`priority is now ${updatedIssue.priority}`);
  }
  if (previousIssue.status !== updatedIssue.status) {
    changes.push(`status is now ${updatedIssue.status}`);
  }
  return changes.join(", ") || "the issue details are unchanged";
}

function lowercaseFirst(value: string): string {
  return value ? `${value.charAt(0).toLowerCase()}${value.slice(1)}` : value;
}

function parseTicketDraftRequest(message: string): DraftPrefill["issue"] | null {
  const normalizedMessage = normalizeText(message);
  const asksForCreation =
    /\b(create|make|add|raise|file)\b/.test(normalizedMessage)
    && /\b(ticket|issue|bug)\b/.test(normalizedMessage);

  if (!asksForCreation) return null;

  return {
    assignee: extractAssigneeName(message),
    priority: extractPriority(normalizedMessage),
    title: extractIssueTitle(message)
  };
}

function extractAssigneeName(message: string): string | undefined {
  const match = message.match(
    /\b(?:for|assigned to|assign to|owner is)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)/i
  );
  if (!match) return undefined;

  const stopWords = new Set([
    "about",
    "regarding",
    "with",
    "on",
    "in",
    "as",
    "ticket",
    "issue",
    "bug"
  ]);
  const nameParts = match[1]
    .split(/\s+/)
    .filter((part) => !stopWords.has(part.toLowerCase()));

  return nameParts.length > 0 ? titleCase(nameParts.join(" ")) : undefined;
}

function extractPriority(normalizedMessage: string): DemoIssue["priority"] {
  if (/\b(urgent|critical|high)\b/.test(normalizedMessage)) return "High";
  if (/\blow\b/.test(normalizedMessage)) return "Low";
  return "Medium";
}

function extractIssueTitle(message: string): string {
  const explicitTitle = message.match(/\b(?:about|regarding|named|called)\s+(.+)$/i);
  if (explicitTitle?.[1]) {
    return titleCase(explicitTitle[1].trim());
  }

  const normalizedMessage = normalizeText(message);
  if (normalizedMessage.includes("login") || normalizedMessage.includes("sign in")) {
    return "Investigate login issue";
  }
  if (normalizedMessage.includes("github")) return "Review GitHub sync issue";
  if (normalizedMessage.includes("webhook")) return "Investigate webhook issue";
  if (normalizedMessage.includes("bug")) return "Investigate reported bug";
  return "Investigate customer onboarding issue";
}

function localTurnResponse({
  action,
  message,
  sessionId,
  turnId
}: {
  action: DemoAction | null;
  message: string;
  sessionId: string;
  turnId: number;
}): AgentTurnResponse {
  return {
    session_id: sessionId,
    turn_id: turnId,
    status: "completed",
    speech: message,
    proposed_action: action
      ? {
          type: action.type,
          payload: "payload" in action && action.payload ? action.payload : {}
        }
      : null,
    validated_action: action,
    intent_trace: {
      goal:
        action?.type === "HIGHLIGHT_ADD_MEMBER_BUTTON"
          ? "Validate assignee"
          : action?.type === "UPDATE_DEMO_ISSUE"
            ? "Update issue"
            : "Guide demo",
      current_intent:
        action?.type === "HIGHLIGHT_ADD_MEMBER_BUTTON"
          ? "Add missing team member"
          : action?.type === "UPDATE_DEMO_ISSUE"
            ? "Update issue"
            : "Clarify next step",
      relevant_feature: action?.type === "HIGHLIGHT_ADD_MEMBER_BUTTON" ? "Teams" : "Issues",
      reason: "Handled locally because the browser has the current session directory.",
      confidence: 0.9,
      status: "active"
    },
    signals: [],
    retrieved_context: [],
    session_summary: initialSessionSummary
  };
}

function initialsForName(name: string): string {
  return (
    name
      .trim()
      .split(/\s+/)
      .map((part) => part[0])
      .join("")
      .toUpperCase()
      .slice(0, 2) || ""
  );
}

function emailForName(name: string): string {
  const handle = normalizeText(name).replace(/\s+/g, ".");
  return handle ? `${handle}@pixel.demo` : "";
}

function normalizeText(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
}

function titleCase(value: string): string {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => `${word.charAt(0).toUpperCase()}${word.slice(1).toLowerCase()}`)
    .join(" ");
}

function nextDemoIssueId(issues: DemoIssue[]): string {
  const nextNumber =
    Math.max(
      ...issues
        .map((issue) => Number(issue.id.match(/\d+/)?.[0]))
        .filter(Number.isFinite),
      142
    ) + 1;
  return `PIX-${nextNumber}`;
}

function nextDemoIssue(
  issues: DemoIssue[],
  input: { assignee: string; title: string; priority?: DemoIssue["priority"] }
): DemoIssue {
  const nextNumber =
    Math.max(
      ...issues
        .map((issue) => Number(issue.id.match(/\d+/)?.[0]))
        .filter(Number.isFinite),
      142
    ) + 1;

  return {
    id: `PIX-${nextNumber}`,
    title: input.title,
    priority: input.priority ?? "Medium",
    assignee: input.assignee,
    project: "Issue Triage",
    status: "Todo"
  };
}
