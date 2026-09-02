# AI Voice-First Adaptive Product Demo Agent

## 1. Product Goal

Build a working prototype of an AI product demo agent that can talk with a visitor, understand what they care about, and adapt a controlled product UI in real time.

The core demo loop is:

```text
User speaks or types
  -> agent extracts intent
  -> agent retrieves product knowledge
  -> agent chooses an allowed UI action
  -> backend validates the action
  -> frontend updates the demo UI
  -> Intent Trace explains why the UI changed
```

Simple example:

```text
User:
"We use Jira and sprint planning is messy."

System extracts:
- Current tool: Jira
- Goal: Sprint planning
- Pain point: workflow complexity
- Relevant feature: Cycles

System action:
OPEN_CYCLES

Intent Trace:
"Showing Cycles because the visitor asked about sprint planning."
```

## 2. MVP Scope

The MVP should prove the main technical claim:

> A voice/text AI agent can understand visitor intent, stay inside a product boundary, and control a demo UI through validated actions.

### Must Have

- Linear-like demo product UI
- Text chat
- Voice input and spoken response
- Session state
- Structured intent extraction
- Product-scoped knowledge retrieval
- Controlled UI actions
- Backend action validation
- Turn IDs for synchronization
- Interruption/cancellation behavior
- Intent Trace panel
- Session transcript
- Basic session summary

### Defer

- Real CRM integrations
- Real Linear/Jira browser automation
- Multi-product marketplace
- Enterprise auth
- Billing
- Kubernetes
- Large analytics platform
- Full voice provider benchmarking
- Confusion Map across many sessions

## 3. High-Level Architecture

```text
Browser
  - Demo product UI
  - Chat/voice controls
  - Intent Trace panel
  - Session transcript
  - Speech playback

Backend API
  - Session manager
  - Product guard
  - RAG retriever
  - Agent planner
  - Action validator
  - Turn/cancellation manager
  - Signal extractor

Storage
  - Product docs
  - Demo product data
  - Sessions
  - Messages
  - Visitor context
  - Signals
  - UI events
```

## 4. Recommended Tech Stack

### Frontend

- Next.js
- React
- TypeScript
- Tailwind CSS

Why:

- Fast to build
- Good for a polished demo UI
- Easy state management
- Good browser support for voice APIs

### Backend

- FastAPI
- Python
- Pydantic schemas

Why:

- Fast API development
- Strong typing with Pydantic
- Good ecosystem for AI/RAG work

### AI

- LLM with structured output support
- Product knowledge retrieval
- Deterministic fallback rules for key demo intents

Why:

- Structured outputs reduce hallucinated actions
- Fallback rules make the demo reliable

### Storage

For MVP:

- SQLite for runtime session state
- Markdown files for product documentation

Later:

- PostgreSQL
- pgvector

Why:

- SQLite gives us transactional session state without operational complexity
- Markdown keeps product docs easy to read and edit
- Postgres/pgvector can be added after the architecture works

## 5. Core Components

## 5.1 Demo Product UI

The demo product is a controlled Linear-like project management app.

Pages:

- Dashboard
- Issues
- Projects
- Cycles
- Teams
- Integrations

Important idea:

The AI does not control the browser freely. It only asks the app to perform known actions.

Example allowed actions:

```text
OPEN_DASHBOARD
OPEN_ISSUES
OPEN_PROJECTS
OPEN_CYCLES
OPEN_TEAMS
OPEN_INTEGRATIONS
OPEN_DEMO_ISSUE
HIGHLIGHT_ASSIGNMENT_CONTROL
HIGHLIGHT_CYCLE_PROGRESS
```

## 5.2 Agent API

Main endpoint:

```http
POST /api/turn
```

Input:

```json
{
  "session_id": "session_123",
  "turn_id": 7,
  "product_id": "linear_simplified",
  "message": "We use Jira and sprint planning is messy.",
  "input_mode": "voice"
}
```

Output:

```json
{
  "turn_id": 7,
  "status": "completed",
  "speech": "Cycles help teams plan time-boxed work. I'll show you the current cycle.",
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
    "confidence": 0.88
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

## 5.3 Product Guard

The Product Guard prevents the assistant from leaving the configured product domain.

Examples:

```text
Allowed:
"Show me sprint planning."

Denied:
"Open Salesforce."
"Browse my Gmail."
"Delete all issues."
```

Implementation:

1. Give the agent only product-specific instructions, docs, and allowed actions.
2. Retrieve only documents for the active `product_id`.
3. Allow only actions registered for the active `product_id`.
4. Validate the action before sending it to the frontend.
5. Add explicit semantic out-of-domain classification only if the simple boundary is not enough.

Simple example:

```text
If active product is Linear Simplified:
OPEN_CYCLES is allowed.
OPEN_SALESFORCE is not allowed.
```

## 5.4 RAG Knowledge Layer

For MVP, use a small local knowledge base:

```text
docs/
  cycles.md
  issues.md
  projects.md
  integrations.md
