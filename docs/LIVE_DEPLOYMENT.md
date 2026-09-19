# Pixel Live Deployment

The live application has two services. Vercel serves the Next.js interface. A long-running API
service runs FastAPI and owns authentication, records, conversation state, usage accounting and
paid-provider calls. The browser reaches the API only through the same-origin `/api/agent/*`
rewrite.

## API service

Deploy the repository with `Dockerfile.api`. `railway.json` configures the container and the
`/health` readiness check.

Attach one persistent volume at `/data`, then set:

```text
PIXEL_DB_PATH=/data/pixel-live.sqlite3
PIXEL_DEPLOYMENT_ID=live-demo
PIXEL_AUTH_SECRET=<long random value>
PIXEL_SYNTHETIC_DEMO=true
PIXEL_DEMO_SEEDS=true
PIXEL_DEMO_LOGIN_USERS=demo-visitor
PIXEL_DEMO_IDLE_RESET_MINUTES=20
PIXEL_SESSION_MAX_AGE_SECONDS=86400
```

Never set `PIXEL_DEMO_ADMIN_LOGIN` or `PIXEL_RATE_LIMITS=off` on a deployment. Both exist only for
isolated test harnesses.

Provider credentials and budgets belong only to the API service. Copy the paid-provider settings
from `.env.example`; never add them to Vercel or expose them as `NEXT_PUBLIC_*` variables.

Do not deploy this SQLite configuration without the mounted volume. Container-local storage is
temporary and would invalidate logins, usage history and saved demo records whenever the service
restarts.

### Readiness means a conversation can start

`GET /health` and `GET /api/health` return `200 {"status": "ok"}` only when every active product
can start a conversation. The check is the one a real turn uses: the bound definition version is
registered, published, and its file still matches the registered checksum. Otherwise they return
`503 {"status": "unhealthy", "reason": "sessions_cannot_start", "products": <count>}`. The public
body names no tenant, product or definition. The result is cached for 30 seconds.

Operators get the detail in two places: the server log line `session_start_unavailable` (logger
`pixel.readiness`), and the readiness command below. Because Railway only routes traffic to a
deployment whose health check passes, a deployment that could not start conversations no longer
goes live looking healthy.

This check exists because of the 2026-09-18 outage. The production database had registered the
Linear definition with a checksum over Windows (CRLF) line endings, while the Linux image carries
the same file with LF endings. Checksums are over exact bytes, so every new conversation failed
with `definition_invalid`, voice with it, while `/health` still said `ok`. `.gitattributes` now
pins product definition and adapter files to LF on every checkout.

### Operator commands

Run these from a shell in the API container (`/app`), or from the repository root locally:

```text
PYTHONPATH=apps/api python -m app.ops check-readiness
PYTHONPATH=apps/api python -m app.ops reset-demo-data
```

`check-readiness` prints every active product that cannot start a conversation and why, and exits
non-zero if there is one. `reset-demo-data` restores everyone's demo records to the seed. Neither
is reachable through the public API.

### The public demo identity

- The demo login signs in only seeded identities that are **not administrators**: never an
  organization admin, never a member with administration over the product's records. The rule is
  enforced by the API, not by which user ID the web app happens to send.
- `PIXEL_DEMO_LOGIN_USERS=demo-visitor` narrows the demo login to the one public identity.
- `demo-visitor` is an ordinary team member with record access to both demo workspaces.
- `POST /api/demo-data/reset` resets everyone's data, so it requires a record administrator. No
  public identity is one. The page's **Reset** button starts a fresh conversation for that visitor
  and reloads the data; it never resets shared data. Operators use `reset-demo-data` above.
- **Known limitation:** demo records are shared by every visitor. One visitor's change is visible
  to anyone using the demo at the same time. Per-visitor, disposable demo state is not built yet.
- **Interim remedy:** with `PIXEL_DEMO_IDLE_RESET_MINUTES=20`, a visitor who signs in after the
  demo was changed and then left unused for 20 minutes starts from the seed. The log line
  `demo_data_restored` (logger `pixel.demo`) records each restore. Unset or `0` turns it off.

### Abuse limits

Limits apply per client address and per authenticated identity. A refused request is not counted,
and the response is `429` with `Retry-After`.

