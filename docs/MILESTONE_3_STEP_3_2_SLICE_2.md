# Milestone 3.2, Slice 2: Normalizer, Intent Router and Conversation Memory

Status: **signed off by the stakeholder on 2026-09-17, after green Linux CI.** Comparison mode only: nothing in this slice is wired into the runtime. Reviewed and signed off together with slice 3; four routing defects found in these components during that review were fixed first, and are recorded with the CI evidence in `docs/MILESTONE_3_STEP_3_2_SLICE_3.md`.
Date: 2026-09-17. Plan: `docs/MILESTONE_3_STEP_3_2_PLAN.md` (revision 3.2).

## What was built

| Component | File | Notes |
| --- | --- | --- |
| Normalizer | `app/engine/normalizer.py` | Keeps the original message. Produces `full` (every word, spelling fixed) and `focused` (the clause after the last correction marker, with negated product terms removed). Short and common words are never "corrected". |
| Rule matching | `app/engine/rules.py` | Whole-word literal matching and the specificity score. |
| Mentions | `app/engine/mentions.py` | Names, record IDs, enum values and titles found in a message. English-only heuristics; everything found is checked through the scope-bound lookup. |
| Intent router | `app/engine/router.py` | Implements the plan's section 3 stages 1–7 and 9. The model stage (8) is not built yet, so it decides nothing. Returns proposals only. |
| Memory rules | `app/engine/memory.py` | Pending question with candidates, rejected candidates, singled-out candidate, target, partial fields and one repeat; pending confirmation; expiry after one turn. |
| Result types | `app/engine/routing.py` | `PROPOSE` and `CONFIRM` carry a *proposal*. Other result kinds: `CLARIFY`, `ANSWER`, `REFUSE` (always with a topic), `CANCELLED` and `FALLBACK`. Nothing is marked validated, authorized, dispatched or executed. |

**What changes memory:**
- Routing alone changes only pending questions and confirmations.
- Focus, last person, last view and a pending confirmation change only through `remember_accepted`, which the slice 3 validator will call.
- In this slice, tests and the comparison call it explicitly, marked as standing in for validation.

## How the review constraints are met

| Constraint | Evidence |
| --- | --- |
| 1. Normalization keeps safety context | Refusals run on the full message and on the focused one. Tests: "delete everything, actually show me the contacts", "show contacts instead of the invoice" and "not the invoice, just contacts" are all refused. The original message is kept. |
| 2. Router results are proposals | Result types carry `proposal`, and only a visitor's explicit yes sets `confirmed`. A test asserts that no result or proposal field can hold validation, authorization, dispatch or execution state. Another shows that without `remember_accepted`, no confirmation is ever stored. **Note:** on a yes, the router returns the stored proposal without re-resolving it; slice 3 re-validates before execution. |
| 3. Lookups are scoped first | The scope is fixed when the lookup is built, and the router can only call the five protocol methods, none of which takes a scope. A fenced test lookup fails if the router reaches for anything else. Behaviour tests show hidden people are never offered as candidates, hidden candidates are dropped before a correction decides, and hidden records cannot be targeted by ID or from memory. **Since slice 3:** the real product lookup exists and has its own scope tests in `products/linear_simplified/tests/test_product_package.py`. |
| 4. Concrete comparison notes | Each note records case, turn, message, expected result, actual result, reason (at least 60 characters; blanket phrases rejected) and one of four resolutions. The mapping tables are explicit, and unmapped actions, payload keys or replies fail. |
| 5. Memory across turns | Every golden conversation is replayed turn by turn with its own memory. Synthetic conversations cover asking, answering, ordinals, corrections, refusals during a question, expiry and confirmation. A test shows the same follow-up without history does not act. |
| 6. Accurate platform-check claim | The router tests only show that guardrails cannot grant access (removing every guardrail exposes nothing). Authorization, pinning and lifecycle stay proven by the existing integration tests, which are unchanged and still pass. |

## Test results

| Suite | Result |
| --- | --- |
| Core API | 348 run: 345 passed, 3 skipped (CI-only) — the totals at the time of this slice; see the slice 3 report for the current run |
| Product (Linear) | 38 passed — likewise |
| New engine tests | `test_engine_router.py` (routing order, normalization safety, clarification memory, corrections, confirmation, visibility, synthetic definitions); `test_engine_contracts.py` updated for proposals |
| Comparison | `test_router_comparison.py`: every recorded turn compared, every difference explained, notes validated |
| Production unchanged | No runtime module imports the engine. The backend golden test still compares today's engine with its recording. No golden recording or definition file changed. The dependency and purity checks pass. |

Browser tests and Linux CI were not run for this slice; nothing on the web or at runtime changed. The PR's CI will run them.

## Comparison report

63 recorded turns (55 conversations): **43 identical, 20 different**, all explained in `products/linear_simplified/tests/golden/router_comparison_notes.json`.

