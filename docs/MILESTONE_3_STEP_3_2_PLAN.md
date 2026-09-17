# Milestone 3, Step 3.2: Generic Conversation Engine — Implementation Plan

Status: **plan, revision 3.1. Slice 1 is approved to start; the milestone is not approved.** Revision 3.1 clarifies failure outcomes, expiry and the mandatory slice 3 review.
Date: 2026-09-17. Design references: `docs/MILESTONE_3_PRODUCT_PROFILE_DESIGN.md` sections 5, 8, 9.1, 10 and 11; `docs/MILESTONE_3_STEP_3_1.md`.

Revision 3 corrects four findings in the execution and confirmation rules:
- execution is atomic, and a commit decides the race between cancellation and execution (section 5.2);
- confirmation has one rule that covers both its sources (sections 3 and 4.3);
- replay has a single contract (section 5.3);
- the limits of keyless writes are stated (section 5.4).

Revision 2 corrected five review findings:
- guardrails now run before any pending state, and corrections never guess (section 3);
- the generic action contract is complete (section 4);
- execution has an explicit owner and lifecycle (section 5);
- cached definitions never carry approval (section 2);
- the dependency check is transitive (section 10.2).

## 1. Goal and boundaries

**Goal:** Edith's backend decisions come from the session's pinned Product Definition, not from Linear-specific code. The turn API keeps its shape, and the current web app keeps working.

**In scope:**
- a text normalizer driven by the definition's vocabulary;
- an intent router driven by its intents, clarifications and guardrails, with explicit conversation memory;
- an action-contract validator;
- an execution ledger for dispatched actions;
- a narrow, product-neutral record lookup interface;
- a prompt builder and a response composer;
- the temporary backend translation to today's action names;
- Linear definition v2.

**Out of scope (unchanged owners):**

| Work | Step |
| --- | --- |
| Moving the browser's own decisions into the backend, including the browser's own "Done. I updated…" replies | 3.3 |
| Knowledge store | 3.4 |
| Record store, relationships and the demo-data migration | 3.5 |
| Generic web shell and adapters | 3.6 |

3.2 defines the lookup *interface*, a temporary Linear implementation on today's store, and a thin execution check on today's write endpoints. It does not start the record-store migration.

## 2. Target components

All new core code lives in `apps/api/app/engine/` and must not depend on product-specific modules, directly or indirectly (section 10.2).

| Component | Responsibility | Replaces |
| --- | --- | --- |
| `DefinitionCache` | Caches **parsed definition content only**, keyed by (definition ID, version, checksum) | Direct `PRODUCTS_BY_ID` lookups |
| `Normalizer` | Lower-casing, punctuation and whitespace rules (platform), plus the definition's `vocabulary.corrections` | `language_normalizer.py` |
| `IntentRouter` | Deterministic routing with the precedence in section 3, and parameter extraction through `RecordLookup` | `action_planner.py`, `intent_extractor.py`, `reasoning_policy.py`, `conversation_manager.py`, the boundary checks in `agent.py` |
| `ConversationMemory` | Explicit per-session state: pending clarification, pending confirmation, focused record, last person, last view (section 6) | Signals re-read ad hoc in `agent.py` |
| `ActionContractValidator` | Checks a `GenericAction` against the contract in section 4, the pinned definition, the caller's access and the lookup's scope | `action_validator.py` |
| `ExecutionLedger` | Records dispatched actions and their outcome (section 5) | Nothing today: success is assumed |
| `RecordLookup` (protocol) | Scope-filtered, read-only record and people lookup (section 7) | `demo_data.py` imports in the engine and reasoner |
| `PromptBuilder` | Fixed platform instructions, with product text and data in a delimited section. Keeps the Milestone 2 token limits. | Prompt code in `agent_reasoner.py` |
| `ModelProposalParser` | Strict parsing of the model output (section 8) | Parsing in `agent_reasoner.py` |
| `ResponseComposer` | Speech from the definition's templates, with values inserted as plain text; platform default text when a key is missing. Never uses completion wording for an action that has not executed. | Sentences in `agent.py` |
| `ConversationEngine` | Turn orchestration. Turn, session, cancellation, pinning and accounting semantics are unchanged. | `DemoAgent` internals |

