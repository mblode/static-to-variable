import path from "node:path";

import type { NextConfig } from "next";

const root = import.meta.dirname;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Monorepo: pin the file-tracing root to the repo root so Vercel's build
  // doesn't mis-detect it.
  outputFileTracingRoot: path.join(root, "..", ".."),
  // The /api/build route reads the Python engine + build service at runtime and
  // uploads them to the Vercel Sandbox, so trace them into the function bundle.
  outputFileTracingIncludes: {
    "/api/build": ["../../packages/variable-gen/**", "../../services/build/**"],
  },
  // Type safety is enforced by `turbo typecheck` (tsc --noEmit) in CI, not here.
  typescript: { ignoreBuildErrors: true },
  // The per-family pages live at /showcase/<id>; there is no index page (the
  // homepage is the hub), so send the bare /showcase to home instead of a 404.
  redirects() {
    return Promise.resolve([
      { source: "/showcase", destination: "/", permanent: false },
    ]);
  },
  // Define the `@/*` alias for Turbopack directly so it resolves without relying
  // on tsconfig paths.
  turbopack: {
    root: path.join(root, "..", ".."),
    resolveAlias: { "@/*": "./*" },
  },
};

export default nextConfig;
