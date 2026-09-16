# Milestone 3 Design: Product Definitions and Tenant Bindings

Status: **Step 3.0 approved by the stakeholder on 2026-09-16.** Step 3.1 may begin.
- Revision 1 was conditionally approved.
- Revision 2 added version pinning, the platform capability boundary, normalized relationships, the corrected sequence, and the separation between product definitions and tenant data.
- Revision 3 separates global definition lifecycle from tenant-specific binding state, and clarifies where knowledge lives.
- **Revision 4** (amends 3.1 before its commit) adopts the canonical SaaS hierarchy (section 3A):
  - Organization → Team → Product → that product's Pixel, on a shared multi-tenant platform
  - teams, definition ownership, and product resolution per request
  - visitor sessions scoped to one product
  - usage attributed to the owning team

## 1. Goal and non-goals

**Goal.** Pixel's core runs any product from a validated, versioned **Product Definition**,
activated for a tenant through a **Tenant Product Binding**:
- The current Linear-style demo becomes the first product.
- A second, invented billing product proves that core code has no product branches.
- Milestone 2's tenant boundaries stay intact throughout.

**Target test.** Deleting a product's package and its web adapter package removes that product
entirely. Core and every remaining product still build and pass, and no references to the
deleted product remain. This must hold for both products.

**Non-goals for Milestone 3:**
- billing or payments of any kind: no real money, cards, refunds, payment execution, Stripe or external billing APIs
- customer onboarding
- self-service editing of product definitions
- enterprise provisioning
- additional AI providers
- UI polish
- live (paid) evaluation
- knowledge ingestion, approval, website crawling, repository analysis or customer uploads
- a general schema-migration language
- arbitrary graph traversal

## 2. Current state: where the product is hard-coded

The product is defined implicitly in at least ten places, with overlapping lists that must be
kept in sync by hand.

### 2.1 Backend (`apps/api/app`)

| Module | Hard-coded product knowledge | Target home |
| --- | --- | --- |
| `schemas.py` | `AllowedActionType`, a `Literal` of 18 Linear action names | Definition actions over the platform capability vocabulary |
| `product_config.py` | Product name, a second copy of the action list, document path, voice style | Definition identity, actions and knowledge topics |
| `workspace_config.py` | Static workspaces defined as "project IDs + issue project labels + team names" | Tenant scopes and scope anchors |
| `services/demo_data.py` | Issue loading; person-name matching; scope checks via `projectId` or issue label | Record store plus scope resolver |
| `services/product_data_store.py` | Five demo tables, seed rows, ID prefixes (`PIX`, `PRJ`, `CYC`), reference rules | Record store; seed package |
| `record_schemas.py` | Pydantic models for Issue, Project, Cycle and Member | Definition entities |
| `services/action_planner.py` | Keyword-to-action rules, default issue `LIN-142`, title, priority and project heuristics | Definition intents plus the generic router |
| `services/action_validator.py` | Per-action payload rules, `PIX-`/`LIN-` prefixes, enums | Generic action-contract validator |
| `services/intent_extractor.py` | Feature detection; role, tool and pain-point keywords; reason sentences | Definition intents and prospect signals |
| `services/language_normalizer.py` | Product vocabulary, typo corrections, negated terms | Definition vocabulary |
| `services/conversation_manager.py` | "All issues or all projects?" clarification; "what about" follow-up | Definition clarifications |
| `services/reasoning_policy.py` | Team-process and conversation-control phrases | Definition intents (mostly generic) |
| `services/retriever.py` | `FEATURE_KEYWORDS`; "week by week" cycles boost; one shared document folder | Definition knowledge topics; tenant knowledge store |
| `services/agent_reasoner.py` | Edith/Pixel persona; action hints; issue-shaped context | Prompt builder plus definition hints |
| `services/agent.py` (814 lines) | Denial sentences naming issue actions; issue targeting; team-count, capability, greeting and identity replies; CRM and email boundaries | Generic engine plus definition templates and guardrails |

**Already product-agnostic** and to be kept as-is:
- `auth.py`, apart from the demo users
- `tenancy.py`
- `session_manager.py`
- `usage_ledger.py`
- `provider_policy.py`
- `http_client.py`
- `speech_service.py`
- `speech_providers.py`

### 2.2 Web (`apps/web`)