| Route | Per client, per minute | Per identity, per minute |
| --- | --- | --- |
| Demo and visitor login | 30 | — |
| Conversation turn | 120 | 600 |
| Speech | 60 | 300 |
| Shared-record write | 30 | 120 |
| Global data reset | — | 5 |

- **The client address is best effort.** It is the first `X-Forwarded-For` entry. Anyone calling
  the API directly can forge it, which is why the identity limit exists: every public visitor
  shares `demo-visitor`, so the identity limit is a ceiling on the whole public demo.
- **Unverified assumption:** that the Vercel rewrite forwards the visitor's address. If it does
  not, every visitor shares one client bucket. Check it after each deployment (release smoke test
  below).
- **Limits are held in memory, per replica.** Run one API replica until a shared store exists.

### Spending

Every anonymous visitor can start paid provider calls until the deployment's server-side budget
is exhausted. The daily budgets in `.env.example` bound the cost, and the limits above bound the
rate. Concurrency limits and spending alerts are **not built yet**; until they are, this
deployment is a demo, not a production service.

### Backups: not in place

The SQLite database on the volume has no backups. Before any real pilot we need scheduled,
encrypted snapshots, a retention policy, copies outside this Railway volume, one documented
restore test, and monitoring of disk use and backup failures.

## Vercel web service

Set these variables for Production:

```text
PIXEL_AGENT_API_BASE_URL=https://<api-host>/api
NEXT_PUBLIC_API_BASE_URL=/api/agent
```

`PIXEL_AGENT_API_BASE_URL` is server-only. Production builds fail when it is missing, preventing a
deployment that silently rewrites API requests to localhost.

The web app signs in as `demo-visitor` unless `NEXT_PUBLIC_PIXEL_DEMO_USER` says otherwise. It is a
build-time value, so changing it needs a redeploy. It is a convenience, not a security control:
the API refuses administrators whatever the page sends.

The web interface checks readiness before login. When the API is unavailable, it disables chat,
guided prompts and voice and shows one retry control; it does not run browser-local demo behavior.
A `429` is reported as "please wait a moment", never as a lost connection.

## Release smoke test

Run the automated smoke test against the deployed web origin:

```text
PIXEL_LIVE_URL=https://linear-simplified-web.vercel.app node scripts/smoke-live.mjs
```

It fails unless: the API reports ready; `demo-visitor` signs in and the administrator cannot;
records load; "Show sprint planning" completes with `OPEN_CYCLES`; "Open Salesforce" is refused for
the guardrail's own reason, in the same conversation; and the visitor cannot reset shared data.
CI runs the same script against the freshly built container (`PIXEL_SMOKE_API_URL`).
`PIXEL_SMOKE_SPEECH=true` adds one paid speech call and needs explicit spending approval.

Then check by hand:

1. Load the dashboard with no service warning.
2. Show sprint planning, open Maya's ticket, and ask to open Salesforce (refused).
3. Assign Maya's ticket to Noah and reload: the assignment persists. It is shared demo data, so
   reset it afterwards with `reset-demo-data`.
4. Create a ticket for an unknown teammate and verify the Teams handoff.
5. Press **Reset**: the conversation restarts and the data is unchanged.
6. Rate limits: from one network, the 31st demo login within a minute returns `429`. From a
   different network straight afterwards, a login succeeds. If it does not, the proxy is not
   forwarding client addresses and every visitor shares one limit.
7. Enable voice and speak one turn (paid: needs approval), or confirm the browser-voice fallback.
8. Restart the API service and verify the saved data remains.

## Recovery: conversations cannot start

Symptoms: `/health` returns `503`, and the chat answers "This product is not available right now."

1. Run `check-readiness` in the API container and read the `reason`.
2. `definition_invalid` means the registered checksum does not match the file the image carries.
   Published definitions are immutable, so the registered row is never rewritten. For the
   synthetic demo, point `PIXEL_DB_PATH` at a new file (for example `/data/pixel-live-2.sqlite3`)
   and redeploy: the seed registers the image's own bytes. The old file stays on the volume as a
   rollback until it is deleted.
3. Anything else (`definition_revoked`, `definition_retired`, a missing binding) is a lifecycle
   decision; fix the binding or the definition's state rather than the database file.

Changing `PIXEL_DB_PATH` or `PIXEL_AUTH_SECRET` signs every visitor out; the web app signs them in
again automatically.
