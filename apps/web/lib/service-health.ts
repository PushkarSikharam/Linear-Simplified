import { apiUrl } from "@/lib/product-data-api";

export type AgentServiceStatus = "checking" | "ready" | "unavailable";

export async function checkAgentService(
  request: typeof fetch = fetch
): Promise<boolean> {
  try {
    const response = await request(apiUrl("/health"), {
      cache: "no-store",
      headers: { Accept: "application/json" }
    });
    if (!response.ok) return false;
    const body = await response.json() as { status?: unknown };
    return body.status === "ok";
  } catch {
    return false;
  }
}