| File | Hard-coded product knowledge |
| --- | --- |
| `app/page.tsx` (~4,000 lines) | Every screen: seven Linear views and four create panels. It also contains a **second decision engine**: `handleLocalDraftIntent` and about 50 helpers (~1,000 lines) that answer chat turns in the browser without the backend. |
| `lib/product-config.ts` | A third copy of the action list; navigation pages |
| `types/demo.ts` | Issue, Project, Cycle and Member types; the `DemoAction` union |
| `lib/action-executor.ts` | Page-per-action mapping; issue-specific execution |
| `lib/agent-api.ts` | Issue-specific validation of returned actions |
| `lib/demo-data.ts` | Browser copy of the seed data |

### 2.3 Consequences
- Adding a product means editing a dozen backend modules and most of the web app.
- The three action lists can drift apart.
- Browser-answered turns bypass backend guardrails, the usage ledger and conversation memory.
- Workspace scope is defined in Linear terms, which was the root of the Milestone 1 scope leak.

## 3A. Canonical SaaS model (revision 4)

**Language.**
- **Product and business language:** use *Organization*, *Team*, *Product* and *Pixel*.
- **Code:** `tenant_id` is the organization's ID.
- **Keep the layers apart:** projects, workspaces, accounts or customers are **records inside a product** (for example "Product Engineering" in the Linear demo). They are never Pixel organizations or teams.

**Logical tenancy:**
```text
Pixel SaaS platform
├── Organization A            (tenant_id)
│   ├── Team A                (team_id)
│   │   ├── Product A → Pixel A   (product_id + product binding)
│   │   └── Product B → Pixel B
│   └── Team B
│       └── Product C → Pixel C
└── Organization B
    └── Team X
        └── Product D → Pixel D
```
- **Isolated per product:** definition, knowledge, records, actions, sessions, settings and usage attribution. Pixel for Product A cannot see Product B, even inside the same organization.
- **One owning team:** in Milestone 3 a product has exactly one owning team. Shared ownership between teams is future work.

**Physical deployment is a separate concept.**
- **Default:** one shared multi-tenant deployment serves many organizations, with strict logical isolation on every request.
- **Enterprise option (later):** a dedicated deployment for one organization or division runs the same semantics.
- **Independent identities:** organization identity never derives from deployment identity, e.g. `deployment_id = pixel-prod-us` hosting `tenant_id = microsoft`. Deployment configuration names only the deployment.

**Request resolution.** A client naming a product is never trusted on its own. The backend resolves:
```text
authenticated principal → organization (from the token, never from the request body)
→ requested product → active product binding in that organization → active owning team
→ caller authorized for that product → published definition version → knowledge version
```
The session then pins:
- the organization, team and product
- the definition ID, version and checksum
- the knowledge version

A request for a different product in the same session is refused; another product means another session.

**Principals (two security domains):**

| Principal | Access |
| --- | --- |
| Organization admin | Every product in the organization |
| Team admin, team member | Products owned by their team |
| Visitor | Exactly one product, through a visitor session issued for that product. Only possible when the product binding allows visitors. A visitor is never an organization member and gets no other product, team or organization access. |

- **Minimal permissions only:** Milestone 3 implements just what is needed to prove these boundaries.
- **Not in Milestone 3:** an RBAC engine, permission UI, SSO, enterprise IAM, admin screens, billing, budget allocation or onboarding.

**Definition ownership.** Definitions are identified by `definition_id`, which is separate from an organization's `product_id`. Two ownership kinds only:
- **`platform_shared`:** a Pixel-provided template that any organization may bind.
- **`organization_private`:** owned by one organization. Only that organization's products may bind it, and it never crosses the organization boundary.

**Usage attribution.**
- Ledger rows record `tenant_id`, `team_id`, `product_id` and `deployment_id`.
- `team_id` is the owning team **at attempt time**, so history is unaffected if a product later moves to another team. Moving a product ends its live sessions.
- Budgets stay per organization and product in Milestone 3; team budget allocation is future work.

**Development bootstrap.** Synthetic demo organizations are declared by product packages in `products/<definition_id>/seed/demo_organization.json` and loaded only when `PIXEL_DEMO_SEEDS=true` is set explicitly. The setting defaults to off, so a production deployment that omits it creates no synthetic data. Core code names no product.

**Stronger proof for 3.7.** The Linear demo and the billing demo run as two teams' products inside **one** organization, on the same runtime, plus another organization. Tests prove both kinds of isolation: between organizations, and between products inside one organization.

