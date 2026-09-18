// Live smoke test for a deployed Pixel. Makes no paid provider call unless PIXEL_SMOKE_SPEECH=true.
//
// It must be able to FAIL. The previous version asserted only that "Open Salesforce" was denied,
// which a backend refusing every conversation also satisfies — it passed while production could
// not start a single session. So every check below has a positive half: something that only a
// working deployment can produce.
//
// PIXEL_LIVE_URL      the deployed web origin; requests go through its /api/agent proxy.
// PIXEL_SMOKE_API_URL  instead, an API's own /api base, e.g. http://127.0.0.1:8011/api for the
//                      container CI builds. Plain HTTP is accepted only for this machine.

const liveUrl = (process.env.PIXEL_LIVE_URL ?? "").replace(/\/$/, "");
const directApiUrl = (process.env.PIXEL_SMOKE_API_URL ?? "").replace(/\/$/, "");
const demoUser = process.env.PIXEL_SMOKE_USER ?? "demo-visitor";

function apiBase() {
  if (directApiUrl) {
    const { protocol, hostname } = new URL(directApiUrl);
    if (protocol !== "https:" && hostname !== "127.0.0.1" && hostname !== "localhost") {
      throw new Error("PIXEL_SMOKE_API_URL must use HTTPS unless it points at this machine.");
    }
    return directApiUrl;
  }
  if (liveUrl.startsWith("https://")) return `${liveUrl}/api/agent`;
  throw new Error(
    "Set PIXEL_LIVE_URL to the deployed HTTPS web origin, or PIXEL_SMOKE_API_URL to an API's /api base."
  );
}

const base = apiBase();

async function call(path, init = {}) {
  return fetch(`${base}${path}`, init);
}

async function request(path, init = {}) {
  const response = await call(path, init);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${init.method ?? "GET"} ${path} returned ${response.status}: ${body}`);
  }
  return response;
}

function turnBody(sessionId, turnId, message) {
  return JSON.stringify({
    session_id: sessionId,
    turn_id: turnId,
    product_id: "linear-demo",
    message,
    input_mode: "text",
    current_page: "dashboard",
    workspace_scope_id: "workspace-product-eng"
  });
}

// 1. Ready, meaning a conversation can start — not merely that the database opens.
const health = await (await request("/health")).json();
if (health.status !== "ok") throw new Error("The API did not report ready.");

// 2. The public demo identity signs in, and the administrator cannot be minted.
const login = await (await request("/auth/demo-login", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ user_id: demoUser })
})).json();
const authorization = { Authorization: `Bearer ${login.token}` };

const adminAttempt = await call("/auth/demo-login", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ user_id: "demo-admin" })
});
if (adminAttempt.ok) {
  throw new Error("The public demo login issued an administrator token.");
}

// 3. Records load for the demo identity.
const data = await (await request("/demo-data", { headers: authorization })).json();
if (!Array.isArray(data.issues) || !Array.isArray(data.workspaceScopes) || data.issues.length === 0) {
  throw new Error("The demo-data response is incomplete.");
}

// 4. A conversation actually starts, and a real request is answered. Deterministic: no model call.
const sessionId = crypto.randomUUID();
const opened = await (await request("/turn", {
  method: "POST",
  headers: { ...authorization, "Content-Type": "application/json" },
  body: turnBody(sessionId, 1, "Show sprint planning")
})).json();
if (opened.status !== "completed" || opened.validated_action?.type !== "OPEN_CYCLES") {
  throw new Error(
    `A working request was not answered: status=${opened.status}, ` +
    `reason=${opened.intent_trace?.reason ?? "none"}`
  );
}

// 5. The guardrail refuses an out-of-product request — for the guardrail's reason, in the same
//    conversation, rather than because the backend refuses everything.
const refused = await (await request("/turn", {
  method: "POST",
  headers: { ...authorization, "Content-Type": "application/json" },
  body: turnBody(sessionId, 2, "Open Salesforce")
})).json();
const refusalReason = refused.intent_trace?.reason ?? "";
if (refused.status !== "denied" || refused.validated_action !== null
    || !refusalReason.includes("outside this product demo")) {
  throw new Error(`The guardrail did not refuse for its own reason: ${refusalReason || "none"}`);
}

// 6. A visitor cannot reset everyone's demo data.
const reset = await call("/demo-data/reset", { method: "POST", headers: authorization });
if (reset.status !== 403) {
  throw new Error(`A demo visitor reached the global reset (status ${reset.status}).`);
}

// 7. Optional, and paid: one short speech synthesis through the real provider.
let speech = "not requested";
if (process.env.PIXEL_SMOKE_SPEECH === "true") {
  const response = await request("/speech", {
    method: "POST",
    headers: { ...authorization, "Content-Type": "application/json" },
    body: JSON.stringify({
      text: "Pixel deployment check.",
      product_id: "linear-demo",
      session_id: sessionId
    })
  });
  speech = `${response.headers.get("x-tts-engine") ?? "unknown"} (${(await response.arrayBuffer()).byteLength} bytes)`;
}

console.log(JSON.stringify({
  target: base,
  health: health.status,
  demo_user: login.user_id,
  administrator_login: "refused",
  issues: data.issues.length,
  workspaces: data.workspaceScopes.length,
  conversation: `${opened.status} (${opened.validated_action.type})`,
  guardrail: refused.status,
  global_reset: "refused",
  speech
}, null, 2));
