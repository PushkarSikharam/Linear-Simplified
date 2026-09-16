# Milestone 2: Provider Control, Accounting and CI

Status date: 2026-09-16. Milestone 2 is **not signed off**.
- CI is green on GitHub for pushes to `main`: run 35126923767 (commit `73cd03d`, the CI fix) and run 35128102003 (commit `4a1fd69`, this evidence plus the harness fix).
- Paid before/after measurement: formally waived (see Measurement decision).
- Still needed: a green pull-request workflow run.

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
| 7 | CI added | Done |
| 8 | Fake-provider CI guard | Done. Passed on GitHub Actions run 35126923767 (commit `73cd03d`). |
| 9 | Concurrency, restart, reset and accounting-failure tests | Done. Passed on GitHub Actions run 35126923767. |
| 10 | Before/after measurement | **Waived** for development because the project has no budget for provider spend. Dry-run and fake-provider evidence is accepted for Milestone 2. One partial paid run happened before the waiver (see Measurement decision). Production cost benchmarking is future work before commercial launch. |
| 11 | Green GitHub pull-request workflow | **Open. The only remaining blocker.** All Milestone 2 code reached `main` by direct pushes, and the latest push run (35128102003 on `4a1fd69`) is green on all three jobs. A pull-request run is still required. This evidence update is the pull request's diff; no placeholder changes were made. |

## Local verification

| Check | Result |
| --- | --- |
| API suite | 146 passed; the 3 CI-only guard tests skip locally and pass with CI settings |
| Linux rehearsal (Python 3.14 + Node 24 container, CI environment, no developer env files) | API 146 passed (guard tests included); type check, 21 unit tests and production build passed; 51 browser tests passed |
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

### First GitHub run (commit `531e460`, push to `main`)

- **API tests and Web checks:** passed on Linux.
- **Browser tests:** failed in one test, `milestone 2 speech is only requested after the visitor turns voice on`.
  - **Symptom:** the test expected 429 `providers_disabled` and received 503 `no_provider_available`.
  - **Cause:** CI has no provider keys, so the speech service found no providers before it checked the kill switch. Locally the test passed only because the e2e API read developer `.env` files.
  - **Fixes:**
    - The kill switch is now checked first.
    - A new setting, `PIXEL_IGNORE_ENV_FILES=true`, stops the API from reading developer `.env` files. The e2e API and CI both set it, so local runs behave like CI.
    - Regression tests cover both fixes.
  - **Readable failures:** in CI, Playwright also reports failures as public GitHub annotations.
  - **Action versions:** workflow actions were updated to their Node 24 releases.
- **Verification:** the Linux rehearsal above reproduced the failure before the fix and passes after it.

## Measurement decision

**The paid before/after measurement is waived for Milestone 2.** The project currently has no budget for provider spend. Milestone 2 has to answer two separate questions:
- *Can we prove provider-control safety?* Yes, with fake providers, dry runs and CI.
- *Can we prove real-world provider cost?* Not yet; that needs paid traffic.

The second question isn't needed to prove the architecture, so production cost benchmarking remains future work before commercial launch.

The dry run above proves that page load makes no provider requests, that speech is refused before dispatch when providers are off, and that both the browser and server ceilings hold. **It does not measure real provider cost.**

### Paid run made before the waiver

The stakeholder briefly authorized a bounded paid measurement (20-attempt ceiling), then withdrew that authorization. One "after" run on this code completed before the withdrawal; the "before" run was never started.

| Item | Result |
| --- | --- |
| Configured providers | Azure Speech (`en-US-Ava:DragonHDLatestNeural`) and Gemini; no OpenAI |
| Page load | 0 provider requests |
| Conversation | 5 turns; 5 speech requests and 3 turn requests reached the API; browser worst-case charge 13 of 20 |
| Server ledger (final) | 5 Azure speech attempts, 738 characters reserved, all still `reserved` |
| Reasoning | No Gemini attempts: none of the 3 turns needed the model |
| Provider-reported usage | None: the outcomes were never recorded |

- **Why the Azure attempts never settled:** the harness sent each prompt before the previous reply's audio returned, and stopped the API about a second after the last turn, while all five Azure requests were still in flight.
- **Cost treatment:** by design, these five attempts stay counted as spent. The worst-case exposure is therefore 738 characters of Azure neural speech, at the HD voice's per-character price. That is an estimate, not a billed figure. It has not been reconciled against the Azure bill.
- **Harness fix (made after this run):** the harness now waits for each spoken reply before the next prompt, and waits up to 25 seconds for the ledger to settle before taking its snapshot. The fix was verified with a dry run only.

## Measurement procedure (for a future funded benchmark)

`npm run measure:usage` covers one page load plus five conversation turns, with voice turned on for replies.
- **Ceiling:** a browser-side safeguard charges each request its worst-case attempts before forwarding it, and blocks realtime entirely. When the harness starts the API itself, `PIXEL_TOTAL_ATTEMPT_CAP` enforces the same ceiling on the server.
- **Report:** written to `test-results/measurements/`.
- **Guardrail:** do not set `MEASURE_PAID=true` without an explicit, budgeted authorization.
- **Before-run (commit `c3a6f41`):** run that commit separately, then use `MEASURE_BASE_URL=<its web URL>` with `MEASURE_SPEECH_ATTEMPTS` equal to the number of configured speech providers. That build has no server ledger, so only the browser-side safeguard applies.
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

**Start condition:** Milestone 3 starts only after this milestone has green pull-request CI evidence. The measurement decision is resolved: waived.

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
