# Milestone 3.2, Slice 3: Validator, Lookup, Execution Boundary and Translator

Status: **approved at the local implementation level; final sign-off pending green Linux CI on the pull request.** Three review rounds reproduced eight defects on this branch — four in routing and validation, one dishonest translation, and two in the transaction boundary itself. All eight are fixed with regression tests, and the stakeholder has approved the routing, validation, translation, lookup and transaction-boundary work. Slice 4 may begin once CI is green.
Date: 2026-09-17. Plan: `docs/MILESTONE_3_STEP_3_2_PLAN.md` (revision 3.3), sections 4, 5, 7 and 9.
Scope: this is Milestone 3.2, slices 2 and 3. Step 3.3 has not been started.

## What was built

| Component | File | Notes |
| --- | --- | --- |
| Action contract validator | `apps/api/app/engine/validator.py` | Checks shape, view navigability, record and person visibility, and every value against its declared type, bounds and allowed values. Returns `ValidatedAction` or a `Refusal` with a stable code. |
| Execution ledger | `apps/api/app/engine/execution.py` | One-time keys, the claim decision (proceed / replay / refuse), outcome settlement, turn cancellation. Stores identifiers and outcomes only: a request digest, the changed record's ID and a result code. |
| Execution guard | `apps/api/app/services/execution_guard.py` | Re-runs access, product, team, definition and session-pin checks **on the write transaction's connection**. |
| Keyed write boundary | `apps/api/app/services/record_writes.py` | Runs the re-checks, the claim, the record change and the outcome in one `begin immediate` transaction. Product-neutral: the caller supplies the change. |
| Keyed record endpoints | `apps/api/app/main.py` | `POST/PUT /api/demo-data/issues` accept `X-Execution-Key` with `X-Session-Id`. This is live write handling, not dormant code. Writes without a key behave as before. |
| Connection threading | `db.py` (`use_connection`), `organizations.py`, `registry.py`, `session_manager.py`, `record_access.py`, `product_data_store.py` | Reads and writes can join a caller's transaction instead of opening their own. No behaviour change when no connection is passed. |
| Live record lookup | `products/linear_simplified/backend/lookup.py` | Scope-bound at construction over the real store; built from a record grant. |
| Legacy translator | `products/linear_simplified/backend/translator.py` | Validated action → today's action type and payload. Total: no mapping means `TranslationMissing`, never a guess. |
| Package registration | `products/linear_simplified/backend/package.py` | Both factories registered in code, found by definition ID. |

## The transaction boundary

A keyed write does exactly this, inside one `begin immediate` transaction on one connection:

1. **Re-check standing** — organization active, product active and still bound to the same team, team active, caller still holds a record grant, the session exists, belongs to this caller's organization and product, is not expired, and its pinned definition version, checksum and file still match.
2. **Claim the key** — the key must exist, belong to this tenant, product **and** user, have been issued for **this session**, match the digest of this write request, not be cancelled, and not have expired.
3. **Change the record** — with the product's own rule checks (visibility of the record now and after the change, references, duplicates).
4. **Settle the outcome** on the same key row.

Consequences, by design:

| Situation | Result |
| --- | --- |
| Key already `executed` | Same execution attempt, no second write; the record's **current visible state** is returned. |
| Key already `failed` | The original rejection reason is returned again (409). No write. |
| Key `cancelled` before the write commits | Refused (`execution_cancelled`). No write. |
| Cancellation arrives after the write commits | Cancellation changes nothing; the outcome stays `executed`. |
| Rule rejection (missing record, scope, reference, duplicate) | Commits as `failed` with a reason, and the caller gets the rule's own HTTP status. |
| Unexpected error | **Nothing commits.** No record, no outcome; the key stays `dispatched` and can be retried. |
| Unused key older than 600 seconds | Refused (`execution_expired`). An already-settled key still replays. |
| Anything about the caller's standing changed | Refused with a 403 and a stable reason; the key stays `dispatched`. |

**Refusal vocabulary.** A key problem is a 409 (`unknown_execution_key`, `execution_request_mismatch`, `execution_cancelled`, `execution_expired`, `execution_already_settled`). A standing problem is a 403 (`access_*`, `session_*`, `record_access_withdrawn`). A key that belongs to someone else, or to another conversation, is reported as `unknown_execution_key` — never as "not yours".