## 3. Architecture overview

Six separate concerns, each with a clear owner:

| Concern | What it holds | Owned by | Lives in |
| --- | --- | --- | --- |
| **Product Definition** | Reusable product semantics: entities, fields, allowed values, views, actions, intents, clarifications, guardrails, response templates, knowledge topics, reasoning hints | The product (shareable across tenants) | `products/<product_id>/definition/v<N>.yaml`, immutable once published |
| **Product Adapter** | Product-specific web rendering only | The product | `apps/web/adapters/<product_id>/` |
| **Tenant Product Binding** | Which tenant runs which product and definition version; knowledge version; checksums; binding state; tenant settings from a closed list (such as branding) | The tenant | Database registry |
| **Tenant Records** | Business data (customers, invoices, issues, members) and their relationships | The tenant | `records`, `record_relationships` |
| **Tenant Knowledge** | Product documents a tenant's assistant may use, by knowledge version | The tenant | `knowledge_documents` |
| **Tenant Scope** | Named scopes (workspaces, accounts) and their anchor records | The tenant | `scopes`, `scope_anchors` |

**Hard rule:** a Product Definition never contains tenant business data.
- It *may* say: an entity `customer` exists, with a `status` field and these allowed values.
- It must *not* say: `Acme Corp`, `INV-104` or `Maya Chen`.
- Demo seed data (records, scopes and knowledge) lives in a separate **seed package**, `products/<product_id>/seed/`, which is loaded only into demo tenants.

**Ownership is tenant-specific; a product definition is not necessarily unique to one tenant.**
- Two tenants may bind the same definition while keeping separate data, knowledge, branding, permissions and usage policy.
- Tenant-specific overlays on a definition are future work, and would sit above the base definition.

**Two layers:**
```text
Reusable layer        Product Definition, Product Adapter
Tenant-owned layer    Tenant Binding, Tenant Records, Tenant Knowledge, Tenant Scope, Sessions
```

A binding effectively says: *tenant Acme, product Billing: use definition v3 (checksum ABC123)
and knowledge v7.* Sessions pin those exact values.

**Where knowledge lives.** Real tenant knowledge is always tenant-owned: tenant A may run
Billing with knowledge v4 while tenant B runs it with knowledge v9.
- A product package may carry only **synthetic test knowledge** for demos and tests (`test-knowledge/`).
- Deleting the package deletes those synthetic assets. Product source code is never where customer documents live.

**Directory layout:**
```text
products/
  linear_simplified/
    definition/v1.yaml     # Product Definition (immutable once published)
    seed/                  # synthetic demo records and scopes, loaded into demo tenants only
    test-knowledge/        # synthetic knowledge for demo tenants and tests
    tests/                 # product-specific API, evaluation and browser tests
  billing_demo/
    definition/v1.yaml
    seed/
    test-knowledge/
    tests/
apps/web/adapters/
  linear_simplified/       # product-specific rendering only
  billing_demo/
```

Core code knows only the definition contract, the adapter contract, the registry mechanisms and
the generic engine.

## 4. Product Definition contract

### 4.1 Identity and metadata
Identity is explicit in the file, not inferred from its path:

```yaml
definition:
  product_id: billing_demo
  version: 1
```

At load time, the loader checks that the file path, the file's own metadata and the registry
entry all agree, and that the content checksum matches the registry. Any mismatch rejects the
definition.

### 4.2 Sections

| Section | Purpose |
| --- | --- |
| `identity` | Default product display name, assistant name, persona text, `voice_style`, greeting |
| `vocabulary` | Terms, synonyms, typo corrections, negatable terms (literal strings only) |
| `entities` | Record types. Each has an ID strategy (prefix plus server allocation, or a stable slug) and title/summary fields. Fields are scalar (text, integer, enum, date, boolean) or reference fields (single or multiple, with a target entity). Bounds and required/editable/displayed flags are declared per field. |
| `people` | Which entity represents people, which reference fields assign people, and which fields names are matched on |
| `scope` | The **anchor entity**, plus a path from each entity to an anchor of at most two hops (section 7.3) |
| `views` | Navigation entries; each is a dashboard, list, detail or form, or a named adapter view. Views declare columns, filters, controls (named, highlightable elements) and available actions. |
| `actions` | Registry entries built on the platform capability vocabulary (section 5) |
| `intents` | Literal trigger terms and phrases, examples, target action, and parameter extraction (a person, a record ID, an enum value, or the currently selected record) |
| `clarifications` | Vague-request trigger terms and the question to ask; follow-up rules |
| `guardrails` | Out-of-scope topics (literal terms) and the refusal wording |
| `responses` | Plain-text templates using the fixed placeholder vocabulary |
| `knowledge_topics` | Topic → literal keywords, used for retrieval boosts |
| `prospect_signals` | Literal keyword lists for role, team size, current tool, goals and pain points |
| `reasoning` | Short product hints placed in the **product configuration** section of the prompt (section 5.3) |

