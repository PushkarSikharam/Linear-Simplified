# Milestone 3, Step 3.1: Product Definition Contract, Loader and SaaS Tenancy Model

Status: **reopened on 2026-09-16.** A post-sign-off review reproduced three isolation defects, so the earlier sign-off is not evidence that isolation works. Step 3.1a (below) fixes them; 3.1 is signed off again only after 3.1a has a green pull-request run and its final diff is reviewed. 3.2 does not start before then.
Date: 2026-09-16. Design reference: `docs/MILESTONE_3_PRODUCT_PROFILE_DESIGN.md` (revision 4, section 3A).

## Scope delivered

The work stayed inside the 3.1 scope: schema and contract, loader, validation, registry,
version and checksum handling, golden baseline, and the Linear demo as the first definition.
The revision-4 amendment added the canonical SaaS model inside the same step:
- **Hierarchy:** Organization → Team → Product → that product's Pixel.
- **Deployment:** one shared, multi-tenant deployment. Organization identity never comes from deployment identity.

Scope boundaries:
- **Not started:** record migration, web rebuilding and the billing product.
- **Not added (by decision):**
  - an RBAC engine, permission UI, SSO or IAM
  - billing or budget allocation
  - onboarding, a product creation wizard, team management UI or an organization dashboard
- **Behaviour:** the demo is unchanged. The backend and browser golden recordings match without re-recording.

| Area | Delivered | Where |
| --- | --- | --- |
| Capability vocabulary | Closed list of six capabilities (no delete); fixed platform views, response keys, placeholders, intent requirements and product settings; definition ownership, member roles and organization/team/product states | `apps/api/app/definitions/vocabulary.py` |
| Contract | Strict models that reject unknown fields and type coercion; whole-definition cross-reference checks (entities, fields, targets, people, scope paths of at most two hops, views, controls, actions, responses) | `definitions/contract.py` |
| Definition identity | `definition_id`, `version`, `ownership` (`platform_shared` or `organization_private`) and, for private definitions only, `owner_organization`. Definitions carry no organization, team or product binding. | `definitions/contract.py` |
| Untrusted-input safety | Allowlist rules: literal terms only; keys and slugs only; plain-text templates with fixed placeholders; no URLs, paths, selectors, markup or control characters | `definitions/safety.py` |
| Loader | Hardened YAML (safe loader, no aliases, no repeated keys, size limit); SHA-256 checksum; path, declared identity and registered checksum must agree; adapter views must exist in the package's adapter manifest | `definitions/loader.py` |
| Compatibility | Only additive-compatible or breaking-requires-migration; only entity changes can be breaking | `definitions/compatibility.py` |
| Registry | Global definition lifecycle stored in the database, with validated transitions; published content immutable; ownership permanent across versions; breaking publishes need a reviewed migration and expire older sessions | `definitions/registry.py`, `db.py` |
| Organizations and teams | `organizations` (active/suspended), `teams` (active/disabled) and `memberships` (org admin without a team; team admin and team member with exactly one team) | `definitions/organizations.py`, `db.py` |
| Product bindings | Keyed by organization and product. Each binding: <br>• is owned by one team and selects a published definition version the organization may use <br>• carries a knowledge version and checksum, a closed settings list, and visitor access <br>• has an active/disabled state, can move or roll back between versions, and can be transferred between teams | `definitions/organizations.py` |
| Product resolution | Every request names a product; the backend resolves it inside the principal's organization. <br>• Org admins may use any product of their organization. <br>• Team roles may use only their team's products. <br>• Visitors may use only the one product their session was issued for, and only if it accepts visitors. <br>Unknown, foreign and forbidden products all give the same denial. | `definitions/access.py` |
| Principals | Member tokens bound to one organization membership; visitor tokens bound to one organization and one product (`visitor_logins`). Suspended organizations are refused. | `auth.py` |
| Session pinning | Sessions store organization, team, product, definition ID, version and checksum, knowledge version and expiry. Each turn ends the session on: <br>• definition revocation or changed content <br>• suspended organization, disabled team or disabled product <br>• product transfer to another team <br>• age, or a missing pin <br>A session can never be continued as another product or by another organization. | `definitions/sessions.py`, `services/session_manager.py`, `services/agent.py` |
| Usage attribution | Every ledger row records the owning team at attempt time, so transfers never rewrite history. The admin usage summary is for organization admins only and covers only their organization, by team and product. | `services/usage_ledger.py`, `main.py` |
| Paid capabilities | Speech requires a product and is authorized, attributed and styled per product. Reasoning is reserved against the product context of the turn. | `main.py`, `services/speech_service.py`, `services/agent_reasoner.py` |
| API | `POST /api/organizations/{tenant_id}/products/{product_id}/visitor-sessions` (public, product-scoped). Demo login resolves the organization from membership. Product-data endpoints refuse visitors. | `main.py` |
| Development bootstrap | Product packages may ship `seed/demo_organization.json`; only when `PIXEL_DEMO_SEEDS=true` is set explicitly, migration creates that synthetic organization, team, members and product idempotently. A missing setting creates nothing (fail safe). | `definitions/bootstrap.py` |
| Linear definition v1 | Platform-shared. 4 entities, 7 views, 19 actions (every current action), 19 intents, clarifications, guardrails, 29 response templates, knowledge topics, prospect signals, reasoning hints. No organization data. | `products/linear_simplified/definition/v1.yaml` |
| Linear demo organization | `pixel-dev` → team `planning-team` → product `linear-demo` (definition `linear_simplified` v1, visitors allowed); `demo-admin` is org admin, the two other demo users are team members | `products/linear_simplified/seed/demo_organization.json` |
| Linear adapter manifest | Declares the one custom view (`integrations`) and its controls | `apps/web/adapters/linear_simplified/manifest.json` |
| Web | Uses the organization's product ID (`linear-demo`) for turns and speech | `apps/web/lib/product-config.ts`, `hybrid-voice-engine.ts`, `app/page.tsx` |
| Golden baseline | 55 conversations recorded from the backend engine and from the real browser (which component decided, view, reply, status, highlights, filter, open ticket) | `products/linear_simplified/tests/golden/` |
| Core purity check | New core code must be product-neutral; existing coupling is listed with the step that removes it, and the list may only shrink (`tenancy.py` left the list in this step) | `apps/api/tests/test_core_purity.py` |
| Test harness | Browser isolation harness shared by core and product specs; product tests run in `test:api` and `test:e2e` | `tests/e2e/harness.ts`, `package.json`, `playwright.config.ts` |