## Test results

| Suite | Result |
| --- | --- |
| Core API | **452 run: 449 passed, 3 skipped** (CI-only) |
| Product (Linear) | **65 passed** |
| New: validator | `apps/api/tests/test_engine_validator.py` — 42 tests |
| New: execution boundary | `apps/api/tests/test_execution_boundary.py` — 48 tests, real HTTP endpoint against a real SQLite file |
| New: lookup and translator | `products/linear_simplified/tests/test_product_package.py` — 27 tests |
| What changed at runtime | The ticket write endpoints now accept an execution key, and the database plumbing threads connections. The **new conversation engine is still unwired**: no runtime path routes, validates or dispatches through it. Golden recordings and definitions are untouched; purity and dependency checks pass, and the engine's only dependencies are `db`, `definitions`, `safety`, `vocabulary` and `tenancy`. |

Browser tests, the web build and the type check were also run locally (see Blocker 2). The Linux CI run on the pull request is still the evidence that counts. No paid provider call was made.

What the execution tests actually prove, rather than assert:

- **One record from a race.** Two threads present the same key simultaneously; exactly one record exists and the loser replays the winner's result.
- **A real write lock.** While a keyed write is in flight, an independent connection cannot begin a write at all (`database is locked`), so the authority the guard read cannot change under the record change.
- **Cancellation race, both orders.** The key ends `executed` with one record, or `cancelled` with none. Never both.
- **Rollback.** With the store raising an unexpected error, no record and no outcome are committed, and the same key then works.
- **Re-checks bite after dispatch.** Product disabled, team disabled, definition revoked, record grant withdrawn, record-owning product reassigned, and a suspended organization each refuse the write and leave the key `dispatched`.
- **Durability.** A fresh ledger instance sees the settled outcome; a replay through the endpoint still writes nothing.
- **Keyless writes unchanged.** They succeed, are still scope-checked, and create no execution row.
- **The ledger holds no raw record content.** A test asserts the exact column list, and that none of the written title, assignee, project or priority appears anywhere in the row. The request digest is derived data, not content.

## Self-review findings, fixed in this slice

| # | Problem | Fix |
| --- | --- | --- |
| 1 | **A key was portable between a caller's own conversations.** The claim checked tenant, product and user but not the session the key was issued for. | The claim now requires the session, and a keyed write without `X-Session-Id` is refused, because without the conversation the definition pin cannot be re-checked. |
| 2 | **The record-owning product was resolved outside the transaction.** If that mapping changed, the write would have used a stale product. | It is re-read inside the transaction and must still match the product the key was issued for. |
| 3 | **Three validator checks could never fire.** Unknown view, control-outside-view and uneditable-field are already impossible: the shape check ties parameters to what the action declares, and the contract refuses such a definition. | The dead branches were removed, and tests now prove the guarantee where it actually lives. Keeping unreachable checks would have overstated the validator. |
| 4 | **Two authorizations answered the same keyed request.** The endpoint dependency refused first with a generic message, hiding the guard's reason and making the guard look decorative. | A keyed write is authorized by the guard alone, inside the transaction; a keyless write keeps the dependency it always had. |
| 5 | **A new person's name was translated as a person reference**, so proposing "add Maya Chen" failed to translate. | Only reference fields (`assignee`, `lead`) resolve to display names; a member's own `name` is text, because the person may not exist yet. |

## Second review pass, and what it found

A deliberate adversarial pass over this slice found five more defects. All five are fixed, each
with a test that fails on the old behaviour. Every claim below was verified against the code,
not assumed.

