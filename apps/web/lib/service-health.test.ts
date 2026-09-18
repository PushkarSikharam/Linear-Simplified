import { describe, expect, it, vi } from "vitest";

import { checkAgentService } from "@/lib/service-health";

describe("agent service readiness", () => {
  it("accepts only an explicit healthy response", async () => {
    const request = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), { status: 200 })
    );

    await expect(checkAgentService(request)).resolves.toBe(true);
    expect(request).toHaveBeenCalledWith(expect.stringMatching(/\/api(?:\/agent)?\/health$/), {
      cache: "no-store",
      headers: { Accept: "application/json" }
    });
  });

  it("fails closed for errors, non-200 responses and malformed bodies", async () => {
    const networkError = vi.fn<typeof fetch>().mockRejectedValue(new Error("offline"));
    const unavailable = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 503 }));
    const malformed = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ status: "starting" }), { status: 200 })
    );

    await expect(checkAgentService(networkError)).resolves.toBe(false);
    await expect(checkAgentService(unavailable)).resolves.toBe(false);
    await expect(checkAgentService(malformed)).resolves.toBe(false);
  });
});