**Platform views** belong to Pixel, not to a product, and are available to every product. An
example is `architecture`, which replaces today's `OPEN_SYSTEM_ARCHITECTURE`.

### 4.3 Abbreviated illustrations

**Linear demo:**
```yaml
definition: { product_id: linear_simplified, version: 1 }
entities:
  project: { id: { prefix: PRJ }, title: name,
             fields: { name: { type: text, required: true, max: 200 },
                       status: { type: enum, values: [Planned, Active, At risk, Completed] } } }
  member:  { id: { strategy: slug, from: name }, title: name,
             fields: { name: { type: text, required: true }, active: { type: boolean, default: true },
                       projects: { type: refs, target: project } } }
  issue:   { id: { prefix: PIX }, title: title,
             fields: { title: { type: text, required: true, min: 3, max: 120 },
                       priority: { type: enum, values: [Low, Medium, High] },
                       status: { type: enum, values: [Todo, In progress, Review, Done] },
                       assignee: { type: ref, target: member, required: true },
                       project: { type: ref, target: project, required: true } } }
people: { entity: member, assigned_by: [issue.assignee], match_on: [name] }
scope:  { anchor: project, paths: { project: self, issue: [project], member: [projects] } }
actions:
  open_issue:       { capability: OPEN_RECORD, entity: issue }
  create_issue:     { capability: CREATE_RECORD, entity: issue,
                      fields: [title, priority, assignee, project, status] }
  update_issue:     { capability: UPDATE_RECORD, entity: issue, fields: [assignee, priority, status] }
  issues_by_person: { capability: FILTER_RECORDS, entity: issue, by: assignee }
  show_cycles:      { capability: NAVIGATE_VIEW, view: cycles }
intents:
  - { action: show_cycles, terms: [cycle, sprint, planning, time-boxed] }
  - { action: issues_by_person, requires: [person], terms: ["all tickets", "everything for"] }
guardrails:
  - { topic: external_crm, terms: [salesforce], response: out_of_scope }
```

**Billing demo:**
```yaml
definition: { product_id: billing_demo, version: 1 }
entities: [account, customer, invoice, subscription, member]
scope:    { anchor: account,
            paths: { account: self, customer: [account],
                     invoice: [customer, account],        # two hops: the maximum
                     subscription: [customer, account], member: [accounts] } }
actions:  [overdue_invoices (FILTER_RECORDS), draft_invoice (CREATE_RECORD),
           change_plan (UPDATE_RECORD, confirm: true, sandbox only)]
```

Billing data is synthetic, and the product does not imitate any real billing vendor.

## 5. Security invariants

These are platform policy. A definition that violates any of them is rejected as a whole.
Validation treats every definition as **untrusted input**, even though definitions are
currently stored in Git and reviewed through pull requests.

### 5.1 Configuration describes permission; it never creates authority

```text
Product Definition  → declares actions using a platform capability
Pixel Core          → checks the capability is in the closed vocabulary and the parameters are safe
Registered adapter  → performs only its approved UI effect
```

- **Closed capability vocabulary,** defined in core code: `NAVIGATE_VIEW`, `OPEN_RECORD`, `FILTER_RECORDS`, `CREATE_RECORD`, `UPDATE_RECORD`, `HIGHLIGHT_CONTROL`.
  - Anything else (e.g. `RUN_COMMAND`, `READ_FILE`, `CALL_URL`, `EXECUTE_SQL`) rejects the definition at load time, so it never reaches an executor.
  - **There is no delete capability in Milestone 3.**
- **Code-owned adapter registry.** Definitions reference adapter views by key only. An unknown key rejects the definition.
- **Record mutations** (`CREATE_RECORD`, `UPDATE_RECORD`) always pass server-side schema, scope and permission checks in the record store, whatever the definition says.

