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
PIXEL_DB_PATH=/data/demo_agent.sqlite3
PIXEL_DEPLOYMENT_ID=live-demo
PIXEL_AUTH_SECRET=<long random value>
PIXEL_SYNTHETIC_DEMO=true
PIXEL_DEMO_SEEDS=true
PIXEL_SESSION_MAX_AGE_SECONDS=86400
```

Provider credentials and budgets belong only to the API service. Copy the paid-provider settings
from `.env.example`; never add them to Vercel or expose them as `NEXT_PUBLIC_*` variables.

After deployment, both endpoints must succeed:

```text
GET https://<api-host>/health
GET https://<api-host>/api/health
```

Do not deploy this SQLite configuration without the mounted volume. Container-local storage is
temporary and would invalidate logins, usage history and saved demo records whenever the service
restarts.

## Vercel web service

Set these variables for Production:

```text
PIXEL_AGENT_API_BASE_URL=https://<api-host>/api
NEXT_PUBLIC_API_BASE_URL=/api/agent
NEXT_PUBLIC_PIXEL_DEMO_USER=demo-admin
```

`PIXEL_AGENT_API_BASE_URL` is server-only. Production builds fail when it is missing, preventing a
deployment that silently rewrites API requests to localhost.

Redeploy the web application, then verify:

```text
GET https://linear-simplified-web.vercel.app/api/agent/health
POST https://linear-simplified-web.vercel.app/api/agent/auth/demo-login
```

The web interface checks readiness before login. When the API is unavailable, it disables chat,
guided prompts and voice and shows one retry control; it does not run browser-local demo behavior.

## Release smoke path

Run this sequence against the deployed URL:

1. Load the dashboard with no service warning.
2. Show sprint planning.
3. Open Maya's ticket.
4. Assign it to Noah and reload the page to verify persistence.
5. Ask to open Salesforce and verify refusal.
6. Create a ticket for an unknown teammate and verify the Teams handoff.
7. Enable voice, speak one turn, and verify one spoken reply.
8. Restart the API service and verify the saved assignment remains.