| Resolution | Count | Cases |
| --- | --- | --- |
| `security`: today's reply reveals that a person exists outside the caller's workspace | 4 | `update-outside-person`, `update-unknown-person`, `scope-outside-person`, `scope-platform-outside-person` |
| `reviewed_difference`: the router is right, and the golden change will be listed in slice 5 | 5 | `update-without-target` (asks instead of guessing); `create-open-and-assign` (no longer assigns an unnamed person); `member-add-unnamed` (uses v1's add-member rule); `guided-path` (uses v1's guided-path rule); `unknown-person-tickets` (says the person was not found) |
| `definition_v2`: v1's rules need changes, made in the new v2 | 6 | `assignment-workflow`, `member-add-named`, `github-explain`, `scope-broad-request`, `scope-platform-own-person`, `prospect-profile` |
| `engine`: platform work needed before slice 5 | 5 | `greeting`, `greeting-with-name`, `capabilities` (no reply-only rules); `person-follow-up` (no follow-up rule); `voice-question` (knowledge answers belong to the model and knowledge stage) |

## Self-review findings, fixed in this slice

A stakeholder-style review of the first build found six problems. All are fixed, each with a test that fails on the old behaviour.

| # | Problem | Fix |
| --- | --- | --- |
| 1 | **"No, the other one" was not understood.** Corrections only worked when the whole message was a correction phrase, so the exact phrasing from the review ("no, the other one") and "not that one please" just repeated the question. | Correction phrases are now recognised at the start of a reply and anywhere inside it. A reply can also reject a candidate by name ("not Ana Lopez"), and a reply that rejects and names ("no, Ana Reyes") selects the named one. A rejection that fits every candidate ("not Ana" among three Anas) selects and removes nothing. |
| 2 | **Answers to "what should I create?" were treated as new requests**, so "a ticket" opened the ticket list instead of continuing to create one. | A question now remembers the request that caused it, and a short answer is read together with it. "Create something new" → "a ticket" → "Noah" now proposes creating a ticket for Noah. "open all" → "issues" opens the issue list. |
| 3 | **Ordinary words were read as names**, so "Show tickets for today" answered "I could not find a ticket for today", and "I'm Priya" produced the name "I'm Priya". | A name that cannot be found must be capitalized, must not be the first word, must not be a contraction, and must not follow "about" (where the rest is a subject, not a name). |
| 4 | **The wrong question for two people.** Naming two people always asked the assignment question, even for a listing. | The question now follows the action: `clarify_assign` for changes, and a new platform key `clarify_person` for listings and openings. With no suitable question declared, the router falls back instead of acting on one of the people. |
| 5 | **Two tests proved nothing.** The "proposal only" test used an assertion that cannot fail, and the scope test only exercised the fixture. | Both replaced, as described in the constraints table. |
| 6 | **A recorded reply was misclassified.** Named greetings were compared as plain greetings. | The comparison distinguishes `greeting` from `greeting_named`. |

**Deliberate behaviour, now documented:** a refusal word anywhere in the message refuses the turn, even when it is negated ("don't delete anything, just show me the issues"). Refusing too often is the safe direction, and no action is proposed.

**Limit of the comparison:** the replay accepts every proposal as if the validator had approved it, so later turns in a conversation assume the earlier action succeeded. Some proposals would not survive slice 3 validation (a create with no priority, project or status), so those conversations are optimistic until slice 5.

## Defects found after this report was written

A later review round reproduced four defects in this slice's components. They are fixed, each with
a regression test, and described in full in the slice 3 report:

| Defect | Component |
| --- | --- |
| A correction did not decide which record an action targeted, and an unavailable named record fell back to the remembered one | `router.py`, `normalizer.py` |
| An ambiguous ordinal answer ("first or second") selected the first candidate | `router.py` |
| An exact clarification lost to a grouped intent | `router.py` |
| A scalar reference field accepted an empty list and multiple values | `validator.py` (slice 3, but the same contract) |

The constraints table above still holds; it was simply not sufficient evidence on its own.

## Findings that need decisions

1. **v1 was written for first-match routing.** Its own comment says "Evaluated in order; the first matching intent wins." The approved plan ranks by specificity and never uses file order. v1 stays untouched, and v2 must be written and tested for specificity. Four of the `definition_v2` differences come from this (`github-explain`, `prospect-profile`, `scope-platform-own-person` and `member-add-named`).
2. **Conversational replies have no home.** The contract requires every intent to name an action, so greetings, identity and capabilities cannot be declared. There are two options:
   - a platform stage for these reply keys, with no schema change;
   - a reviewed contract change that allows reply-only intents.

   Needs your decision before slice 5.
3. **Follow-ups.** "What about Noah" after a list needs a rule that reapplies the last person-based request from memory. It is proposed as router work before slice 5.
4. **Guardrail placement.** v1 lists `broad_scope_refused` as a clarification, so an intent match overrides it. v2 should move it to guardrails, where refusals run first and can only refuse.
5. **Create defaults.** Create proposals carry only what the visitor said (assignee, title). v1 requires priority, project and status. The slice 3 validator will reject such proposals unless v2 declares field defaults (the contract already supports `default`), or the proposal names the missing fields in a question.
6. **New platform reply key.** `clarify_person` ("Which person do you mean?") was added to the platform vocabulary as an additive change. Linear v1 does not declare it, so a request naming two people falls back today; v2 should declare it.
7. **Known limits of this slice:**
   - The mention heuristics are English-only.
   - A "singled-out" candidate is currently produced only by corrections, because replies that name one candidate arrive with the composer in slice 4. The three-candidate correction test therefore starts from prepared state; the other correction paths run through sequential turns.
   - The comparison checks outcome, parameters and the unknown-person reply, not full wording, which is slice 4.