Naming: product and business language uses Organization, Team, Product and Pixel, while code
keeps `tenant_id` for the organization. The demo product's own records (its projects,
workspaces and "team members") are product data. They are never Pixel organizations or teams.

## Mandatory tests covered in 3.1

| Requirement | Test |
| --- | --- |
| 1. Version pinning | `SessionPinningTest.test_sessions_stay_on_their_version_after_a_new_one_is_published` |
| 2. Capability escalation | `DefinitionContractTest.test_unsupported_capabilities_are_rejected` |
| 3. Unsafe parameters | `test_targets_must_be_declared_keys`, `test_html_and_unknown_placeholders_are_rejected_in_templates`, `test_urls_and_paths_are_rejected_in_text`, `test_match_terms_are_literal_only`, `test_unknown_fields_are_rejected_everywhere` |
| 4. Breaking change | `CompatibilityTest.test_breaking_entity_changes_need_a_migration` (six kinds of breaking change) |
| 5. Revocation for every organization | `test_revoking_a_version_ends_its_sessions_for_every_organization`; API-level `LinearDemoOrganizationTest.test_revoking_the_version_ends_live_conversations` |
| 5b. Product-specific control | `test_disabling_one_organizations_product_leaves_others_running`, `test_rolling_back_one_product_does_not_affect_others` |
| 6. Lifecycle | `test_invalid_transitions_are_rejected`, `test_published_content_is_immutable`, `test_ownership_is_recorded_and_permanent` |
| Same organization, different teams | `ProductAccessTest.test_same_organization_different_teams`; turn path `TurnIsolationTest.test_same_organization_different_teams`; API `ApiAccessTest.test_member_turns_are_limited_to_their_team_products` |
| Same organization, different products | `ProductAccessTest.test_same_organization_different_products`, `TurnIsolationTest.test_same_organization_different_products` |
| Different organizations | `ProductAccessTest.test_different_organizations`, `TurnIsolationTest.test_different_organizations` (including a same-named product in another organization) |
| Private definition ownership | `DefinitionOwnershipTest.test_private_definitions_are_bindable_only_by_their_owner`, `test_sessions_refuse_a_private_definition_outside_its_owner`, `DefinitionContractTest.test_ownership_names_an_owner_only_for_private_definitions` |
| Platform-shared definition | `DefinitionOwnershipTest.test_platform_shared_definitions_serve_several_organizations_independently`; the Linear v1 identity test |
| Disabled product binding | `ProductAccessTest.test_disabled_products_end_their_sessions_only`, `TurnIsolationTest.test_disabled_products_end_live_sessions` |
| Visitor pinned to Product A | `ProductAccessTest.test_visitors_are_pinned_to_one_product`, `TurnIsolationTest.test_visitors_are_pinned_to_their_product`, `SpeechEndpointTest.test_speech_is_authorized_per_product` |
| Product A session switched to Product B | `TurnIsolationTest.test_same_organization_different_products`, `test_visitors_are_pinned_to_their_product` |
| Team attribution at attempt time | `UsageLedgerTest.test_team_attribution_is_recorded_at_attempt_time`, `UsageApiTest.test_summary_is_for_organization_admins_and_their_organization_only` |
| Demo seeds fail safe | `DemoSeedDefaultTest` (unset or `false` creates nothing; `true` creates the demo organization) |
| Organization identity independent of deployment | `OrganizationTest.test_organization_identity_does_not_come_from_the_deployment`, `UsageLedgerTest.test_organization_identity_is_independent_of_the_deployment` |
| Suspended organization, disabled team, transfer | `test_suspended_organizations_and_disabled_teams_stop_their_products`, `test_transferring_a_product_ends_sessions_pinned_to_the_old_team`, `ApiAccessTest.test_suspended_organizations_are_refused` |