| # | Severity | Problem | Fix |
| --- | --- | --- | --- |
| 6 | **High** | **A create action that cannot satisfy its entity validated successfully.** The validator only required the fields the action itself declares, so an action allowed to set `name` on an entity that also requires `account` passed validation and then failed at the write — burning the key as `failed` for a proposal that could never succeed. Confirmed by probe. | The contract now refuses such a definition outright (`required field X can neither be set nor defaulted`), and the validator checks every required field of the entity rather than only the declared ones, so the two can never drift. Linear v1 already satisfies the rule. |
| 7 | **High** | **A keyed write against a never-seeded store burned the key.** Inside a caller-owned transaction the store skips seeding, so every workspace scope lookup returned nothing, the scope check rejected the write, and the outcome committed as `failed`. The first action on a fresh deployment would have failed permanently. | Reference data is prepared before the transaction opens. Seeding inside it would either be skipped or take a second lock. |
| 8 | Medium | **The session only had to belong to the caller's organization and product, not to the caller.** | The guard now also checks session ownership, on the same connection. |
| 9 | Medium | **The store accepted a caller-owned connection with no open transaction**, which would silently split the record change and the outcome into separate commits — the exact guarantee this slice exists to provide. | The store now refuses such a connection. |
| 10 | Low | **`last_executed` was non-deterministic** for two outcomes settled in the same second, so "what did you change?" could name the older action. | Ordering now breaks ties by insertion order. |

One earlier suspicion did **not** hold up and is recorded so it is not re-litigated: the four rule
rejections are sibling exception types, so the order they are matched in does not matter.

## Stakeholder blockers, and how they were resolved

### Ledger data — the ledger stored customer records. Fixed, the preferred way. **Accepted by the stakeholder.**

The minimal ledger was chosen over a retention scheme. The review named `result_json`; the same
objection applied to two more columns, so all three are gone. A row now holds only:

    execution_key  tenant_id  product_id  session_id  turn_id  user_id
    action_key  capability  entity  target_id
    request_digest        -- sha256 of the canonical request, not the request
    state  result_record_id  result_code  reason
    created_at  expires_at  settled_at

| Column removed | What it held | Replaced by |
| --- | --- | --- |
| `result_json` | A full copy of the written record | `result_record_id` and `result_code`. A replay reads the record under the caller's access at that moment. |
| `request_json` | The entire request body, so a create duplicated the record before it existed | `request_digest`, a sha256 of the canonical request. Matching still works; there is nothing to disclose. |
| `fields_json` | Every submitted field value, kept for "what did you change?" | Nothing. `last_executed` now *names* the change (entity, record ID, operation), and a caller that needs content reloads it. |

**The replay contract, stated once.** This is a deliberate change from the original plan, not a
restatement of it:

```text
Same execution attempt, no second write; return the record's current visible state.
```

It is not "the original result", and the two are not equivalent. Consequences, accepted:

- A replay shows the record **as it is now**. A test proves it: when someone else renames the
  ticket between the write and the replay, the replay shows the new name.
- A replay of a record the caller can no longer see is refused with `execution_result_unavailable`.
  The change still happened; its content is simply not this caller's to read any more, and
  deletion turns a previously successful request into a refusal.
- If exact historical response replay is ever required, it needs its own bounded receipt and an
  explicit retention period. We are not building that now.
- The table has never shipped, so this is a schema correction, not a migration.
- Records carry no revision column today, so the ledger records the operation and record ID
  without one. If record revisions are added later, the ledger can carry the revision too.

Growth is now bounded by row count rather than record size, and a row holds **no raw customer
content**. The request digest is derived data, not an opaque secret: it is an unsalted sha256 of a
predictable request, so a party who can guess the request can confirm the guess. It is kept because
matching is all it is for; it is not treated as a privacy boundary. A retention rule is therefore
not required for sign-off, and deleting settled rows past a horizon would cost nothing, because
nothing depends on them for content.

### Green CI — the remaining condition

Everything CI runs was run locally first, on Windows. Local runs are development evidence only:
the pull request's Linux run is what counts, and neither slice is complete until it is green. The
current figures are under **Complete run after the fixes** below; earlier figures in this document's
history are superseded by that run.

No paid provider call was made in any run: `LLM_ENABLED=false` throughout, and `MEASURE_PAID` was
never set.

### The two semantic tests you asked for

| Requirement | Test |
| --- | --- |
| A settled key is one historical attempt: a failed key keeps returning that failure even after the data would allow success, and only a **new** key may succeed | `test_a_settled_key_is_one_historical_attempt_not_a_retry_loop` — fails the update, creates the missing ticket at priority High, retries the same key (409 `record_not_found`, priority still High), then issues a fresh key and succeeds (priority Low) |
| Key order in the request body must not cause a mismatch | `test_key_order_in_the_request_body_does_not_cause_a_mismatch` — the same values in reversed order are accepted; the digest is computed over canonical JSON with sorted keys. Values that differ, including a default that changes the approved operation, still mismatch by design |

