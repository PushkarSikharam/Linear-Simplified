# Implementation Plan: Team Member Creation & Live Demo Link Deployment

## Overview
This plan addresses two goals:
1. **Team Member Creation & Chatbot Directory Validation** — Adding `+ Add Member` in Teams View, stateful team directory, and chatbot detection when creating tickets for non-employees (e.g. `Lucifer`).
2. **Live Demo Link for Internship Evaluator** — Configuring Next.js API rewrites so frontend and backend work as a single unified app, and generating a shareable public URL via tunneling (`localtunnel` / `cloudflared` / `ngrok`).

---

## User Review Required

> [!IMPORTANT]
> **Key Architecture Decisions:**
> 
> 1. **Next.js Backend Proxy (Single-Port Access):**
>    - Configure `next.config.ts` rewrites to proxy `/api/agent/*` → `http://127.0.0.1:8001/api/*`.
>    - Update `agent-api.ts` to use relative endpoints by default (`/api/agent/turn`).
>    - **Benefit:** When sharing a live link, external users only connect to port 3000 — no separate API host needed and no `127.0.0.1` browser cross-origin failures.
> 
> 2. **Teams View `+ Add Member` Form:**
>    - Lift `demoTeam` array into dynamic `[team, setTeam]` state in `page.tsx`.
>    - Add `TeamMemberCreatePanel` modal (*Name, Role, Load %, Initials, Email*).
>    - Automatically include new team members in ticket Assignee dropdowns.
> 
> 3. **Chatbot Employee Directory Validation:**
>    - When a user asks Edith to create a ticket for an unlisted person (e.g., `Lucifer`), Edith responds:
>      *"Lucifer is not in your team directory yet. I'll open Teams so you can add Lucifer to the workspace. I've also created PIX-151 for Lucifer."*
>    - Edith automatically navigates to Teams with `+ Add Member` highlighted and prefilled.

---

## Proposed Changes

### Component 1: Frontend Next.js Proxy & Team State

#### [MODIFY] [next.config.ts](file:///e:/Linear Simplified/apps/web/next.config.ts)
- Add `rewrites()` rule mapping `/api/agent/:path*` → `http://127.0.0.1:8001/api/:path*`.

#### [MODIFY] [agent-api.ts](file:///e:/Linear Simplified/apps/web/lib/agent-api.ts)
- Update default `API_BASE_URL` to use relative path `/api/agent` in browser context.

#### [MODIFY] [page.tsx](file:///e:/Linear Simplified/apps/web/app/page.tsx)
- Add stateful `team` array initialized with `demoTeam`.
- Implement `addTeamMember(member: DemoTeamMember)` function.
- Update `TeamsView` with header `+ Add Member` button and `TeamMemberCreatePanel`.
- Pass dynamic `team` state to `IssueCreatePanel` & `IssueDetailView`.

#### [MODIFY] [globals.css](file:///e:/Linear Simplified/apps/web/app/globals.css)
- Add CSS rules for `TeamMemberCreatePanel`, `add-member-button`, and form styling.

---

### Component 2: Backend Chatbot Intelligence

#### [MODIFY] [agent.py](file:///e:/Linear Simplified/apps/api/app/services/agent.py)
- Detect when requested assignee is not in standard employee list.
- Return speech informing user that assignee is unlisted and opening Teams with `add_member_button` target.

---

## Verification & Deployment Plan

### Automated Tests
- Test API rewrite `/api/agent/turn` through Next.js dev server.
- Test Python backend team validation.

### Live Demo Public Link Generation
- Launch `npx localtunnel --port 3000` (or `npx cloudflared tunnel`).
- Generate public https URL (e.g. `https://pixel-app.loca.lt`).
- Verify complete end-to-end functionality via public link.
