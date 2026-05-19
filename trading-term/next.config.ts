import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.72.160"],
  async rewrites() {
    return {
      afterFiles: [
        {
          source: "/api/backend/:path*",
          destination: "http://127.0.0.1:8080/:path*",
        },
      ],
    };
  },
};

export default nextConfig;
