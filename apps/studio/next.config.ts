import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Type safety is enforced by `turbo typecheck` (tsc --noEmit) in CI, not here.
  typescript: { ignoreBuildErrors: true },
};

export default nextConfig;