```

Each document belongs to one product:

```json
{
  "product_id": "linear_simplified",
  "title": "Cycles",
  "content": "Cycles organize work into time-boxed planning periods..."
}
```

MVP retrieval can start simple:

- keyword search
- feature mapping
- small top-k document selection

Later upgrade:

- embeddings
- pgvector
- semantic ranking

## 5.5 Intent Extractor

The Intent Extractor converts natural language into safe structured fields.

Fields:

```json
{
  "role": null,
  "team_size": null,
  "current_tool": null,
  "goals": [],
  "pain_points": [],
  "features_interested_in": [],
  "current_intent": null,
  "buying_signal": null
}
```

Simple example:

```text
User:
"I'm an engineering manager with 15 devs."

Extracted:
role = Engineering Manager
team_size = 15
```

## 5.6 Action Planner

The Action Planner chooses the best allowed product action.

Example rules:

```text
If intent contains sprint planning:
  action = OPEN_CYCLES

If intent contains bug tracking:
  action = OPEN_ISSUES

If intent contains GitHub or Slack:
  action = OPEN_INTEGRATIONS
```

The LLM can help produce the action, but the backend validator has final authority.

## 5.7 Action Validator

The Action Validator checks:

- Is the action known?
- Is it allowed for this product?
- Is the payload schema valid?
- Is the action safe?
- Does the turn still match the active turn?

Example:

```text
LLM proposes:
OPEN_SALESFORCE

Validator:
Rejected, because Salesforce is not an allowed action for this product.
```

## 5.8 Turn Manager

Every user request gets a `turn_id`.

The frontend and backend keep track of the latest active turn through an explicit `active_turn_id` contract.

Cancellation endpoint:

```http
POST /api/turn/{turn_id}/cancel
```

Rule:

```text
Only apply responses, audio, and UI actions from the latest active turn.
```

Backend rule:

```python
if turn_id != session.active_turn_id:
    discard_result()
```

Example:

```text
Turn 7:
User asks about sprint planning.
Agent starts opening Cycles.

Turn 8:
User interrupts and asks about bugs.

Result:
Turn 7 is cancelled.
Any late Turn 7 UI action is ignored.
Turn 8 opens Issues.
```

## 5.9 Voice State Machine

Frontend voice states:

```text
IDLE
LISTENING
THINKING
SPEAKING
INTERRUPTED
EXECUTING_ACTION
```

Basic flow:

```text
LISTENING
  -> user finishes turn
THINKING
  -> backend response arrives
SPEAKING
  -> agent audio starts
EXECUTING_ACTION
  -> UI action runs
LISTENING
  -> ready for next turn
```

Interruption flow:

```text
SPEAKING
  -> user starts meaningful interruption
INTERRUPTED
  -> stop audio
  -> cancel active turn
LISTENING
  -> collect new request
```

For MVP, backchannel detection can be simple:

```text
"yeah", "right", "mm-hmm", "okay"
```

These should not always cancel the agent.

## 5.10 Intent Trace Panel

Intent Trace is the signature visible feature.

It should show:

- Role
- Team size
- Current tool
- Goal
- Pain point
- Current intent
- Relevant feature
- Why this feature
- Confidence
- Interruption status

It must not show chain-of-thought.

Example:

```text
Intent Trace

