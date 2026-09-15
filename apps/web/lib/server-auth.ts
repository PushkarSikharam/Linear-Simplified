import { NextResponse } from "next/server";

const agentApiBaseUrl = (process.env.PIXEL_AGENT_API_BASE_URL ?? "http://127.0.0.1:8001/api").replace(/\/$/, "");

/**
 * Server-side guard for Next.js routes that spend provider credits.
 * Returns an error response unless the caller's bearer token is accepted by the Pixel API.
 */
export async function rejectUnauthenticated(req: Request): Promise<Response | null> {
  const authorization = req.headers.get("authorization");
  if (!authorization) {
    return NextResponse.json({ error: "Sign in required." }, { status: 401 });
  }

  try {
    const response = await fetch(`${agentApiBaseUrl}/auth/me`, {
      headers: { Authorization: authorization },
      cache: "no-store",
      signal: AbortSignal.timeout(5_000)
    });
    if (response.ok) return null;
  } catch {
    return NextResponse.json({ error: "Could not verify sign-in." }, { status: 503 });
  }
  return NextResponse.json({ error: "Sign in required." }, { status: 401 });
}
