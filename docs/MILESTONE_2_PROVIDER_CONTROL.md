# Milestone 2: Provider Control, Accounting and CI

Status date: 2026-09-16. Milestone 2 is **not signed off**. Its remaining blockers need a
green GitHub pull-request run and an authorized paid measurement.

## What is enforced

- **The API owns every paid provider.**
  - Speech: `POST /api/speech`, with Azure, then Gemini, then OpenAI as fallbacks.
  - Reasoning: Gemini.
  - The web app holds no provider code, credentials or server API routes. `lib/provider-boundary.test.ts` fails if any appear.
  - All outbound provider traffic goes through `app/services/http_client.py`.
- **Reserve before dispatch.** Every attempt, fallbacks included, reserves allowance in the ledger before any request is sent. When policy refuses the attempt, or accounting is unavailable, nothing is sent.
  - A dispatched attempt stays counted after an error, timeout or cancellation.
  - `release` returns allowance only for attempts that were never sent.
- **Tenant-owned accounting.** `provider_attempts` records, per attempt:
  - owner: `tenant_id`, `product_id`, `deployment_id`, `user_id`, `session_id`
  - request: `request_id`, `attempt_id`, `capability`, `provider`, `model`
  - usage: `unit`, `reserved_units`, `actual_units` (plus the input/output split), `status`, timings
  - Every budget query, settle, release and summary is scoped by tenant, product and deployment.
  - Ownership comes from deployment configuration (`PIXEL_TENANT_ID`, `PIXEL_PRODUCT_ID`, `PIXEL_DEPLOYMENT_ID`). Login tokens are bound to that tenant.
- **Atomic, persistent budgets.** Reservations run inside `begin immediate` transactions, so they survive restarts, new sessions and demo resets.
  - Consumption counts the larger of the reserved estimate and the provider-reported usage.
  - Blocked attempts are recorded, but reserve nothing.
- **Policy** (`app/services/provider_policy.py`). Every lookup takes the tenant context.

  | Capability | Per user / day | Per deployment / day | Per session | Units |
  | --- | ---: | ---: | ---: | --- |
  | Speech | 100 attempts, 25,000 characters | 500 attempts, 125,000 characters | none | at most 2,000 characters per attempt |
  | Reasoning | 50 attempts | 250 attempts | 25 attempts | at most 4,000 input + 512 output tokens per attempt |
  | Realtime | 0 | 0 | 0 | disabled |

  Further limits apply across all capabilities:
  - at most two provider attempts per request
  - an optional total ceiling for the whole run (`PIXEL_TOTAL_ATTEMPT_CAP`)
  - a kill switch (`PIXEL_PAID_PROVIDERS_ENABLED`)
  - quotas reset at 00:00 UTC
- **Reasoning limits.** Gemini receives `maxOutputTokens: 512`.
  - The prompt keeps instructions, scope rules, allowed actions and the visitor's request.
  - Optional context is trimmed in this order: visible issues, team, projects, then documents.
  - A request that still doesn't fit is neither reserved nor sent.
  - The input estimate is conservative (one token per three bytes). A provider-reported count above the limit is logged as `reasoning_input_limit_exceeded`.
- **Legacy counter removed.** The in-memory per-session counter is gone; the persistent session limit replaces it.
- **No unrequested speech.**
  - Removed: prewarming and the automatic spoken greeting.
  - Changed: replies are spoken only after the visitor turns voice on.
- **Realtime is blocked.** The realtime session route and the browser's WebRTC client are removed, and the realtime policy is zero.
- **Metadata-only logging.**
  - The ledger and logs never contain prompts, spoken text, audio, credentials or provider error bodies. Tests assert this.
  - Rows are kept for 90 days (`PIXEL_USAGE_RETENTION_DAYS`).
  - The usage summary is admin-only and tenant-scoped.
- **CI** (`.github/workflows/ci.yml`) runs on every pull request and every push to `main`:
  - API tests
  - type check
  - unit tests
  - production build
  - browser tests

  Paid providers are off, external HTTP is blocked, and no credentials are present. `tests/test_ci_guard.py` asserts all three in CI.
  - Python dependencies are pinned in `apps/api/requirements.lock`.
  - Scripts run on Windows and Linux (`scripts/python.mjs`).

## Sign-off blockers

| # | Blocker | Status |
| --- | --- | --- |
| 1 | FastAPI owns provider execution | Done |
| 2 | Tenant, product and deployment ownership in accounting | Done |
| 3 | Gemini input and output limits | Done. The input ceiling relies on a conservative estimate, not a provider count. |
| 4 | Legacy in-memory counter removed | Done |
| 5 | Unrequested speech and prewarming removed | Done |
| 6 | Realtime blocked | Done |
| 7 | CI added | Done (workflow committed) |
| 8 | Fake-provider CI guard | Done locally. Needs its first GitHub run. |
| 9 | Concurrency, restart, reset and accounting-failure tests | Passing locally. Needs its first GitHub run. |
| 10 | Before/after measurement | **Open.** Dry run done; paid runs not authorized. |
| 11 | Green GitHub pull-request workflow | **Open.** Needs a push and a pull request. |