**Cache rule:** the cache holds parsed content, never approval.

Every turn, before the cache is consulted, the platform gates (section 3, stage 0) re-check all of the following against the database:
- the principal's product access;
- the product binding's state and team;
- the definition version's lifecycle state and recorded checksum;
- the file's current checksum;
- the session pin.

A cached entry is used only after all of them pass, and only for the exact (ID, version, checksum) they approved.

**Platform vocabulary additions** (code-owned, additive; v1 stays valid):
- response keys `record_create_proposed`, `record_update_proposed`, `confirm_action` and `action_cancelled`;
- closed lists `AFFIRMATIONS` and `CORRECTION_CUES`.

No definition *schema* change is planned (section 10.4).

## 3. Routing precedence (normative)

The router evaluates these stages in order and stops at the first that decides.

0. **Platform gates.** These run before routing:
   - authorization, session pinning, definition lifecycle and checksum (unchanged from 3.1/3.1a);
   - the cache rule in section 2.

   No definition text can influence them, and they never depend on guardrail wording.
1. **Refusals first.** If any guardrail matches, Edith refuses with its response. Guardrails can only refuse, never permit.
   - A refusal also **discards** any pending clarification or confirmation.
   - Nothing pending is completed on a turn that matches a refusal.
2. **Pending confirmation.** This exists whenever `requires_confirmation` is true for a validated action (section 4.3).
   - It executes only if the whole normalized message is in `AFFIRMATIONS` ("yes", "yes please", "confirm", "go ahead", "do it").
   - Any other message cancels it (`action_cancelled`), and the message is then routed from stage 3.
3. **Pending clarification.**
   - **New request:** if the message matches any intent or clarification rule, the pending clarification is discarded and the message is routed from stage 4.
   - **One candidate named:** if the message identifies **exactly one** remaining candidate (by name, record ID, or ordinal such as "the second one"), the request proceeds with it.
   - **Correction cue** (`CORRECTION_CUES`: "no", "not that one", "the other one", "wrong one"). The cue removes a candidate only when the conversation has singled one out:
     - **Singled out:** Edith's previous reply named exactly one candidate (for example, "Did you mean Maya Chen?"). That candidate is removed, and Edith **asks again** with the rest. She never picks one herself.
     - **Not singled out:** the previous reply listed several candidates. Edith asks which one to exclude, or which one the visitor wants.
   - **Mutations need an explicit yes.** When a correction leaves exactly one candidate for a mutating action, the action is validated with `correction_requires_confirmation`. It then goes through stage 2, and is never executed directly from a correction.
   - **Anything else:** the question is asked again once, then expires.
4. **Exact phrases.** An intent or clarification whose `exact` list contains the whole normalized message wins.
5. **Intent match groups.** Among intents whose every `match` group has a hit and no `exclude` term is present:
   - **higher specificity wins:** the number of match groups, then the total number of matched terms, then the length of the longest matched term;
   - **a remaining tie never falls back to file order.** It produces a clarification: the first matching clarification rule, else the platform `fallback` response.
6. **Requirement extraction** for the winning intent (`person`, `record`, `selected_record`, `unknown_person`), through `RecordLookup`:
   - exactly one visible match: proceed;
   - several visible matches: ask with at most three candidates, recorded as pending;
   - no visible match: the `unknown_person` response, or an ask when the requirement is a record.
7. **Clarification rules.** If no intent matched, the first matching clarification rule asks its question and records it as pending.
8. **Model path.** Used only when enabled, within budget, and none of the stages above decided. The proposal passes through `ModelProposalParser` and `ActionContractValidator`. Any failure falls back to stage 9. Model output never authorizes anything and never completes a pending state.
9. **Fallback.** The definition's `fallback` response, or the platform default.