### 5.2 Parameter safety
- **Declared keys only:** targets may only reference keys declared in the same definition (views, entities, fields, controls, actions) or platform views.
- **No free-form targets:** no URLs, file or route paths, CSS selectors, or DOM identifiers.
- **Plain-text responses:** templates are plain text; HTML is rejected. Placeholders come from a fixed platform list: `{product}`, `{assistant}`, `{scope}`, `{view}`, `{visitor}`, `{person}`, `{record_id}`, `{record_title}`, `{records}`, `{field}`, `{value}`, `{changes}`, `{count}`. Response keys also come from a fixed platform list.
- **Literal terms only:** intents, clarifications, vocabulary and guardrails contain no regular expressions or wildcards. Rules are expressed as `match` (every group must contain one of its terms), `exclude` and `exact`.
- **No unknown fields:** unknown fields anywhere reject the definition.
- **Bounded strings:** string lengths, list sizes and total definition size are limited.

### 5.3 Prompt boundaries
- **Platform instructions are fixed:** safety, scope, action and grounding rules are platform text and are never built from definition or tenant strings.
- **Product text is labelled as data:** definition-controlled strings (persona, hints, vocabulary, templates) and tenant data (records, knowledge) enter the prompt only inside a clearly delimited section labelled as product configuration or data. The platform instructions tell the model to treat that section as data, not policy.
- **Not a complete defence:** this does not solve prompt injection. The server-side action validation in 5.1 and 5.2 remains the enforcement layer, and the model's output is only ever a proposal.

### 5.4 Adapter boundary
Adapters **may**:
- render custom UI
- translate an already validated action into a UI effect

Adapters **may not**:
- route intents
- make product decisions or answer product questions
- bypass server validation
- authorize actions
- call providers or external services
- write records except through the generic records API

The browser handles presentation and trivial UI state. The backend makes every decision.

## 6. Registry, versions and sessions

### 6.1 Registry tables
- **Definition versions:** `product_definition_versions(product_id, version, checksum, state, validated_at, published_at, retired_at, revoked_at)`
- **Bindings:** `tenant_product_bindings(tenant_id, product_id, definition_version, definition_checksum, knowledge_version, knowledge_checksum, state, settings_json, updated_at)`
  - `settings_json` accepts only a closed list of tenant settings, e.g. display name, assistant name and greeting overrides. Anything else is rejected.
  - A binding may only point at a `published` definition version.
  - **Binding state** is tenant-specific: `active` or `disabled`.
    - A disabled binding starts no sessions, and its existing sessions end at their next request.
    - A binding can move to any other **published** version, including a rollback to an earlier one. The move affects only new sessions.

### 6.2 Lifecycle
- **States** are held in the registry, never in the immutable file: `draft`, `validated`, `published`, `retired`, `revoked`.
- **Allowed transitions:**
  - `draft → validated`
  - `validated → published`
  - `published → retired`
  - `published → revoked`
  - `retired → revoked`
  - **Anything else is rejected**, including `revoked → published` and any edit to published content.
- **Changing a published definition** means publishing a new version.
- **`retired`:** existing sessions may finish; new sessions may not start on it.
- **`revoked`:** sessions on that version are terminated at their next request, and must restart on the tenant's current published version.

**Global vs tenant-specific control:**

| Problem | Response | Affects |
| --- | --- | --- |
| The shared definition version is unsafe or invalid (e.g. a flaw in `billing:v3`) | Revoke the version | Every tenant's sessions on that version |
| One tenant's knowledge, data or configuration is wrong | Disable that tenant's binding, or move it to another published version | That tenant only |

A tenant-specific problem is never fixed by revoking a shared definition version.

### 6.3 Session pinning
- **Pinned values:** the existing `sessions` table gains `tenant_id`, `definition_version`, `definition_checksum`, `knowledge_version`, and `expires_at`.
- **At session start:** the engine resolves the tenant binding and pins those values.
- **On every turn:** the pinned definition and knowledge are used, and the checksum is verified. A revoked version, an expired session or a checksum mismatch ends the session.
- **Publishing a new version or knowledge set** affects only new sessions. A live session never changes vocabulary, actions, knowledge or guardrails mid-conversation.
- **Maximum session age** is platform configuration (for example `PIXEL_SESSION_MAX_AGE`), not something a product definition can set.

### 6.4 Compatibility between versions
When a new version is published, the validator compares it with the previous published version
and classifies the change as one of only two kinds:
- **Additive-compatible** (entity-level):
  - a new entity
  - a new optional field
  - a new enum value
  - a new optional reference field

  Changes outside `entities` are always compatible, because live sessions stay pinned to their version.
