# Milestone 3.2, Slice 4b: Response Composer, Conversation Intents and the Knowledge Boundary

Status: **IMPLEMENTATION COMPLETE LOCALLY — nine review defects reproduced and fixed with regressions. Linux CI sign-off is pending. Nothing is wired into the runtime.**
Date: 2026-09-18. Plan: `docs/MILESTONE_3_STEP_3_2_PLAN.md` (revision 4.1), sections 7.2, 8.2 and 8.5.
Approved scope: the response composer as a lifecycle state machine, platform conversation intents, product-defined identity and capability replies, and the `KnowledgeLookup` honest fallback.

## What was built

| Component | File | Notes |
| --- | --- | --- |
| Response composer | `apps/api/app/engine/composer.py` | A `Stage` per lifecycle state, platform-owned lifecycle wording, and the rule that model speech may never describe an outcome. |
| Conversation intents | `apps/api/app/engine/conversation.py` | Generic detection of greetings, identity, capability questions and introductions; `offerable()` filters what may honestly be offered. |
| Knowledge boundary | `apps/api/app/engine/knowledge.py` | `KnowledgePassage`, the `KnowledgeLookup` protocol, `NoKnowledge` as the default, and `ground()`. |
| Product knowledge source | `products/linear_simplified/backend/knowledge.py` | Passages from this product's documents, built for one `KnowledgeContext`. |
| Registration | `installed_products.py`, `backend/package.py` | `knowledge_factory`, registered in code beside the lookup and translator factories. |
| Platform vocabulary | `apps/api/app/definitions/vocabulary.py` | New response key `knowledge_unavailable` (additive, like `clarify_person` in slice 2). |

## The wording rule

The platform owns lifecycle wording, and a test asserts that the *same action* produces four different
sentences across proposed, awaiting-confirmation, executed and cancelled — so the states cannot
quietly collapse into one another.

| Stage | Means | Example wording |
| --- | --- | --- |
| `proposed` | Nothing has happened | "I'll update CON-1: status to Closed." |
| `awaiting_confirmation` | The visitor has not agreed | "Should I update CON-1: status to Closed?" |
| `executed` | The write committed | "CON-1 is now updated: status to Closed." |
| `failed` | A rule rejected it | a platform-owned failure sentence, never a success |
| `cancelled` | The visitor declined | "Okay, I won't change anything." |
| `clarification` | A question is pending | the product's clarification template |
| `ungrounded` | Nothing installed can answer | a platform-owned knowledge-unavailable sentence |

**No stage accepts model-written speech.** `MODEL_SPEECH_STAGES` is empty, deliberately.
Executing one action proves that one action succeeded; it does not make any other sentence true,
and "I deleted every customer" passes every lexical check ever written. Retrieving a passage
proves a document exists; it does not make a sentence about that document accurate. Until a reply
can be bound to its citation and that binding evaluated, every word is composed deterministically.
Lifecycle text comes from platform-owned templates and verified results. Product templates remain
responsible for conversational identity, capability and clarification copy, where no execution
claim is being made.

**Every product-authored stage enforces a template allowlist.** `STAGE_TEMPLATES` is checked on
every product render. Lifecycle states do not render product-owned sentence bodies at all, so a
definition cannot disguise a failure as a success by placing completion language in an allowed key.

## The knowledge boundary

`KnowledgeLookup` mirrors `RecordLookup`: read-only, scope-bound at construction, `search` takes
no tenant, product or scope, and the implementation lives in the product package. Core states the
contract and imports nothing — a test reads the module's own import lines and fails on any
mention of a retriever, `products`, or `app.services`.

- **`NoKnowledge` is the default.** A deployment with nothing installed finds nothing, and the
  platform returns a fixed honest fallback rather than improvising.
- **An answer is grounded or it is not given.** No passages means a platform-owned response at a
  distinct `ungrounded` stage that is deliberately *not* a refusal: the request was fine, the
  deployment simply has no source for it.
- **Documents are untrusted content.** Plain-text snippets are quoted and explicitly attributed to
  their title rather than spoken as Edith's own claim. The reply also carries immutable source IDs.
  Markup and malformed passages are refused.
- **The boundary carries the caller.** `KnowledgeContext` holds tenant, product, definition
  version and checksum, knowledge version and scope, and is required at construction. Today's
  documents are static and shipped with a definition, so *this implementation* still reads by
  definition ID — but the shape is already right, so Milestone 3.4 changes the implementation
  rather than the boundary. It is also why dismantling today's assistant in slice 5 does not
  silently empty `retrieved_context`.
- **Malformed context fails closed.** Tenant, product and definition identifiers are validated;
  versions must be positive integers; the definition checksum must be a lowercase SHA-256 value;
  and scope must be non-empty plain text.

## Capability replies

An action is offered only when it passes four filters: declared by this product, expressible by
the installed adapter, permitted for this caller, and **reachable under the caller's current
scope**. The last one has teeth — with no visible contacts, opening, updating and reassigning are
all withheld, while creating is still offered, because creating is the one thing still possible on
an empty scope.

## Self-review findings, fixed before this report

A probe of my own work found five defects. Each has a regression test.

