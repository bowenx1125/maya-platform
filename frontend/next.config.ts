import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // Next 16 writes its own AGENTS.md and CLAUDE.md into this package on every
  // dev start. The repository already has authoritative agent rules at its
  // root, so the generated copies are noise the boundary check would flag.
  agentRules: false,
  // The browser calls /api/v1 on its own origin, which the gateway serves in
  // Docker. Running `next dev` on its own there is no gateway, so every API
  // call would 404 against Next itself; in development the same paths are
  // forwarded to a locally running backend instead. `next start`, and so the
  // container image, is unaffected.
  async rewrites() {
    if (process.env.NODE_ENV === "production") return [];
    const target = process.env.MAYA_API_PROXY ?? "http://127.0.0.1:8000";
    return [
      { source: "/api/v1/:path*", destination: `${target}/api/v1/:path*` },
    ];
  },
};

export default nextConfig;