## Local verification

| Check | Result |
| --- | --- |
| API suite | 142 passed; the 3 CI-only guard tests skip locally and pass with CI settings |
| Web type check | Passed |
| Web unit tests | 21 passed |
| Production build (isolated build folder) | Passed |
| Chromium browser run | 51 passed; no escaped or external requests |
| Measurement dry run (providers off) | 0 provider requests on page load; 5 speech requests across 5 turns, all refused on the server before dispatch; browser ceiling charged 13 of 20 worst-case attempts (worked through below); 0 attempts actually dispatched |

### How the dry run's 13 is calculated

The number 13 is the browser-side ceiling's **worst-case charge**. It is not a count of provider calls.
- **The rule:** before forwarding a request, the harness charges the most provider attempts that request could cause:
  - each speech request: 2 (the API's two-attempts-per-request limit)
  - each chat-turn request: 1 (a turn makes at most one Gemini call)
- **Recorded requests:**

| Request type | Forwarded | Worst-case charge each | Charged |
| --- | ---: | ---: | ---: |
| Page load (any type) | 0 | — | 0 |
| Speech (`/api/agent/speech`), one per spoken reply | 5 | 2 | 10 |
| Chat turn (`/api/agent/turn`) | 3 | 1 | 3 |
| Realtime | 0 | blocked | 0 |
| **Total** | | | **13** |

- **Why 3 turn requests for 5 turns:** two of the five prompts were answered in the browser and never reached the API. That is the browser-side routing recorded under GAP-06.
- **What actually happened:**
  - None of the three turn requests needed the model, so the ledger has no reasoning rows.
  - All five speech requests were refused before dispatch (`providers_disabled`), and the ledger shows exactly five `blocked` speech rows.
  - Actual provider attempts dispatched: **0**.
- **In a paid run**, the charge stays an upper bound. The authoritative figures are the server ledger's rows; the report includes them under `serverLedger`.

## Measurement procedure

`npm run measure:usage` covers one page load plus five conversation turns, with voice turned on for replies.
- **Ceiling:** a browser-side safeguard charges each request its worst-case attempts before forwarding it, and blocks realtime entirely. When the harness starts the API itself, `PIXEL_TOTAL_ATTEMPT_CAP` enforces the same ceiling on the server.
- **Report:** written to `test-results/measurements/`.

**Paid runs require explicit authorization.** Only then set `MEASURE_PAID=true`, in a shell that has the provider keys.

- **After (this code):** `MEASURE_PAID=true npm run measure:usage`
- **Before (commit `c3a6f41`):**
  1. Check out that commit separately and start its API and web app.
  2. From this checkout, run with `MEASURE_BASE_URL=<its web URL>` and `MEASURE_SPEECH_ATTEMPTS=3`. The old build tried up to three providers per request.

  That build has no server ledger, so only the browser-side safeguard applies; run it with a fresh browser profile and no other clients. An incomplete run that stops at the ceiling is acceptable; exceeding the ceiling is not.

## Local development changes

- The API needs `PIXEL_SYNTHETIC_DEMO=true` before the demo can sign in.
- Provider keys belong only in the API's environment. The API still also reads `apps/web/.env.local`, as a legacy convenience; move the keys to a root `.env`.
- Replies are silent until "Voice On" is selected.

## Known debt (carried forward, not Milestone 2)

- Provider credentials, voices and budgets are deployment-wide settings, not tenant-configurable. `configured_speech_providers(tenant)` and `capability_policy(tenant, ...)` are the seams for per-tenant configuration.
- The API still reads `apps/web/.env.local`. Configuration should move to API-only files.
- `conversation_owners.customer_id` and `login_sessions.customer_id` hold tenant IDs under the old column name.
- Speech has no session limit. Its attempts are attributed to a session only when the session belongs to the caller.
- The voice labels ("Start Microsoft Voice", and a "Microsoft Voice" badge before any audio plays) overstate the provider (GAP-08).
- Core code still contains demo-specific reasoning hints and planners. These move to the Product Profile layer in Milestone 3.

## Milestone 3 boundary

**Start condition:** Milestone 3 starts only after this milestone has green pull-request CI evidence and a resolved measurement decision.

**Goal:** convert the Linear-specific core into a product-configurable architecture, without weakening Milestone 2's tenant boundaries. The work covers:
- `ProductProfile`
- tenant-owned product configuration
- terminology, knowledge, action registry and UI adapters, each per product
- a second, non-Linear product as proof

**Not approved before that abstraction exists:**
- billing
- enterprise deployment
- UI polish
- additional providers
- broad onboarding automation
