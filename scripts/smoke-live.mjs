const baseUrl = (process.env.PIXEL_LIVE_URL ?? "").replace(/\/$/, "");

if (!baseUrl.startsWith("https://")) {
  throw new Error("Set PIXEL_LIVE_URL to the deployed HTTPS web origin.");
}

async function request(path, init = {}) {
  const response = await fetch(`${baseUrl}/api/agent${path}`, init);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${init.method ?? "GET"} ${path} returned ${response.status}: ${body}`);
  }
  return response;
}

const health = await (await request("/health")).json();
if (health.status !== "ok") throw new Error("The API did not report ready.");

const login = await (await request("/auth/demo-login", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ user_id: "demo-admin" })
})).json();
const authorization = { Authorization: `Bearer ${login.token}` };

const data = await (await request("/demo-data", { headers: authorization })).json();
if (!Array.isArray(data.issues) || !Array.isArray(data.workspaceScopes)) {
  throw new Error("The demo-data response is incomplete.");
}

const sessionId = crypto.randomUUID();
const turn = await (await request("/turn", {
  method: "POST",
  headers: { ...authorization, "Content-Type": "application/json" },
  body: JSON.stringify({
    session_id: sessionId,
    turn_id: 1,
    product_id: "linear-demo",
    message: "Open Salesforce",
    input_mode: "text",
    current_page: "dashboard",
    workspace_scope_id: "workspace-product-eng"
  })
})).json();
if (turn.validated_action !== null || turn.status !== "denied") {
  throw new Error("The live guardrail did not deny the out-of-product action.");
}

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
  health: health.status,
  issues: data.issues.length,
  workspaces: data.workspaceScopes.length,
  guardrail: turn.status,
  speech
}, null, 2));