Role: Engineering Manager
Current Tool: Jira
Goal: Sprint Planning
Pain Point: Workflow Complexity
Relevant Feature: Cycles
Why: Visitor asked about sprint planning.
Confidence: 88%
```

## 5.11 Session Summary

At the end of the demo:

```text
Visitor Persona: Engineering Manager
Current Tool: Jira
Primary Goal: Sprint planning
Features Explored: Cycles, Issues
Pain Point: Jira complexity
Objection: Migration effort
Suggested Follow-Up: Jira migration workflow
```

This turns the demo into useful sales/product intelligence.

## 6. Implementation Plan

## Phase 1: Product Skeleton

Build the controlled demo UI.

Deliverables:

- Next.js app
- Layout with product sidebar
- Pages for Dashboard, Issues, Projects, Cycles, Teams, Integrations
- Static demo data
- Intent Trace panel
- Chat panel

Why:

We need a visible product surface before the AI can demonstrate anything.

Simple example:

```text
Clicking "Cycles" manually should open the Cycles screen before the agent can open it.
```

## Phase 2: Controlled Actions

Add frontend action execution.

Deliverables:

- Action registry
- `executeAction(action)` function
- Navigation actions
- Highlight actions
- UI event logging

Why:

The agent should control the UI only through a safe contract.

Simple example:

```text
executeAction({ type: "OPEN_CYCLES" })
```

changes the active page to Cycles.

## Phase 3: Backend Agent API

Build FastAPI service.

Deliverables:

- `POST /api/turn`
- Pydantic request/response schemas
- Session store
- Turn manager
- Action validator
- Simple intent extractor
- Simple action planner

Why:

This creates the full text-based demo loop before voice adds complexity.

## Phase 4: Text Chat End-to-End

Connect frontend chat to backend.

Deliverables:

- User can send text
- Backend returns response/action/intent
- Frontend updates transcript
- Frontend executes validated action
- Intent Trace updates

Why:

If text mode works, voice becomes another input/output layer instead of the whole problem.

## Phase 5: Product Knowledge Retrieval

Add product docs and retrieval.

Deliverables:

- Local product docs
- Product-scoped retrieval
- Retrieved context included in agent response
- Out-of-domain rejection path

Why:

The assistant should answer from approved product knowledge, not generic guesses.

## Phase 6: Voice Input and Output

Add voice interaction.

Deliverables:

- Microphone input
- Speech-to-text
- Text-to-speech
- Voice state machine
- Stop/cancel audio behavior

Why:

Voice is core to the assignment, but it is safer to add after the agent loop works in text.

## Phase 7: Interruption and Turn Cancellation

Implement the signature demo moment.

Deliverables:

- Active turn tracking
- Cancel current speech on interruption
- Ignore stale backend responses
- Ignore stale UI actions
- Intent Trace shows interrupted intent and new intent

Why:

This proves voice/UI synchronization, which is one of the hardest parts of the project.

## Phase 8: Session Intelligence

Add end-of-session summary.

Deliverables:

- Features explored
- Goals
- Pain points
- Objections
- Suggested follow-up

Why:

This shows how conversation can become structured business intelligence.

## Phase 9: Evaluation Scripts

Create scripted test scenarios.

Scenarios:

- Sprint planning request opens Cycles
- Bug tracking request opens Issues
- Interruption cancels old action
- Salesforce request is denied
- Backchannel does not cancel speech
- Assignment question opens an issue and highlights assignee control

Why:

This makes the prototype defensible, not just flashy.

## 7. Build Order

Recommended order:

```text
1. Frontend demo UI
2. Frontend action registry
3. Backend schemas and /api/turn
4. Text chat loop
5. Action validator / product boundary
6. Intent Trace
7. Product docs and retrieval
8. Voice input/output
9. Interruption handling
10. Session summary
```

## 8. Main Engineering Risks

## Risk 1: Voice interruption is unreliable

Mitigation:

- Build text mode first
- Implement explicit cancel button
- Use turn IDs everywhere
- Add voice interruption after action cancellation works

## Risk 2: LLM returns unsafe or invalid action

Mitigation:

- Structured output schema
- Server-side validation
- Allowed action registry
- Product guard

## Risk 3: Demo feels generic

Mitigation:

- Intent Trace must update visibly
- UI must navigate immediately
- Responses must mention the user's context

## Risk 4: RAG takes too long to implement

Mitigation:

- Start with local docs and keyword retrieval
- Upgrade to embeddings only after end-to-end loop works

## 9. Demo Script

### Step 1

User:

```text
We're using Jira right now. I'm an engineering manager and I want to understand how sprint planning works.
```

Expected:

- Intent Trace shows Engineering Manager, Jira, Sprint Planning
- UI opens Cycles
- Agent explains Cycles

### Step 2

User interrupts:

```text
Actually stop. I'm more interested in bug tracking.
```

Expected:

- Current speech stops
- Previous turn is cancelled
- Intent Trace shows interruption
- UI opens Issues

### Step 3

User:

```text
Can you open Salesforce and show me opportunities?
```

Expected:

- Domain Guard denies request
- No UI action executes
- Agent stays inside product domain

### Step 4

User:

```text
How do I assign a bug to one developer?
```

Expected:

- Retrieval finds issue assignment docs
- UI opens a demo issue
- Assignment control is highlighted
- Agent explains assignment workflow

## 10. Success Criteria

The prototype is successful if:

- A visitor can use text or voice to ask product questions
- The agent answers within the product domain
- The product UI changes based on intent
- Intent Trace explains the adaptation
- Invalid product actions are blocked
- Interrupted turns do not execute stale actions
- The session summary captures useful visitor signals

## 11. Positioning

Short pitch:

> This is a voice-first adaptive product demo agent. Unlike a chatbot, it understands visitor intent, retrieves product knowledge, triggers validated UI actions, and exposes an Intent Trace panel that shows why the demo is adapting.

One-line technical pitch:

> Realtime voice plus product-scoped RAG plus structured agent actions plus turn-synchronized UI control.
