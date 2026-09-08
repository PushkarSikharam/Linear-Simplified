import type { NextConfig } from "next";

const agentApiBaseUrl = process.env.PIXEL_AGENT_API_BASE_URL ?? "http://127.0.0.1:8001/api";

const nextConfig: NextConfig = {
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