**Never guess:** when a decision would need a guess (tied intents, several candidates, a correction with more than one remaining candidate, a missing required field), Edith asks. Mutations always need either a fully specified request or an explicit confirmation.

## 4. Generic action contract (normative)

### 4.1 Shape and capability

```text
GenericAction {
  action_key                          # must exist in the pinned definition
  params: { view?, control?, target?, filter?, fields?, prefill? }
}
target  = { entity, id }              # resolved through RecordLookup before validation passes
filter  = { field, value }
fields  = { name: value }
prefill = { name: value }
```

- **The capability is always derived from `action_key`.** It is never accepted from the model or from any request. A model output containing `capability` is malformed.
- **Internal defence:** the engine's typed `GenericAction` carries the derived capability, and the validator re-checks that it equals the definition's value. That catches router bugs, not model output.

### 4.2 Parameters per capability

Values not listed here are forbidden, and an unknown parameter is always rejected.

| Capability | Required | Optional | Forbidden | Value rules |
| --- | --- | --- | --- | --- |
| `NAVIGATE_VIEW` | `view` | — | `control`, `target`, `filter`, `fields`, `prefill` | `view` equals the action's `view` and is navigable (or a platform view) |
| `OPEN_RECORD` | `target` | — | `view`, `control`, `filter`, `fields`, `prefill` | `target.entity` equals the action's `entity`; the ID resolves to a visible record |
| `FILTER_RECORDS` | `filter` | — | `view`, `control`, `target`, `fields`, `prefill` | `filter.field` equals the action's `by`. The value must be valid for that field's type: a reference resolves to a visible record of the target entity, and an enum value is one of the declared values. |
| `CREATE_RECORD` | `fields` | — | `view`, `control`, `target`, `prefill` | Only names in the action's `fields`, and every required entity field present. Each value passes its field spec (type, enum, maximum length, text safety). References resolve to visible records. |
| `UPDATE_RECORD` | `target`, `fields` (non-empty) | — | `view`, `control`, `filter`, `prefill` | `target` resolves to a visible record of the action's entity. Fields are only names in the action's `fields`, and none is marked `editable: false`. Each value passes its field spec, and references resolve to visible records. |
| `HIGHLIGHT_CONTROL` | `view`, `control` | `target` (required when the action sets `record: true`); `prefill` (only when the action declares `prefill`) | `filter`, `fields` | `view` and `control` equal the action's values. `target` follows the `OPEN_RECORD` rules. `prefill` names are a subset of the action's `prefill` and pass the field specs. |

### 4.3 Confirmation

```text
requires_confirmation = action.confirm                      # declared in the definition
                        OR correction_requires_confirmation  # a mutating action whose target
                                                             # came from a correction (section 3)
confirmation_reason   = "definition" | "correction"          # recorded with the pending state
```