- **Breaking, requires migration:** any other entity change, such as removing or renaming a field, tightening a bound, changing a type, or making a field required.
  - Publishing is rejected unless a reviewed migration accompanies the change.
  - Publishing it ends all sessions on older versions.

There is deliberately no general schema-migration language: migrations are reviewed platform code.

## 7. Tenant data model

### 7.1 Records
`records(tenant_id, product_id, entity, record_id, data_json, revision, migration_origin, created_at, updated_at)`
- **Primary key:** `(tenant_id, product_id, entity, record_id)`.
- **`data_json`** holds scalar fields only. **References never live in `data_json`.**
- **`migration_origin`** is platform metadata, set only for rows a migration created.

### 7.2 Relationships: the only record of references
`record_relationships(tenant_id, product_id, source_entity, source_record_id, field_key, target_entity, target_record_id)`
- Single references have one row; multi-references have one row per target.
- Composite foreign keys point to `records` at both ends. Deleting a referenced target is blocked.
- `RecordStore` is the **only** write path. It writes scalars and relationships in one transaction, validated against the pinned definition.
- The API assembles a logical record (scalars plus references) on read.
- Every ownership query filters on `tenant_id`, `product_id`, `entity` and `record_id`.

Examples:
- `invoice.customer → customer:CUS-14`
- `issue.project → project:PRJ-102`
- `member.projects` → one row per project

### 7.3 Scopes
- `scopes(tenant_id, product_id, scope_id, name, description)`
- `scope_anchors(tenant_id, product_id, scope_id, anchor_entity, anchor_record_id)`, with foreign keys to `scopes` and `records`; the anchor entity must match the definition's `scope.anchor`.
- **Access grants** reference `scope_id`.
- **`ScopeResolver`** decides membership only by following relationship rows by record ID. It **never matches on names**; that was the Milestone 1 leak.
- **Path length:** at most two hops (record → related record → anchor). Arbitrary graph traversal would be a separate, later architecture decision.
- **No precomputed record-to-scope index** in Milestone 3.

### 7.4 Knowledge
- **Store:** `knowledge_documents(tenant_id, product_id, knowledge_version, doc_id, title, body, checksum)`.
- **Retrieval** only reads documents for the session's pinned tenant, product and knowledge version, boosted by the definition's `knowledge_topics`.
- **Seeding:** demo knowledge is loaded from the seed package.
- **Out of scope:** ingestion, approval workflows and uploads.

### 7.5 Migration of the current demo data
Following the Milestone 2 rule, the database is backed up first, the migration is rehearsed on a copy, row counts and relationships are compared, and rollback is verified.
1. **Members get stable IDs** before the generic migration.
2. **Names become references.** Issue assignees and member project lists become relationship rows.
3. **Unresolved names get a synthetic member.** "Sam Rivera", a historical assignee who is not a team member, becomes an inactive member record: `active: false`, `migration_origin` set. No other details are invented.
4. **Scopes become anchors.** `demo_workspace_scopes` becomes `scopes` plus `scope_anchors` (project anchors). The old issue-label list is dropped once every issue has a project reference.
5. **The five demo tables move** into `records` and `record_relationships` under the demo tenant.
6. **Old column names:** the `customer_id` → `tenant_id` rename is done only if these tables are touched anyway.

## 8. Core engine after extraction

| Generic component | Responsibility | Built from |
| --- | --- | --- |
| `DefinitionRegistry` | Load, validate (section 5), checksum and cache definitions; enforce lifecycle transitions and compatibility | New |
| `BindingResolver` | Resolve a tenant's binding; pin and verify sessions | New; `session_manager.py` |
| `Normalizer` | Normalize text from definition vocabulary | `language_normalizer.py` |
| `IntentRouter` | Deterministic routing from definition intents and clarifications; parameter extraction through entity matchers | `action_planner.py`, `intent_extractor.py`, `reasoning_policy.py`, `conversation_manager.py`, and the browser decision engine |
| `ActionContractValidator` | Check capability, parameter schema, target existence, scope and permission | `action_validator.py` |
| `RecordStore` + `ScopeResolver` | Sections 7.1–7.3 | `product_data_store.py`, `demo_data.py` |
| `KnowledgeRetriever` | Section 7.4 | `retriever.py` |
| `PromptBuilder` | Fixed platform instructions plus the delimited product and data section; keeps the Milestone 2 token limits | `agent_reasoner.py` |
| `ResponseComposer` | Build speech from plain-text templates, citing retrieved sources | Sentences in `agent.py` |
| `ConversationEngine` | Turn orchestration; unchanged turn, session and accounting semantics | `agent.py` |

