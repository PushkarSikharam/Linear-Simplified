# Implementation Blueprint

This document turns the architecture into the first buildable version.

## 1. Repository Structure

```text
linear-simplified/
  apps/
    web/
      app/
      components/
      lib/
      types/
    api/
      app/
        main.py
        schemas.py
        db.py
        services/
        data/
  docs/
    product/
      cycles.md
      issues.md
      projects.md
      integrations.md
  packages/
    shared/
      actions.ts
      schemas.ts
  README.md
  ARCHITECTURE_PLAN.md
  IMPLEMENTATION_BLUEPRINT.md
```

Why this shape:

- `apps/web` owns the user experience.
- `apps/api` owns the AI, validation, session state, and persistence.
- `docs/product` holds approved product knowledge.
- `packages/shared` can hold action names and shared TypeScript schemas if we use a monorepo setup.

For the first implementation, we can keep it simpler if needed:

```text
frontend/
backend/
docs/product/
```

## 2. Frontend Page Model

The demo app should feel like a small Linear-style work management product.

Pages:

```text
dashboard
issues
issue_detail
projects
cycles
teams
integrations
```

Recommended screen layout:

```text
Left sidebar:
  Product navigation

Center:
  Active product page

Right panel:
  Intent Trace
  Chat/voice controls
  Transcript
```

This matters because the AI behavior must be visible. The user should see the page change and see the Intent Trace update at the same time.

## 3. Frontend State Model

```ts
type DemoPage =
  | "dashboard"
  | "issues"
  | "issue_detail"
  | "projects"
  | "cycles"
  | "teams"
  | "integrations";

type VoiceState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "executing_action";

type IntentTrace = {
  role?: string;
  team_size?: number;
  current_tool?: string;
  goal?: string;
  pain_point?: string;
  current_intent?: string;
  relevant_feature?: string;
  reason?: string;
  confidence?: number;
  status?: "active" | "interrupted" | "denied";
};
```

## 4. Action Schema

The frontend can only execute actions from the allowed registry.

```ts
type DemoAction =
  | { type: "OPEN_DASHBOARD"; payload?: {} }
  | { type: "OPEN_ISSUES"; payload?: {} }
  | { type: "OPEN_PROJECTS"; payload?: {} }
  | { type: "OPEN_CYCLES"; payload?: {} }
  | { type: "OPEN_TEAMS"; payload?: {} }
  | { type: "OPEN_INTEGRATIONS"; payload?: {} }
  | { type: "OPEN_DEMO_ISSUE"; payload: { issue_id: string } }
  | { type: "HIGHLIGHT_ASSIGNMENT_CONTROL"; payload: { issue_id?: string } }
  | { type: "HIGHLIGHT_CYCLE_PROGRESS"; payload?: {} };
```

Simple example:

```ts
executeAction({ type: "OPEN_CYCLES" });
```

sets the active product page to `cycles`.

## 5. API Contracts

### Create Or Continue Turn

```http
POST /api/turn
```

Request:

```json
{
  "session_id": "session_123",
  "turn_id": 7,
  "product_id": "linear_simplified",
  "message": "We use Jira and sprint planning is messy.",
  "input_mode": "text"
}
```

Response:

```json
{
  "session_id": "session_123",
  "turn_id": 7,
  "status": "completed",
  "speech": "Cycles help teams plan work in time-boxed periods. I'll show you the current cycle.",
  "action": {
    "type": "OPEN_CYCLES",
    "payload": {}
  },
  "intent_trace": {
    "role": "Engineering Manager",
    "current_tool": "Jira",
    "goal": "Sprint planning",
    "pain_point": "Workflow complexity",
    "relevant_feature": "Cycles",
    "reason": "Showing Cycles because the visitor asked about sprint planning.",
    "confidence": 0.88,
    "status": "active"
  },
  "signals": [
    {
      "type": "feature_interest",
      "value": "cycles",
      "confidence": 0.91
    }
  ]
}
```

### Cancel Turn

```http
POST /api/turn/{turn_id}/cancel
```

Request:

```json
{
  "session_id": "session_123"
}
```

Response:

```json
{
  "session_id": "session_123",
  "turn_id": 7,
  "status": "cancelled"
}
```

## 6. Backend Modules

```text
app/main.py
  FastAPI app and routes

app/schemas.py
  Pydantic request/response models

app/db.py
  SQLite connection and migrations

app/services/session_manager.py
  Creates sessions, stores active_turn_id, cancels turns

app/services/retriever.py
  Reads product docs and returns relevant snippets

app/services/intent_extractor.py
  Extracts UI-safe intent_trace and private signals

app/services/action_planner.py
  Maps intent to proposed action

app/services/action_validator.py
  Validates proposed action against product action registry

app/services/agent.py
  Coordinates retrieval, intent extraction, planning, and response generation
```

## 7. SQLite Tables

```sql
sessions(
  id text primary key,
  product_id text not null,
  active_turn_id integer,
  started_at text not null,
  ended_at text
);

messages(
  id text primary key,
  session_id text not null,
  turn_id integer not null,
  role text not null,
  content text not null,
  created_at text not null
);

visitor_context(
  session_id text primary key,
  role text,
  team_size integer,
  current_tool text,
  goals text,
  pain_points text,
  features_interested_in text
);

signals(
  id text primary key,
  session_id text not null,
  turn_id integer not null,
  type text not null,
  value text not null,
  confidence real not null,
  created_at text not null
);

ui_events(
  id text primary key,
  session_id text not null,
  turn_id integer not null,
  action_type text not null,
  status text not null,
  created_at text not null
);
```

For MVP, array-like fields can be stored as JSON strings in SQLite.

## 8. First Build Checklist

1. Create frontend app shell.
2. Create product pages with static data.
3. Create right-side Intent Trace and chat panel.
4. Add frontend action executor.
5. Create FastAPI backend.
6. Add SQLite session/message tables.
7. Add `/api/turn`.
8. Add `/api/turn/{turn_id}/cancel`.
9. Add action validator.
10. Connect text chat end-to-end.
11. Add keyword product retrieval.
12. Add basic voice input/output.
13. Add interruption behavior.

## 9. First Demo Test

Script:

```text
User:
"We're using Jira. I'm an engineering manager and sprint planning is messy."

Expected:
UI opens Cycles.
Intent Trace shows Jira, Engineering Manager, Sprint Planning, Cycles.

User:
"Actually, I care more about bug tracking."

Expected:
Previous turn is cancelled.
UI opens Issues.
Intent Trace changes to Bug Tracking and Issues.

User:
"Open Salesforce."

Expected:
No product action executes.
Intent Trace status is denied.
Agent explains that it can only demo this product.
```