- **Actions needing confirmation** are validated in full, then **not dispatched**. The engine stores them as a pending confirmation, with their resolved parameters and the reason, and asks `confirm_action`. The execution key is created only at dispatch.
- **On an explicit affirmation** (section 3, stage 2), the parameters are re-validated against the current lookup and the action is dispatched. Any other message cancels it.
- **Cancellation paths:** a pending confirmation expires after one turn and is discarded by a refusal, a scope change or turn cancellation.
- **Test coverage:**
  - Linear v1 sets `confirm` on no action, so the recording is unaffected. The definition path is tested with the synthetic fixture's `update_contact` (`confirm: true`).
  - The correction path is tested with a `confirm: false` mutation (Linear's `update_issue`, and a synthetic action with `confirm: false`).

## 5. Execution boundary and lifecycle

**Who executes today:**
1. The backend returns a validated action.
2. The browser executor applies it.
3. For creates and updates, the browser writes through the backend record endpoints (`/api/demo-data/issues`, and so on) and updates the screen only after the write succeeds.

This boundary stays in 3.2. The browser remains the executor, and the backend write endpoints remain the only place a mutation happens.

**Lifecycle:**

| State | Owner | Meaning |
| --- | --- | --- |
| `proposed` | Router or model | A candidate action, with no authority |
| `validated` | `ActionContractValidator` | The contract, scope and access checks passed |
| `awaiting_confirmation` | Engine | A `confirm` action waiting for an explicit yes |
| `dispatched` | Engine and `ExecutionLedger` | Sent to the client with an **execution key** (unique per session, turn and action) |
| `executed` | Write endpoint and `ExecutionLedger` | The backend write committed under that key |
| `failed` | Write endpoint and `ExecutionLedger` | The write was rejected (validation, scope, conflict, not found) |
| `cancelled` | Engine and `ExecutionLedger` | The turn was cancelled or superseded before execution |

### 5.1 Temporary execution check
This runs on today's write endpoints until 3.5, for writes that carry an execution key.

- **Dispatch.** The engine creates the key, a random value bound to the session owner, organization, product, session, turn, action, target and field values. It stores the key as `dispatched`, with an expiry of 10 minutes.
- **Execution.** A keyed write is accepted only when every check in section 5.2 passes in the same transaction.

### 5.2 Atomic execution (normative)
One keyed write is **one database transaction** (`begin immediate`). The following happen inside that transaction, in this order, or not at all:

1. **Re-check authorization now:**
   - the caller's membership and product access, and the record grant and scope;
   - the session pin and the definition lifecycle, which must still be usable as at a new turn. Being usable at dispatch time is not enough.
2. **Load the key and apply the replay contract** (section 5.3).
3. **Check the request.** The request must equal the bound action, target and field values.
4. **Perform the record mutation.**
5. **Store the outcome** (`executed` with its result, or `failed` with its reason) on the key row.

**What the transaction guarantees:**
- **Concurrency.** SQLite serializes writers, so concurrent requests with the same key produce **exactly one** mutation. Every other request sees the stored outcome.
- **Cancellation versus execution: whichever commits first wins.**
  - **Cancellation first:** a turn's cancellation or supersession marks its `dispatched` keys `cancelled` in its own transaction, and a later write is refused.
  - **Execution first:** the outcome stays `executed`. Cancellation changes only keys that are still `dispatched`. It never relabels or undoes an executed or failed key, and the cancel response says the action already ran.
- **Two kinds of failure:**
  - **Rule rejection:** the request is authorized, but the record change is refused by a rule (validation, scope, not found, conflict). No mutation happens, but the transaction **commits** a `failed` outcome with its reason.
  - **Unexpected error:** anything else (database error, crash, bug). The transaction **rolls back** the mutation and the outcome together, and the key stays `dispatched`.
- **Failed authorization writes nothing.** If step 1 fails, or the key belongs to another owner, organization or product, the transaction ends without touching the ledger. A caller can never alter a ledger entry that is not theirs.

### 5.3 Replay contract (normative)

| Key state | Request | Result |
| --- | --- | --- |
| `dispatched`, not expired | Same owner, identical request | Execute (section 5.2) |
| `executed` | Same owner, identical request | Return the stored result; no second write |
| `failed` (rule rejection, committed) | Same owner, identical request | Return the stored failure; no retry under this key. A retry needs a new turn and a new key. |
| `dispatched` after a rolled-back attempt (unexpected error, nothing committed) | Same owner, identical request, not expired | Retry allowed |
| any state | Different parameters, action or target | `409`, nothing written |
| any state | Different owner, organization or product | Refused as not found |
| `cancelled`, unknown, or `dispatched` and expired | any | Refused, nothing written |

**Expiry and authorization for replay:**
- **Expiry only stops unused keys.** It prevents an unused `dispatched` key from executing. It never erases, relabels or re-executes a committed `executed` or `failed` outcome.
- **Replay needs current authorization.** Returning a stored result still requires the step 1 checks to pass now. A caller who has lost access gets a refusal, not the stored result.

**Durability:** the outcome is stored in the same row, and committed with the mutation. Replay protection therefore survives restarts.

### 5.4 Stated limitation: keyless writes
- **Keyed writes only.** The execution ledger protects **assistant-originated** writes that carry a key. The product's own forms still write without a key, through today's endpoints, under the 3.1a record-access rules alone.
- **Not a universal boundary.** A client that omits the key falls back to that manual path. Assistant confirmation is therefore **not** a universal security boundary in 3.2: it guarantees what Edith executes, not what every client may write.
- **Acceptable temporarily.** Manual-write authorization independently permits exactly the same operations. The record store in 3.5 decides whether keyless writes remain.
- **Browser test.** A browser test proves that every assistant-originated mutation sends its execution key (section 10.6).

**Honest wording:**
- **Before the write:** for a dispatched mutation, the backend reply uses `record_create_proposed` or `record_update_proposed` ("I'll update LIN-142: assignee to Noah Patel.").
- **After the write:** completion wording (`record_created`, `record_updated`) is used only once the ledger shows `executed`, for example on a following "what changed?" turn.
- **Reproduced by the recording:** today's backend already says "Done. I updated…" and "I created…" before any write happens. This is corrected and listed in section 11 (five cases).
- **Client wording:** the client receipt reports success only after the write returns, as it does today.

## 6. Conversation memory

| State | Set by | Survives | Cleared by |
| --- | --- | --- | --- |
| Pending clarification: key, expected slot, remaining candidates, rejected candidates, turn number | Stages 6 and 7 | One following turn | Resolution; any routed intent or refusal; expiry; scope change; turn cancellation |
| Pending confirmation: action, resolved parameters, confirmation reason, turn number | Section 4.3 | One following turn | Affirmation (then dispatch); any other message; refusal; scope change; turn cancellation |
| Focused record (entity, ID) | A validated action on a record | Navigation to other views | A new focus; scope change; the lookup no longer returning it for this caller |
| Last person | A resolved person requirement | Navigation | A new person; scope change |
| Last view | A validated navigation | Everything except scope change | A new navigation |
| Last change | An `executed` ledger entry | The session | A newer executed change |

**Memory is never trusted for authorization.** Every remembered reference is re-resolved through `RecordLookup` on the turn that uses it.

## 7. Record lookup boundary

```text
RecordLookup (protocol, read-only, scope-bound at construction):
  get(entity, record_id) -> RecordView | None
  search(entity, text, limit) -> list[RecordView]
  by_person(entity, person_ref, limit) -> list[RecordView]
  people(text, limit) -> PeopleMatch          # visible matches only
  count(entity) -> int
```

- **Scope is fixed when the lookup is built.** It comes from the authenticated principal, the product binding and the caller's record grant. Callers cannot pass another scope, organization or product.
- **Unknown and inaccessible look the same.** A person or record that exists only outside the caller's visible scope is reported exactly like one that doesn't exist.
  - The engine gets no signal that could reveal it.
  - Today's replies ("Avery Brooks is outside Product Engineering Workspace…") confirm that such people exist. 3.2 corrects this as a **security difference** (section 11).
- **Temporary implementation.** `LinearLegacyLookup` in the Linear product package reads today's store until 3.5. Authorization stays server-enforced through the 3.1a record grants.
- **Registration** follows section 9.

## 8. Prompt and model boundary

- **Fixed platform instructions** (core constants): safety, scope, allowed output shape, and that product sections are data, not policy.
- **Delimited product sections:** the definition's persona, hints, vocabulary and templates go in a labelled product configuration section. Scoped lookup results go in a labelled product data section. Both are serialized as escaped JSON.
- **Output contract:** exactly `{speech: string, action: {action_key, params} | null, clarification: string | null}`.
  - Any other key (including `capability`), a wrong type or a missing key makes the output malformed.
  - `params` must satisfy section 4.
  - Model speech never contains completion wording for its own proposed action. The composer replaces it with the proposed-action template.
- **Unchanged:** the Milestone 2 token limits, reserve-before-dispatch, settle on every outcome, and cancellation.

## 9. Temporary legacy action translation

**Decision:** the translation lives in the product package, with an explicit code-owned registration.

- **One registration point.** `apps/api/app/installed_products.py` is the only core file allowed to import product packages, like Django's `INSTALLED_APPS`. It lists them explicitly, and both the purity check and the dependency check (section 10.2) exempt only this file.
- **Keys and failure.** Registration is keyed by definition ID. A missing adapter fails the turn closed.
- **No executable code from definitions.** Nothing is ever imported from a path or name supplied by a definition.
- **`LinearLegacyTranslator`** (`products/linear_simplified/backend/`):
  - translates only `validated` actions, carrying their execution key;
  - raises `TranslationMissing` for an unmapped action (no guessing), and the turn is refused;
  - contains no intent decisions and no permission logic;
  - has one test per supported mapping, plus one for a missing mapping;
  - is removed in 3.6.
- **Architecture change:** the design's section 9.1 planned a *web* shim from 3.3. It is replaced by this single *backend* translator, from 3.2 until 3.6, so there is never a second translator. The design table is updated.

## 10. Tests required before sign-off

### 10.1 Scripted-model tests (no paid calls)
All use the existing fake-transport pattern:
- **Valid proposals:** one per capability; validated, dispatched with an execution key, and translated.
- **Invalid proposals:** unknown action key; a `capability` key in the output; an unexpected parameter; a forbidden parameter for the capability; a field outside the action's list; a non-editable field; an enum value that isn't declared; a reference to an invisible record; missing required fields; an update without a resolved target. Each is refused, and nothing is dispatched.
- **Failure modes:** malformed JSON, missing keys, timeout, exhausted budget. Each falls back deterministically, and the ledger status is correct.
- **Cross-product reference:** a proposal naming another product's record or entity is refused. The lookup never returns it.
- **Injected instructions:** product configuration or record text containing instructions that conflict with the platform rules. The instructions stay inside the data section, and any resulting proposal is validated and refused when invalid.
- **No completion claims:** model speech saying "Done, I updated it" for a proposal is replaced by the proposed-action wording.
- **Existing tests unchanged:** accounting and cancellation tests stay green.

### 10.2 Architecture tests
- **Purity allowlist:** the engine files leave it (section 12).
- **Transitive dependency boundary (new):**
  - **The check:** it parses imports with `ast` and follows every `app.*` module reachable from `app/engine/*`, and from any module those import.
  - **It fails** if the graph reaches `app.services.demo_data`, `app.services.product_data_store`, `app.workspace_config`, `app.product_config` or any `products.*` module. The only exemption is `app/installed_products.py`, and only as the registry's entry point.
  - **What it can't see:** dynamic imports (`importlib`, `__import__`). These are banned under `app/engine/` by the same test.
  - **Review:** each pull request in this step also lists the engine's direct dependencies for review.

### 10.3 Synthetic-definition proof
- **Fixture:** the neutral `sample_desk` definition (accounts, contacts, notes), with an in-memory `RecordLookup`, an in-memory execution check and no translator.
- **Proof:** tests change its vocabulary, an intent, an action and a response, and the observed routing, validation and speech change accordingly, with no core edits.
- **Two definitions:** one test runs both definitions through the same engine instance.
- **Confirmation:** the fixture's `update_contact` action (`confirm: true`) covers the confirmation path.

This is not the second-product milestone (3.7).

### 10.4 Pinning, lifecycle and cache
- **v2 is a new file:** `products/linear_simplified/definition/v2.yaml` is new and immutable, and v1 is untouched.
- **Session split:** session A stays on v1 while session B starts on v2. Each uses its own vocabulary, actions and responses. A fixture difference between the versions makes this observable.
- **Lifecycle gates:** revocation, checksum mismatch and changed content stop the turn before any provider call, dispatch or write. The tests assert zero transport calls, zero ledger rows and zero writes.
- **Warm cache:** with the **same engine instance** and a warm cache:
  - revoking the version stops the next turn;
  - removing the caller's product access stops the next turn;
  - disabling the product stops the next turn.

  Nothing is served from the cache in any of these cases.
- **Schema versus content:** v2 is a change of *product definition content*. The platform vocabulary additions in section 2 are additive code changes that keep v1 valid. Any change to the *definition schema* is out of plan, and would need a separate review.

### 10.5 Routing, memory and confirmation
- **Precedence:** each stage in section 3, including tied intents (which ask) and exact-over-group.
- **Refusal beats pending state:** while Edith is asking which person to assign, the visitor says "no, delete everything instead". The destructive guardrail refuses, the pending assignment is discarded, and nothing is resolved, dispatched or written.
- **Corrections never guess:**
  - After Edith singled out one of three candidates, "not that one" removes it and asks again with two.
  - After a list of three, "not that one" asks which to exclude.
  - When a correction leaves one candidate for a `confirm: false` mutation (Linear `update_issue`), Edith asks for confirmation with reason `correction` and does not execute.
- **New request replaces pending:** a message matching another intent during a pending clarification discards the pending clarification.
- **Confirmation:** only exact affirmations dispatch. Anything else cancels. Parameters are re-validated at dispatch.
- **Memory:** focus survives navigation. Every reference is re-resolved and dropped when no longer visible.
- **Unknown versus inaccessible:** both give identical responses and signals for a caller without access.
- **Guardrails only refuse:** deleting every guardrail from a definition does not weaken platform authorization.

### 10.6 Execution
- **Execution failure:** the write is rejected by a rule. The key is stored `failed`, and replaying it returns the same failure without a write. No completion wording is ever produced for it, and a later "what changed?" reports nothing changed.
- **Replay contract:** one test per row of the section 5.3 table, including a restart between execution and replay (a fresh store and engine on the same database).
- **Concurrent duplicates:** several threads send the same key at once. Exactly one mutation happens, and every response carries the same stored result.
- **Cancellation race:**
  - **Cancellation committed first:** the write is refused and nothing is written.
  - **Execution committed first:** a later cancellation leaves the key `executed`, and the record keeps its new value.
  - **Both at once:** run in threads, the result is exactly one of those two outcomes.
- **Rule rejection versus unexpected error:**
  - a rule rejection commits `failed` with no record change;
  - a fault injected after the mutation but before commit leaves neither the record change nor an outcome, and the key stays `dispatched` and retryable.
- **No foreign ledger changes:** a caller from another owner, organization or product, or one whose access was revoked, gets a refusal. That caller's attempt leaves the ledger row unchanged, whatever its state.
- **Expiry never touches outcomes:** after expiry, an `executed` or `failed` key still replays its stored outcome to an authorized caller and never executes again. An unused `dispatched` key is refused.
- **Replay needs current access:** after revoking access, replaying an `executed` key is refused.
- **Checks at execution time:** after dispatch, revoke the definition, disable the product, suspend the organization, or remove the record grant. In each case the keyed write is refused and nothing is written.
- **Expiry:** an expired key is refused.
- **Manual writes:** form writes without a key behave exactly as today (existing tests).
- **Browser:**
  - intercepted write requests prove that every assistant-originated create and update carries its execution key;
  - form-originated writes carry none;
  - the existing failed-save tests stay green.

## 11. Golden parity rules

- **Exact comparison** of every recorded field against `backend_decisions.json`. The recording is never regenerated to make tests pass.
- **Reviewed differences** live in `products/linear_simplified/tests/golden/reviewed_differences.json`.
  - Each entry has: case, turn, field, recorded value, new value, kind (`wording`, `behaviour` or `security`), and reason.
  - The test fails on any unlisted difference **and** on any listed difference that no longer occurs.
- **Defects are not preserved for parity.** Each is corrected, listed, and gets its own regression test. Known so far:

| Kind | Defect | Recorded cases |
| --- | --- | --- |
| `security` | A reply confirms that a person exists outside the caller's scope | `update-outside-person`, `scope-outside-person`, `scope-platform-outside-person` |
| `behaviour` | The backend claims completion before any write | `update-reassign`, `update-priority`, `update-status` ("Done. I updated…"); `create-known-owner`, `create-open-and-assign` ("I created…") |

  **Likely also affected:** `update-unknown-person`, where an unknown person (Priya) is answered with "That work is outside…". Under the unknown-equals-inaccessible rule it should get the `unknown_person` response. If it changes, it is listed with that reason.

  Any further differences found by the slice 2 shadow harness are added case by case.
- **Deterministic path only.** The recording exercises the deterministic path (the LLM is off). The model path is proven by section 10.1, not by the recording.

## 12. Purity allowlist changes

Expected removals:
- `action_planner.py`
- `action_validator.py`
- `agent.py`
- `agent_reasoner.py`
- `conversation_manager.py`
- `intent_extractor.py`
- `language_normalizer.py`
- `product_config.py`

Files deleted outright are removed from the list too. `retriever.py` (3.4) and the record modules (3.5) stay. `main.py` and `product_data_store.py` stay listed, although they gain the execution check.

## 13. Delivery slices

Each slice leaves every suite green and is reviewable on its own.

| Slice | Contents | Exit evidence |
| --- | --- | --- |
| **1. Contracts and fixtures** | Engine types (`GenericAction` with the section 4 rules, lifecycle states, memory model); `RecordLookup` protocol; `installed_products.py`; platform vocabulary additions; synthetic engine fixture; golden difference harness; transitive dependency test | New tests green; no behaviour change |
| **2. Normalizer and router** | `Normalizer`, `IntentRouter`, `ConversationMemory` with the section 3 precedence; a shadow harness compares router decisions with the current engine on every golden case | Section 10.5 routing tests; shadow differences listed |
| **3. Validator, lookup, execution and translator** (mandatory transaction review before slice 4) | `ActionContractValidator`; `ExecutionLedger` plus the execution check on today's write endpoints; `LinearLegacyLookup`; `LinearLegacyTranslator` | Section 4 validator tests; section 10.6 execution tests; lookup-scope tests; per-mapping translator tests |
| **4. Prompt and composer** | `PromptBuilder`, `ModelProposalParser`, `ResponseComposer` with the honest-wording rule | All section 10.1 tests |
| **5. Integration and parity** | `ConversationEngine` replaces the `DemoAgent` internals; `DefinitionCache`; Linear v2; the browser passes the execution key on writes; allowlist shrinks | Golden parity with reviewed differences; section 10.4 tests; synthetic proof; full Windows and Linux runs including browser tests; green PR CI |

## 14. Exit criteria

1. Golden compatibility, with every difference individually listed and justified.
2. Deterministic and scripted-model paths validated.
3. Pinning, cache, scope, cancellation and provider-budget protections preserved.
4. The generic lookup boundary, atomic keyed execution with the section 5.3 replay contract, the stated keyless-write limitation, and the tested legacy translation in place.
5. The synthetic-definition proof passing without core modifications.
6. Engine files removed from the purity allowlist, and the transitive dependency test green.
7. Green Linux CI, including the existing browser tests.

## 15. Sizing and risks

- **Size:** 5–6 focused days, **provisional**, and more uncertain than before. Transactional execution (authorization re-checks, replay contract, cancellation race, restart durability) is more than a thin endpoint check.
- **Mandatory slice 3 transaction review.** Slice 4 does not start until the stakeholder has reviewed slice 3. The review must confirm:
  - the record store's write and the ledger's check and outcome use **the same connection and the same transaction** (shown in code, not assumed);
  - the concurrency, cancellation-race, rollback and foreign-caller tests in section 10.6 pass and actually exercise that transaction.
- **Main risk:** separating routing, memory, record access and execution without changing behaviour, not the file sizes.
- **Specific risks:**
  - **Hidden ordering dependencies** in today's planner. The slice 2 shadow harness exposes them before the switch.
  - **The web change.** Passing the execution key is a small change to today's write calls, covered by the new key-presence browser test and the existing suite.
  - **Write-path coupling.** Today's store opens its own connection per write. The execution check must share that transaction, which means a small refactor of the store's write methods.
  - **Current reply wording** that uses organization data stays as recorded unless listed.
  - **Known corrections** (section 11) change at least eight golden turns. Each is listed.
