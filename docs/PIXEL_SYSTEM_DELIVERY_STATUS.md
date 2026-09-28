# Pixel System Delivery Status

This is an implementation inventory, not a claim that the SaaS product is finished.

## Connected Work

- Email-code sign-in endpoints: eight digits, ten-minute expiry, one use, five guesses,
  persistent per-address and deployment-wide delivery limits. Codes are HMAC digests at rest.
- Verified self-signup creates a private organization and its default team. Self-signup and
  email delivery are separately disabled by default. Existing accounts return to their own organization.
- Customer sign-in no longer calls synthetic login. Logout revokes the server session.
- The console loads the authenticated organization and real accessible products. It does not
  substitute sample products or simulated deployments when a request fails.
- Product import accepts an approved definition, validates its contract and requires ownership
  by the caller's organization. Source storage claims definition ownership atomically.
- The product workspace has a collapsible assistant on the left, fresh conversation IDs on
  product changes, backend-keyed writes, receipts, navigation and opt-in cloud audio playback.
- Browser-supported microphone input can submit a spoken turn and request its spoken reply.
  Microphone permission is requested only after a click. Unsupported browsers keep typed input.
- Product speech reads the pinned definition's voice style rather than a demo-only lookup.
- Approved plain-text/Markdown sources are versioned per product and definition checksum.
  Retrieval is bounded keyword matching, not embedding search or automatic deep understanding.
  Source publication starts a new console conversation; earlier sessions retain their version.
- Approved sources are product-wide: they must be suitable for everyone allowed into that
  product. They are not confidential record-scoped documents. The upload control says this.
- Knowledge capacity is bounded: sixteen documents, 128,000 characters and twenty publication
  increments per product. There is no pruning of historical sources while sessions may use them.
- People have names. Adding somebody asks for their first and last name, and open sign-in asks
  the person signing in for their own, because a deployment that sends nothing has no other
  moment to ask. Screens list colleagues by name, and the assistant answers "who is in my
  organization" with names rather than reading addresses aloud. An account with no name on
  record still shows its address, never a blank.
- Products say what they are for. Adding one asks for a sentence; it is stored on the binding
  and published as approved text on that product, so the assistant answers "what is this
  product for" from what a person wrote. Pixel's own assistant reads the same sentences live
  from the bindings rather than keeping a copy of them.
- Pixel's own records include the organization's teams, each with the number of people in it,
  and every person's team. All of it is read from the platform's tables at the moment of the
  question, so a count cannot drift from what the organization actually has.
- The assistant can point: asking where a person is added opens People and teams with the Add
  person control outlined and focused. The definition names the control; a screen claims that
  name, and a control nobody claims is simply not pointed at.
- One way into the guided demo, called "Visit demo" everywhere and accented in the navigation.
  It used to be offered twice under two names in the same sidebar.
- The overview carries counts of products, people and teams, read from the same endpoints the
  assistant answers from.
- Being signed out and failing to reach the server are answered differently. Only the server
  saying it does not know the caller offers a sign-in; anything else keeps the person where
  they are, says their session is intact, and offers to try again - and the session check is
  attempted twice before either conclusion.
- The separate guided demo remains at `/demo`.

## Required Configuration

Do not enable the email flow without all of these server-side settings:

- `PIXEL_AUTH_SECRET`: a stable random secret, not a browser environment variable.
- `PIXEL_SMTP_HOST`, `PIXEL_SMTP_USER`, `PIXEL_SMTP_PASSWORD`, `PIXEL_EMAIL_FROM`:
  an authenticated sender. Resend is delivered through its HTTPS API when the host is
  `smtp.resend.com`; other SMTP hosts use TLS on port 465. Verify delivery with the mailbox
  provider.
- `PIXEL_EMAIL_LOGIN_ENABLED=true` after configuration and delivery validation.
- `PIXEL_ENGINE_MODE=definition` after its cutover checks; customer sign-in refuses legacy mode.
- `PIXEL_SELF_SIGNUP_ENABLED=true` only when new verified users may create organizations.

### Open sign-in, for demonstrations only

`PIXEL_OPEN_SIGN_IN=true` lets an address in on its own, with nothing emailed to prove the
person typing holds it. It needs none of the settings above, and it exists for hosting that
cannot deliver mail. `GET /api/account/sign-in-mode` reports which way in a deployment uses, and
the sign-in page and the account panel follow it rather than stating one of them.

What it changes is only the proof. A first address still opens its own organization and default
team, two addresses are still two private workspaces, and the same address still returns to the
same workspace with its products, people and records. New workspaces are capped deployment-wide
per hour; a returning address is never held up by that cap.

What it costs: with it on, an address is a claim and not a fact, so whoever types an address
gets that workspace. Leave it off wherever anything real is kept.

No SMTP credentials have been provisioned, no real email has been sent in these tests, and no
payment account has been provisioned. Synthetic administrator access remains blocked.
The account currently uses the existing bearer-token transport and sessionStorage. A
same-origin HttpOnly-cookie session with CSRF protection remains an authentication hardening task.

## Not Complete

- Customer invitations, multi-organization switching, team/role administration and recovery.
- Schema-driven manual record forms, revision-conflict UX and relationship selection.
- Audio streaming, physical-device microphone verification and production voice-latency measurements.
- Automatic conversion of arbitrary source code or documents into an approved product definition.
- Semantic retrieval, document replacement/deletion, scoped document permissions and citation evaluation.
- Customer product lifecycle, deployment management, audit and usage dashboards.
- Billing, checkout, webhooks, entitlements and billing-provider configuration.
- Backup automation, off-volume encrypted retention, restore monitoring, shared rate-limit storage.
- Full accessibility review, production security review and a real customer onboarding pilot.

Unconnected management screens are not shown as functioning customer tools. The designed
prototype code remains in the repository, but its simulated data is not exposed as live data.
Do not call this list complete, production-ready, or a replacement for the remaining roadmap.
