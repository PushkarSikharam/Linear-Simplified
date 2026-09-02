import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: false,
  async rewrites() {
    return [
      {
        source: "/api/agent/:path*",
        destination: "http://127.0.0.1:8001/api/:path*"
      }
    ];
  }
};

export default nextConfig;