## Findings deliberately not fixed

Reviewed and dispositioned: B was accepted, C is now binding on slice 4, D and E are binding on slice 5.

| # | Disposition | Finding | Why it is not fixed here |
| --- | --- | --- | --- |
| B | Accepted | **Every refused keyed write still takes the write lock.** The re-checks run inside the transaction by design, so a caller presenting bad keys in a loop serializes all record writes. | The alternative is checking before the transaction, which is what we deliberately rejected. If this matters, the answer is rate limiting at the edge, not a weaker boundary. |
| C | Slice 4 | **The lookup has no snapshot.** Each call reloads the store, so a clarification list and the later write can disagree if data changes between them, and one turn can reload the store many times. | Fixing it means deciding the read model: a per-turn snapshot, or accepting that reads are live. That belongs with slice 4's composer work. |
| E | Slice 5 | **`cancel_turn` takes no caller.** It cancels by session and turn alone. Nothing exposes it yet. | Slice 5 must not wire it to a request without an ownership check. |

## Rules the review made binding for later slices

Recorded here because they are now requirements, not observations.

| Slice | Binding rule |
| --- | --- |
| 4 | The read model must be **chosen explicitly**: live reads or a per-turn snapshot. It may not stay accidental behaviour. |
| 5 | Edith may **never** report a change the translated action did not make. `create_member` now fails closed, so the case that prompted this rule cannot arise; the rule stands for any future action. |
| 5 | Nothing reachable from a request may call `cancel_turn` without first checking that the session belongs to that caller. |
| Later | A future agent-generated write must go through the keyed boundary. It may not bypass it merely because an older keyless endpoint exists. |

## Decisions carried into slice 5, unchanged

Still open from the slice 2 report: where conversational replies live, the follow-up rule, guardrail placement for broad scope, create defaults, and `clarify_person` in v2. Nothing in this slice pre-empts them.

## Limits of this slice, stated plainly

1. **Only the two ticket endpoints are keyed.** Projects, cycles and team members keep keyless writes; the engine does not propose them yet. Keyless writes are outside the execution guarantee (plan §5.4), and this is now covered by tests rather than by assumption.
2. **The key authorizes one request, matched by digest.** Key order and formatting do not matter, because the digest is taken over canonical JSON; differing values do, including a default that changes the approved operation. The dispatcher must therefore produce the request in the form the endpoint will receive it, and slice 5's client must echo the body it was given.
3. **Nothing dispatches yet.** `ExecutionLedger.dispatch` is exercised by tests, not by the runtime: the conversation engine that calls it arrives in slice 5. Today's `DemoAgent` is untouched. The write endpoints themselves, however, are live.
4. **The guard reads standing, then writes.** A change committed *after* the guard's read cannot interleave, because the transaction holds the write lock, but a long-running write still commits on authority read at its start. With SQLite's single-writer model there is no window; on a different database this assumption must be re-stated.

## Reproduced defects, and the state of approval

A stakeholder review reproduced four defects on this branch. Each is fixed, and each has a
regression test that fails on the old behaviour.

| # | Severity | Reproduction | Fix |
| --- | --- | --- | --- |
| 1 | High | `status CON-1 Closed, actually status CON-2 Closed` proposed changing **CON-1**; and with CON-1 remembered, `status CON-999 Closed` also proposed changing **CON-1** | Targets are extracted from the corrected clause, not the whole message. A record the visitor names but cannot have now produces a clarification; a remembered record is never substituted for it. Hidden and nonexistent give the same answer. |
| 2 | High | An empty list and two owners were both accepted for the scalar `owner` reference | Shape is checked before visibility: `ref` takes exactly one record, `refs` takes a collection, a required collection may not be empty, and a scalar for a collection field (or a collection for a scalar field) is refused. |
| 3 | High | With three candidates pending, `first or second` proposed assigning the first | Every ordinal in the reply is collected before anything is chosen. More than one selection asks again, and the pending question survives. |
| 4 | Medium | An exact clarification for `show contacts` lost to a grouped intent | Exact intents and exact clarifications are decided together, at the exact-phrase stage, before grouped matching. Two competing exact rules fall back rather than letting file order decide. |
| 6 | Medium | `create_member` translated to `HIGHLIGHT_ADD_MEMBER_BUTTON`, so a create silently became a highlight | The mapping is removed. `create_member` now raises `TranslationMissing`, and a test asserts that every action is either mapped or explicitly declared untranslatable. |