The turn API keeps its shape. An action becomes `{capability, action_key, params}`, validated
against the pinned definition instead of a hard-coded `Literal`.

## 9. API and web

- **API:**
  - `GET /api/profile` returns the session's pinned definition in client-safe form (identity after tenant settings, entities, views, action contracts) plus tenant branding.
  - Generic `GET/POST/PUT /api/records/{entity}` replaces `/api/demo-data/*`.
  - `/api/turn` returns generic actions.
- **Web:**
  - A generic shell with navigation built from `views`.
  - Generic `ListView`, `DetailView`, `FormView` and `Dashboard` components.
  - A generic executor over the six capabilities.
  - An adapter registry that loads `apps/web/adapters/<product_id>/`.
  - `page.tsx` is split by responsibility, and the browser decision engine is removed.
- **Test IDs:** derived from definition keys (`nav-{view}`, `create-{entity}-button`). Where a current ID changes, the pull request maps old to new.

### 9.1 Temporary compatibility shims
Each shim has an owner, a removal step and test coverage, contains no decision logic, and must
be gone by the end of Milestone 3.

| Shim | Purpose | Owner | Introduced | Removed | Tests |
| --- | --- | --- | --- | --- | --- |
| `/api/demo-data/*` routes | Serve the current web app while it still uses Linear-shaped data | Backend | Exists today; reimplemented on the record store in 3.5 | 3.6 | Existing API and browser suites |
| Generic action → legacy Linear executor | Let the current web app execute backend-decided generic actions | Web | 3.3 | 3.6 | Unit tests for each action mapping; browser suite |

## 10. Milestone 3 sequence

Each step lands as its own pull request with green Linux CI. Sizing happens after 3.1.

| Step | Scope | Exit evidence |
| --- | --- | --- |
| **3.1 Contract** | Definition schema and validator (all of section 5); capability vocabulary; registry tables, lifecycle transitions, compatibility check; session pinning, revocation and maximum age; Linear definition v1 expressed without behaviour change; **golden baseline** covering current backend decisions **and** browser-local decisions; core purity check introduced with its initial allowlist | All existing suites green; golden baseline recorded; security tests from section 11 that apply to 3.1 passing |
| **3.2 Generic engine** | Normalizer, intent router, action-contract validator, prompt builder (with delimiting), response composer, all driven by the pinned definition | Golden backend decisions reproduced; purity allowlist shrinks |
| **3.3 One backend pipeline** | Browser decision behaviour moved into the definition's intents and clarifications; browser engine deleted; executor shim added | Golden browser decisions reproduced by the backend; no browser code chooses product actions or answers product questions |
| **3.4 Knowledge** | Tenant knowledge store; pinned knowledge version; seed package | Retrieval cannot cross tenant, product or knowledge version |
| **3.5 Records** | Record store, relationships, scopes and anchors; migration (section 7.5); generic records API; demo-data shim on the new store | Rehearsed migration with matching counts; isolation and scope tests green |
| **3.6 Web** | Generic shell and views; per-product adapter packages; both shims removed | Linear demo runs entirely from its definition and adapter package |
| **3.7 Second product** | Billing definition, adapter, seed and tests | Section 11 second-product criteria |
| **3.8 Frozen core** | One new billing workflow added through definition changes only; deletion tests for both products; purity allowlist empty; no shims left | Section 11 frozen-core and deletion criteria |

**Why this order:**
- The browser currently holds a second decision engine that bypasses guardrails, memory and accounting. "Browser presents, backend decides" is established in 3.3, before the data model is migrated in 3.5.
- Generalizing the engine first (3.2) lets the browser behaviour move over *as definition configuration*, not as more hard-coded core code.

## 11. Acceptance criteria and mandatory tests

**Regression**
- All existing API, unit and browser suites are green on Linux CI at every merged step.
- The golden baseline (backend and browser decisions) is reproduced, and any intentional difference is listed in the pull request.