Items 7–9 of the design's section 11 depend on later steps, and they are unchanged from Milestones 1 and 2 for now:
- full isolation across records and knowledge
- scope by ID
- the prompt boundary

## Verification

The full baseline was rerun after the revision-4 amendment and again after demo seeds were made fail safe.

| Check | Windows | Linux rehearsal (Python 3.14, Node 24, CI environment) |
| --- | --- | --- |
| Core API suite | 231 passed (3 CI-only skipped) | 231 passed (CI guards included) |
| Linear product API suite (incl. backend golden) | 11 passed | 11 passed |
| Type check | Passed | Passed |
| Web unit tests | 21 passed | 21 passed |
| Production build | — | Passed |
| Browser suites (core + Linear golden) | 107 passed | 107 passed |

One full Windows browser run had a single failure in the golden `architecture` case, and its error was not captured. It did not reproduce in a golden-only rerun (56 passed), a full Windows rerun (107 passed) or the Linux rehearsal (107 passed). If it recurs, it will be investigated as a flaky test, not ignored.

No paid provider was called: every run used `PIXEL_PAID_PROVIDERS_ENABLED=false`,
`PIXEL_BLOCK_EXTERNAL_HTTP=true` and `LLM_ENABLED=false`.

### GitHub CI

| Run | Trigger | API tests | Web checks | Browser tests |
| --- | --- | --- | --- | --- |
| [35144291014](https://github.com/PushkarSikharam/Linear-Simplified/actions/runs/35144291014) | push of `3221971` to `main` | Passed | Passed | Passed |

Process note: the 3.1 implementation was pushed to `main` directly instead of through a
branch and pull request. The push run above verifies the exact committed code.

**Sign-off decision (2026-09-16):** the stakeholder signed off 3.1 on the green push run and
explicitly waived the pull-request CI run for this step. This is a one-time exception.
Later steps still go through branch → pull request → green CI before sign-off.

## Findings that shape the next steps

1. **The browser decides most turns.** Of 61 recorded turns, **41 were decided entirely in the browser.**
   - They cover most ticket opening, updating and assignment, scope refusals, greetings, identity and capability answers, counts, next-step suggestions, the guided path and the architecture navigation.
   - This confirms 3.3 as the highest-risk step.
2. **The baseline records existing quirks as they are.** Each one needs an explicit decision (keep or fix, with justification) in the step that touches it:
   - The backend answers "assign it to Priya" (an unknown person) with "That work is outside the workspace", while the browser path offers to add her.
   - The browser's name detection answers "I'm an engineering manager…" as though the visitor had introduced themselves by that name.
3. **Some current replies contain organization data** ("open Maya's ticket, assign it to Noah" in the guided path). The definition deliberately uses generic wording, so reproducing these replies in 3.3 means an intentional, documented text change.
4. **Per-view replies need a design decision in 3.3.** The browser's next-step reply varies by current view; the definition currently has a single `next_step` response.
5. **Definition v1 intents are a faithful but approximate translation.** 3.2 reconciles them against the golden baseline and publishes the result as v2, a compatible change that touches no entities.
6. **Ended sessions need browser handling.** A session ended by revocation, a disabled or transferred product, a suspended organization or age is refused on every turn, but the browser keeps reusing its session ID until the page reloads. 3.3 must make the browser start a new session when the backend reports the conversation has ended.
7. **Visitors can speak but cannot chat through the API yet.** `/api/turn` still requires a demo-product workspace grant, which visitors never have, so visitor turns are proven at the agent level only. Until this is fixed, the visitor endpoint is a verified contract, not a usable visitor experience. The debt is split:
   - **3.3 (single backend conversation pipeline):** a visitor token must converse successfully through `/api/turn` using only its pinned product context.
   - **3.5 (records and scopes):** visitors get appropriately scoped access to generic product records.
8. **The web shell serves one product.** It sends a fixed product ID (`linear-demo`). Choosing among several products is 3.6 work. The backend already resolves any number of products per organization.
9. **The speech voice style still comes from the legacy product config**, looked up by the pinned definition ID (`main.py`, already on the purity allowlist). It moves to the definition in 3.2.
10. **Legacy column names.** `login_sessions.customer_id` and `conversation_owners.customer_id` hold the organization ID. Renaming them is a migration for 3.5; the code documents the meaning.
11. **No management API.** Organizations, teams, members and products are created by seed packages or by the directory service only, by decision. Production onboarding is a later milestone.
12. **Budgets are still per product** (organization, product and deployment). Team attribution is recorded for reporting only; no budget allocation exists, by decision.
13. **Deletion-test prerequisite.** `tests/e2e/demo-agent.spec.ts` is Linear-specific but lives in core tests; it must move into `products/linear_simplified/tests/` before the 3.8 deletion test.
14. **Demo seeds fail safe.** `PIXEL_DEMO_SEEDS` defaults to off. Local, demo and test environments (the browser harness, the measurement harness and the test fixtures) set it to `true` explicitly. Tested by `DemoSeedDefaultTest` (unset, `false` and `true`).

## Step 3.1a: isolation hardening

A review after the first sign-off reproduced these defects in temporary databases. Each now has
an exact regression test in `apps/api/tests/test_isolation_hardening.py`.

| Defect | Reproduction | Fix |
| --- | --- | --- |
| Legacy record permissions crossed organizations | `demo-admin`, added to another organization as an ordinary member, read and reset the demo records (both 200) | See "Record access" below |
| Definition ownership could change | A private v2 was published, then a platform-shared v1 of the same definition | Ownership is part of the definition identity (`definitions` table), fixed by the first registered version and checked inside the registration and publication transactions. Existing registrations are backfilled on migration. |
| Speech ignored the definition lifecycle | After revocation, `/api/speech` returned 200 and dispatched | See "Speech" below |
| Voice label claimed a provider | The badge and button said "Microsoft Voice" before any provider answered | A neutral "Voice" until the API reports the engine that produced audio; the button says "Start Voice" |

**Record access** (transitional, until records migrate in 3.5): `app/record_access.py`.
- The legacy tables belong to one designated product, declared by its seed package. Without a designation nobody can reach them.
- Record grants are scoped to organization, product and user; they are no longer part of the principal.
- Every legacy data endpoint requires:
  - an organization member (never a visitor) of the owning organization
  - who may use that product: an active organization, team and binding
  - and who holds a record grant for it.
- Reset and workspace-wide cycles need the grant's record administration flag.
- Chat turns check the grant of the requested product.

**Speech.** Every check runs before any reservation or dispatch.
- With a session: the session must belong to the caller and to this product, and be valid on its pinned definition. A retired version still serves its sessions; a revoked one does not.
- Without a session: the product's current definition must be startable.
- A supplied session that is unknown, foreign, unpinned, expired or ended is rejected, never silently treated as sessionless:
  - unknown, foreign or another product's session: 404
  - lifecycle refusals: 409, with a reason
- Tests assert zero provider dispatches **and** zero ledger rows for every refusal, plus positive cases for pinned, sessionless, retired-but-pinned and visitor speech.

**Tests before and after the fixes.**

| Suite | Before fixes | After fixes |
| --- | --- | --- |
| `test_isolation_hardening.py` (25 tests at the time) | 19 failed, 6 passed (the passing ones are positive or already-correct cases) | 25 passed |
| Added afterwards | — | no designated record owner; identity backfill on migration (27 in total) |
| Existing API suites | — | One test encoded the old behaviour (a foreign speech session was silently ignored); it now asserts rejection. |

**3.1a verification** (no paid providers; no measurement run was needed).

| Check | Windows | Linux rehearsal |
| --- | --- | --- |
| Core API suite | 255 passed, 3 CI-only skipped (258 total) | 258 passed (CI guards included) |
| Linear product API suite | 11 passed | 11 passed |
| Type check | Passed | Passed |
| Web unit tests | 23 passed | 23 passed |
| Production build | — | Passed |
| Browser suites (core + Linear golden) | 107 passed | 107 passed |
| Pull-request CI | Pending | |

Exit criteria for signing off 3.1 again:
- the reproductions fail before the fixes and pass after them (done);
- existing suites stay green (done);
- green pull-request CI;
- a review of the final diff.

## Sizing for 3.2–3.8

Estimates are in focused working days for the two-person team, sized from what 3.1 exposed.
They are estimates, not commitments.

| Step | Estimate | Main driver |
| --- | --- | --- |
| 3.2 Generic engine | 3–4 days | `agent.py` (~820 lines) plus planner, validator and language modules; reconciling definition v2 with the backend baseline; voice style from the definition |
| 3.3 One backend pipeline | 4–5 days | 41 browser-decided turns (~1,000 lines) to express as definition configuration; executor shim; ended-session handling; visitor conversations through `/api/turn` |
| 3.4 Knowledge | 1 day | Small retriever change plus the per-product knowledge store |
| 3.5 Records and migration | 3–4 days | Relationships, scope anchors, name-to-ID migration, scoped visitor record access, legacy column renames, rehearsal |
| 3.6 Web shell and adapters | 5 days | `page.tsx` (~4,000 lines) split into generic views plus the Linear adapter; product selection |
| 3.7 Billing product | 3 days | Definition, seed data, adapter, 10+ browser scenarios, 20-case evaluation, same-organization proof (design 3A) |
| 3.8 Frozen core and deletion tests | 1–2 days | Purity allowlist emptied; deletion tests for both products |
| **Total** | **20–24 days** | Roughly double the earlier 10-day experiment timebox |

This is a **revised estimate, not an approved deadline**. It is a scope expansion over the original
10-day experiment and needs its own schedule decision.

## Files changed in 3.1

- **New core modules:** `apps/api/app/definitions/`:
  - `vocabulary`, `safety`, `contract`, `loader`, `compatibility`, `registry`
  - `organizations`, `access`, `sessions`, `bootstrap`
- **Core changes:**
  - `db.py`: registry, organization, team, membership, product-binding and visitor-login tables; session pin columns; team on usage rows; seed loading
  - `tenancy.py`: `ProductContext` (organization, team, product, deployment); only the deployment ID is configuration
  - `auth.py`: member and visitor principals
  - `main.py`: principal-based turns, product-authorized speech, organization usage summary, visitor sessions, member-only product data
  - `session_manager.py`: full pin storage and lookup
  - `agent.py`: product resolution, pinning and per-turn checks; lookups by the pinned definition ID
  - `usage_ledger.py`, `provider_policy.py`, `speech_service.py`, `speech_providers.py`, `agent_reasoner.py`: product context and team attribution
- **Product package:** `products/linear_simplified/`:
  - definition v1, the demo organization seed, golden conversations and recordings, product tests
  - plus `apps/web/adapters/linear_simplified/manifest.json`
- **Web:** product ID and speech request (`product-config.ts`, `hybrid-voice-engine.ts`, `page.tsx`).
- **Tests:**
  - new core tests: `test_definition_contract.py`, `test_definition_registry.py`, `test_product_access.py`, `test_core_purity.py`, `core_purity.py`, `definition_fixtures.py`
  - updated: `test_usage_ledger.py`, `test_speech.py`, `test_reasoning_limits.py`, `test_agent.py`, `test_phase1_gaps.py`, `demo-agent.spec.ts`
  - harness: `tests/e2e/harness.ts`
- **Tooling:** `package.json` (product API tests), `playwright.config.ts` (product specs, one worker), `playwright.measure.config.ts` (demo seeds enabled explicitly).
- **Config and docs:**
  - `.env.example` (deployment ID, demo seeds, session age) and `README.md` (local demo flags)
  - this report
  - design document revision 4
  - a supersession note in the Milestone 2 report