Finding 5 was about this report, and is corrected above: the status line no longer claims review
approval or completion, and the runtime-change wording now says what actually changed.

**What the stakeholder approved:** the minimal ledger, the replay contract as worded above, and —
after the third review round — slices 2 and 3 at the local implementation level: routing,
validation, translation, lookup and the transaction boundary, each with regression coverage.
**What is still outstanding:** the branch must be pushed and every Linux CI job must be green.
Slice 4 begins after that.

## Second transaction review: two more defects

The boundary review reproduced two high-severity defects that the earlier passes missed. Both are
fixed, both are reproduced by tests that fail on the old behaviour, and I reproduced each one
myself before changing anything.

### 7. High: a keyed create could settle as `executed` without creating anything

The execution digest covered the request body but **not** the legacy `Idempotency-Key` header,
which still selects a stored receipt inside the record store. A manual create followed by the
same action keyed with the same header produced:

```text
manual create: 200        keyed create: 200
execution key state: executed
issues with that id: still 1        same record returned: true
```

So a dispatched create was recorded as executed while it had merely replayed an older receipt.

**Fix.** On a keyed write the execution key is the only idempotency mechanism. A keyed request
carrying the legacy header is refused with 400, and no legacy request key is passed to the store
even internally, so a second mechanism cannot report an older receipt as this action's outcome.
Keyless writes keep the header, where it is the only mechanism there is.

### 8. High: a refused request rewrote product data

`_keyed` called `seed_if_empty()` before the key was validated, and seeding resets and
repopulates the record tables:

```text
response: 409 unknown_execution_key
projects before: 0        projects after: 4
```

That call was added to fix an earlier finding (a key burned on an unseeded store). It fixed the
symptom in the wrong place.

**Fix.** Demo records are seeded once, by the application's startup, behind the same explicit
`PIXEL_DEMO_SEEDS` switch as the organization seeds. No request creates reference data, so a
refused or unauthorized request cannot change product data at all. The earlier scenario is now
the operator's: with the workspaces genuinely absent, a keyed create is refused by the scope rule
and settles as `failed`, which is the honest outcome.

The seeding could not live in `app/definitions/bootstrap.py`: `db.migrate()` imports that module,
so the engine would have gained a transitive dependency on the record store. The dependency test
caught it immediately, which is what it is for.

### Regression tests added for these two

| Requirement | Test |
| --- | --- |
| One approved create produces exactly one new record | `test_one_approved_create_produces_exactly_one_new_record` |
| The reproduction itself | `test_a_keyed_create_cannot_settle_on_an_older_receipt` |
| The legacy header is refused on a keyed write | `test_a_keyed_write_refuses_the_legacy_retry_header` |
| Keyless writes still honour the legacy header | `test_a_keyless_write_may_still_use_the_legacy_header` |
| All record table counts unchanged after an invalid or unauthorized request | `test_a_refused_request_leaves_every_record_table_untouched` (unknown key, another caller's key, no session, legacy header) and `test_a_refused_request_on_an_empty_store_creates_nothing` |
| A keyed write never creates reference data | `test_a_keyed_write_never_creates_reference_data` |
| Startup is what seeds records | `test_application_startup_is_what_seeds_records` |

### Complete run after the fixes

| Check | Result |
| --- | --- |
| API tests | 452 run, 449 passed, 3 skipped (CI-only) |
| Product tests | 65 passed |
| `lint:web` (type check) | passed |
| `test:web` (unit, including the provider-boundary check) | 23 passed |
| `build:web` (production build) | passed |
| `test:e2e` (browser regression) | 107 passed |

33 tests were added for the reproductions: 14 routing, 11 reference-shape, 8 on the transaction
boundary, and the translator's untranslatable-action rule. No paid provider call was made. These
are Windows runs; the pull request's Linux CI is still the evidence that counts, and the branch is
not pushed.