| # | Severity | Defect | Fix |
| --- | --- | --- | --- |
| 1 | **High** | **The completion-claim denylist was trivially evadable.** "The contact was closed.", "That is taken care of.", "Closed.", "Sorted." all passed as a *proposal*. A phrase list cannot be the guarantee against something that writes English. | Narrowed to two stages at the time, and then removed entirely by the stakeholder review below: no stage accepts model speech. |
| 2 | **High** | **A document that claimed completion was spoken verbatim.** A passage reading "Done. I have updated the cycle." became the answer. | Passages are checked like any other untrusted content; one that claims completion or is not plain text is never spoken. |
| 3 | **High** | **Ordinary sentences were read as introductions.** "call me back later" greeted the visitor as "Back Later"; "this is urgent" as "Urgent". | Those cues are gone, a stoplist rejects ordinary words, and a name must appear **capitalized in what the visitor actually typed**. |
| 4 | Medium | **Mutations were offered on an empty scope.** With no visible contacts, updating and reassigning were still advertised. | Only creating survives an empty scope; everything needing an existing record is withheld. |
| 5 | Medium | **Model speech had no length bound in the composer.** A 5000-character sentence passed through. | Capped independently of the parser. Now moot for this slice, since no stage uses model speech, but the cap stays for when one does. |

Verified safe rather than assumed: a field value containing `{assistant}` is **not** re-expanded,
because substitution runs once over the template and inserted text is never rescanned. There is a
test for it.

## Stakeholder review: nine defects, all fixed

| # | Severity | Reproduction | Fix |
| --- | --- | --- | --- |
| 1 | **Critical** | **Lifecycle templates could be crossed.** `failed(action, "record_updated")` produced "CON-1 is now updated" while the reply was marked `FAILED`. `STAGE_TEMPLATES` existed but was never enforced. | Every render checks the stage's allowlist and raises `TemplateNotAllowed`. A test walks every stage and asserts a forbidden key is refused; another asserts no non-executed stage may use completion wording. |
| 2 | **Critical** | **Executed model speech could claim unrelated actions.** Closing one contact let "I deleted every customer and emailed their data" through. | No stage accepts model speech. An executed write is worded from the committed result. |
| 3 | **Critical** | **"Grounded" answers need not be supported.** A cycles passage made "Salesforce exports every customer automatically" acceptable — presence of retrieval, not grounding. | `knowledge_answer` takes only a `Grounding`; there is no parameter through which a model sentence can arrive. A test asserts the signature. |
| 4 | **High** | **Capability filtering failed open.** Omitting `translatable` or `permitted` advertised every declared action. | Both are now required through one `CapabilityPolicy`, and `CapabilityPolicy.nothing()` is the safe default. Omitting it is a `TypeError`. |
| 5 | **High** | **Knowledge was not caller-scoped.** Retrieval was bound only to a definition ID, with no organization, product, version or scope. | A typed `KnowledgeContext` carries tenant, product, definition version and checksum, knowledge version and scope, and is required at construction. Today's static documents still read by definition ID — a property of the implementation, not the boundary. |
| 6 | Medium | **`Grounding` was shallowly frozen.** Mutating the list passed in changed whether an answer was grounded. | Converted to a tuple in `__post_init__`, with empty sources and snippets refused. |
| 7 | **Critical** | **An allowed product template could still lie about lifecycle state.** A valid definition could put deletion or success prose inside `record_create_proposed` or `action_failed`; key allowlisting did not make the sentence truthful. | Proposed, confirmation, executed, failed and cancelled wording is platform-owned. Product lifecycle sentence bodies are never rendered. |
| 8 | **High** | **A retrieved snippet was repeated without visible provenance.** A document could contain an execution claim and the visitor could reasonably hear it as Edith's own statement. | Knowledge is rendered as an explicit quotation attributed to its document title, and `Reply.sources` preserves the immutable source IDs. |
| 9 | **High** | **`KnowledgeContext` accepted malformed isolation metadata.** Whitespace identifiers, non-positive versions, malformed checksums and empty scope values could reach a product knowledge adapter. | Construction now validates every identity, version, checksum and scope field and fails before lookup. |

## Test results

| Suite | Result |
| --- | --- |
| Core API | **623 run: 620 passed, 3 skipped** (CI-only) |
| Product (Linear) | **82 passed** |
| Composer, conversation and knowledge | `apps/api/tests/test_engine_composer.py` — **67 passed** |
| Product package | `products/linear_simplified/tests/test_product_package.py` — **44 passed** |
| Web type check | **passed** |
| Web unit tests | **23 passed** |
| Production web build | **passed** |
| Browser regression | **107 passed** |

No paid provider call was made. Windows runs only; Linux CI is the evidence that counts.

## Notes for the review

1. **Linear v2 must declare conversational templates.** Lifecycle keys may remain in the
   definition for legacy parity, but the new composer does not trust their sentence bodies.
   `greeting_named` and other conversational keys still have to exist when their stages use them;
   the composer raises `MissingTemplate` rather than inventing product identity copy.
2. **Core owns safety-critical lifecycle copy, not product identity.** Product definitions cannot
   redefine what proposed, confirmed, executed, failed or cancelled means. Product-owned identity,
   capability and clarification wording remains separate from that platform guarantee.
3. **Nothing is wired.** A test walks every `app.*` module outside `app/engine/` and fails if any
   of them names the new modules.
4. **Not in this slice:** no provider call, no dispatch, no runtime path, and no knowledge
   indexing, versioning or ranking — those are Milestone 3.4.
