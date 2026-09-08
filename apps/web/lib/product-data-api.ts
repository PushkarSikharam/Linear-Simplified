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

export async function loadDemoData(): Promise<DemoDataResponse> {
  const response = await fetch(apiUrl("/demo-data"), {
    cache: "no-store"
  });
  return parseJsonResponse<DemoDataResponse>(response);
}

export async function resetStoredDemoData(): Promise<DemoDataResponse> {
  const response = await fetch(apiUrl("/demo-data/reset"), {
    method: "POST"
  });
  return parseJsonResponse<DemoDataResponse>(response);
}

export async function saveStoredIssue(issue: DemoIssue): Promise<DemoIssue> {
  const response = await fetch(apiUrl("/demo-data/issues"), {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(issue)
  });
  return parseJsonResponse<DemoIssue>(response);
}

export async function updateStoredIssue(issue: DemoIssue): Promise<DemoIssue> {
  const response = await fetch(apiUrl(`/demo-data/issues/${encodeURIComponent(issue.id)}`), {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify(issue)
  });
  return parseJsonResponse<DemoIssue>(response);
}

export async function saveStoredProject(
  project: DemoProject,
  workspaceScopeId: string
): Promise<DemoProject> {
  const response = await fetch(
    apiUrl(`/demo-data/projects?workspace_scope_id=${encodeURIComponent(workspaceScopeId)}`),
    {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(project)
    }
  );
  return parseJsonResponse<DemoProject>(response);
}

export async function saveStoredCycle(cycle: DemoCycle): Promise<DemoCycle> {
  const response = await fetch(apiUrl("/demo-data/cycles"), {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(cycle)
  });
  return parseJsonResponse<DemoCycle>(response);
}

export async function saveStoredTeamMember(
  member: DemoTeamMember,
  workspaceScopeId: string
): Promise<DemoTeamMember> {
  const response = await fetch(
    apiUrl(`/demo-data/team-members?workspace_scope_id=${encodeURIComponent(workspaceScopeId)}`),
    {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(member)
    }
  );
  return parseJsonResponse<DemoTeamMember>(response);
}

function apiUrl(path: string): string {
  const normalizedBase = API_BASE_URL.replace(/\/$/, "");
  return `${normalizedBase}${path}`;
}

function jsonHeaders() {
  return {
    "Content-Type": "application/json"
  };
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`Demo data request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}