**Security (mandatory)**
1. **Version pinning:** session A starts on v1; v2 is published; A stays on v1; a new session B starts on v2.
2. **Capability escalation:** a definition declaring an unsupported capability is rejected, and the capability never reaches an executor.
3. **Unsafe parameters:** definitions containing a URL, path, CSS selector, HTML template, regular expression or unknown field are rejected.
4. **Breaking change:** publishing a breaking entity change without a migration is rejected.
5. **Revocation:** revoking a version terminates its sessions at their next request, for every tenant bound to it.
5b. **Tenant-specific control:** disabling one tenant's binding, or moving it to another published version, affects only that tenant. Other tenants on the same version keep their sessions.
6. **Lifecycle:** invalid transitions such as `revoked → published`, and edits to published content, are rejected.
7. **Isolation:** two tenants and two products cannot see each other's definitions, bindings, records, relationships, scopes, knowledge or usage.
8. **Scope by ID:** scope decisions ignore same-named records (a regression test for Milestone 1).
9. **Prompt boundary:** definition and tenant strings appear only inside the delimited data section of the prompt.

**Product purity**
- The core purity check passes with an **empty** allowlist.
- **Deletion tests, one per product:**
  - (a) no static references to the deleted product remain in core or other products
  - (b) after deleting the product's package and adapter package, the remaining build and test suites stay green

**Second product**
- At least 10 browser scenarios covering navigation, clarification, creation, validation, persistence and denied actions.
- A 20-case conversation evaluation on fake providers:
  - at least 18 passing
  - **all** security-boundary cases passing
  - no unsupported factual claims
- Scope works with `account` as the anchor, using a two-hop path.

**Frozen core**
- After freezing core, one new billing workflow is added by changing only files in `products/billing_demo/` (and its adapter package, if needed). The diff touches no core file.

## 12. Risks

| Risk | Mitigation |
| --- | --- |
| The browser decision engine (~1,000 lines) encodes behaviour that no backend test covers | Captured in the 3.1 golden baseline before it moves |
| Over-general definition schema | Support only the capabilities, field types and intent matchers the two products need; extend only with evidence |
| Test churn hides regressions | Test IDs derived from definition keys; old-to-new mappings reviewed in PRs |
| Migration corrupts demo data | Backup, rehearsal, count and relationship comparison, verified rollback |
| The second product is secretly shaped like Linear | Different entities and a different scope anchor (`account`), with a two-hop path |
| Purity check becomes noisy | Limited to named core modules, with a reviewed and shrinking allowlist |
| Pinned sessions outlive a bad definition | Revocation plus maximum session age |

## 13. Carried-forward debt (unchanged)

- **Provider keys and voices** are deployment-wide. `voice_style` is product-owned; credentials stay deployment configuration.
- **Configuration file:** the API still reads `apps/web/.env.local`.
- **Old column names:** `customer_id` still holds tenant IDs; possibly addressed in 3.5.
- **Speech limits:** there is no per-session cap on speech.
- **Voice label:** "Microsoft Voice" overstates the active provider; addressed only through the generic shell in 3.6.

## 14. Stakeholder decisions recorded

| Item | Decision |
| --- | --- |
| Definition storage | Approved: versioned YAML in the repo plus a database registry and binding; lifecycle and checksums in the database |
| Generic record storage | Approved with normalized relationships as the only record of references |
| Web architecture | Approved: generic shell and views plus per-product adapter packages, with the section 5.4 boundary |
| Second product | Approved: invented billing software (account, customer, invoice, subscription, member); no real payments |
| Browser decision engine | Approved and required: all of it moves to the backend in 3.3 |
| Compatibility shims | Approved temporarily, with the section 9.1 owner, removal step and tests |
| Sequence | Revised to section 10; sizing after 3.1 |
| Tenancy | Belongs to bindings and tenant data, never to reusable definitions |
| SaaS hierarchy (revision 4) | Organization → Team → Product → Pixel; shared multi-tenant deployment by default, dedicated deployment optional later; organization identity independent of deployment |
| Definition ownership (revision 4) | `platform_shared` or `organization_private`; no team-private definitions in Milestone 3 |
| Multi-product runtime (revision 4) | Required in 3.1: product resolved and authorized per request, pinned per session |
| Lifecycle vs binding state | Definition-version lifecycle is global; binding state (active/disabled) and version moves are tenant-specific |
| Knowledge location | Tenant-owned at runtime; product packages carry only synthetic test knowledge |
| Step 3.0 | Approved 2026-09-16 |
