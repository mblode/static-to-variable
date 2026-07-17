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
  // The repo pins `typescript@7.0.2` (the native TS preview), which Next 16
  // doesn't recognise — so it skips TS and never loads the tsconfig `paths`
  // alias, breaking `@/*` in CI (and silently crashing the Turbopack build on
  // Vercel). The `turbopack.resolveAlias` below restores `@/*` without TS.
  typescript: { ignoreBuildErrors: true },
  // Define the `@/*` alias for Turbopack directly (Next skips the tsconfig
  // `paths` under CI, which broke `@/*` and silently crashed the build).
  turbopack: {
    root: path.join(root, "..", ".."),
    resolveAlias: { "@/*": "./*" },
  },
  // Dev uses Turbopack; the production build runs on webpack (`next build
  // --webpack`) because the Turbopack production build silently crashes under
  // Vercel's monorepo wrapper. Mirror the `@/*` alias here so it resolves the
  // same way without relying on tsconfig paths (which Next skips under CI).
  webpack: (config) => {
    config.resolve ??= {};
    config.resolve.alias = { ...config.resolve.alias, "@": root };
    return config;
  },
};

export default nextConfig;
