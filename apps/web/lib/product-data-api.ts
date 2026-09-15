import type {
  DemoCycle,
  DemoDataResponse,
  DemoIssue,
  DemoProject,
  DemoTeamMember
} from "@/types/demo";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL
  ?? (typeof window === "undefined" ? "http://127.0.0.1:8001/api" : "/api/agent");

// Which seeded demo identity the browser signs in as. Non-admin users only see their workspace.
const DEMO_USER_ID = process.env.NEXT_PUBLIC_PIXEL_DEMO_USER ?? "demo-admin";

/** A record write the server rejected. Its message is safe to show to the user. */
export class RecordSaveError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RecordSaveError";
  }
}

// --- Demo auth token management ---

let _authToken: string | null = null;
let _loginPromise: Promise<void> | null = null;

export function getAuthToken(): string | null {
  if (!_authToken && typeof window !== "undefined") {
    try {
      _authToken = window.sessionStorage?.getItem("demo_auth_token");
    } catch {
      // sessionStorage not accessible
    }
  }
  return _authToken;
}

export function setAuthToken(token: string | null): void {
  _authToken = token;
  if (typeof window !== "undefined") {
    try {
      if (token) {
        window.sessionStorage?.setItem("demo_auth_token", token);
      } else {
        window.sessionStorage?.removeItem("demo_auth_token");
      }
    } catch {
      // sessionStorage not accessible
    }
  }
}

export async function ensureDemoLogin(userId = DEMO_USER_ID): Promise<void> {
  if (getAuthToken()) return;
  if (_loginPromise) return _loginPromise;
  _loginPromise = (async () => {
    try {
      const response = await fetch(apiUrl("/auth/demo-login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId })
      });
      if (!response.ok) {
        throw new Error("Demo login failed. Is the backend running?");
      }
      const body = (await response.json()) as { token: string };
      setAuthToken(body.token);
    } finally {
      _loginPromise = null;
    }
  })();
  return _loginPromise;
}

/**
 * fetch with the current bearer token. A 401 means the API restarted or the token
 * expired, so sign in again once and retry; idempotency keys make retried writes safe.
 */
export async function authorizedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const send = () => fetch(url, {
    ...init,
    headers: { ...(init.headers as Record<string, string> | undefined), ...authHeaders() }
  });
  // Sign in before the first request, so calls made during startup are not rejected.
  if (!getAuthToken()) await ensureDemoLogin();
  const response = await send();
  if (response.status !== 401) return response;
  setAuthToken(null);
  await ensureDemoLogin();
  return send();
}

export function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// --- Data API ---

export async function loadDemoData(): Promise<DemoDataResponse> {
  const response = await authorizedFetch(apiUrl("/demo-data"), {
    cache: "no-store"
  });
  return parseJsonResponse<DemoDataResponse>(response);
}

export async function resetStoredDemoData(): Promise<DemoDataResponse> {
  const response = await authorizedFetch(apiUrl("/demo-data/reset"), {
    method: "POST"
  });
  return parseJsonResponse<DemoDataResponse>(response);
}

export async function saveStoredIssue(issue: DemoIssue, requestKey?: string): Promise<DemoIssue> {
  const response = await authorizedFetch(apiUrl("/demo-data/issues"), {
    method: "POST",
    headers: jsonHeaders(requestKey),
    body: JSON.stringify(issue)
  });
  return parseJsonResponse<DemoIssue>(response);
}

export async function updateStoredIssue(issue: DemoIssue): Promise<DemoIssue> {
  const response = await authorizedFetch(apiUrl(`/demo-data/issues/${encodeURIComponent(issue.id)}`), {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify(issue)
  });
  return parseJsonResponse<DemoIssue>(response);
}

export async function saveStoredProject(
  project: DemoProject,
  workspaceScopeId: string,
  requestKey?: string
): Promise<DemoProject> {
  const response = await authorizedFetch(
    apiUrl(`/demo-data/projects?workspace_scope_id=${encodeURIComponent(workspaceScopeId)}`),
    {
      method: "POST",
      headers: jsonHeaders(requestKey),
      body: JSON.stringify(project)
    }
  );
  return parseJsonResponse<DemoProject>(response);
}

export async function saveStoredCycle(cycle: DemoCycle, requestKey?: string): Promise<DemoCycle> {
  const response = await authorizedFetch(apiUrl("/demo-data/cycles"), {
    method: "POST",
    headers: jsonHeaders(requestKey),
    body: JSON.stringify(cycle)
  });
  return parseJsonResponse<DemoCycle>(response);
}

export async function saveStoredTeamMember(
  member: DemoTeamMember,
  workspaceScopeId: string,
  requestKey?: string
): Promise<DemoTeamMember> {
  const response = await authorizedFetch(
    apiUrl(`/demo-data/team-members?workspace_scope_id=${encodeURIComponent(workspaceScopeId)}`),
    {
      method: "POST",
      headers: jsonHeaders(requestKey),
      body: JSON.stringify(member)
    }
  );
  return parseJsonResponse<DemoTeamMember>(response);
}

function apiUrl(path: string): string {
  const normalizedBase = API_BASE_URL.replace(/\/$/, "");
  return `${normalizedBase}${path}`;
}

function jsonHeaders(requestKey?: string): Record<string, string> {
  return {
    "Content-Type": "application/json",
    ...(requestKey ? { "Idempotency-Key": requestKey } : {})
  };
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail
      : response.status === 422 ? "Check the required fields and dates, then try again."
      : "Could not save your changes. Your draft is still here; please try again.";
    throw new RecordSaveError(detail);
  }
  return response.json() as Promise<T>;
}
