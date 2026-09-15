import type { NextConfig } from "next";

const agentApiBaseUrl = process.env.PIXEL_AGENT_API_BASE_URL ?? "http://127.0.0.1:8001/api";

const nextConfig: NextConfig = {
  distDir: process.env.PIXEL_TEST_BUILD === "1" ? ".next/e2e" : ".next",
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  devIndicators: false,
  async rewrites() {
    return [
      {
        source: "/api/agent/:path*",
        destination: `${agentApiBaseUrl.replace(/\/$/, "")}/:path*`
      }
    ];
  }
};

export default nextConfig;
