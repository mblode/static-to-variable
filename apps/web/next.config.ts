import path from "node:path";

import type { NextConfig } from "next";

import { basePath, siteUrl } from "./lib/config";

const root = import.meta.dirname;

const nextConfig: NextConfig = {
  // Served at blode.co/static-to-variable via the blode.co host app's
  // multi-zone rewrite.
  assetPrefix: basePath,
  basePath,
  reactStrictMode: true,
  // Monorepo: pin the file-tracing root to the repo root so Vercel's build
  // doesn't mis-detect it.
  outputFileTracingRoot: path.join(root, "..", ".."),
  redirects() {
    return Promise.resolve([
      {
        basePath: false,
        destination: siteUrl,
        has: [{ type: "host" as const, value: "variable.blode.co" }],
        permanent: true,
        source: "/",
      },
      {
        // The old subdomain stays attached to this Vercel project, so the
        // permanent redirect to the canonical subdirectory lives here. It
        // cannot be a Cloudflare rule: every blode.co record is "DNS only", so
        // no traffic passes through Cloudflare's proxy.
        //
        // Built from `siteUrl` rather than written out, so the destination
        // cannot drift from `basePath` the next time the route is renamed.
        //
        // basePath: false so `source` matches the raw incoming path rather than
        // being prefixed to /static-to-variable/:path*.
        //
        // No loop: blode.co/static-to-variable proxies to
        // variable.zone.blode.co, whose host does not match, so that request
        // falls through to the app.
        basePath: false,
        destination: `${siteUrl}/:path*`,
        has: [{ type: "host" as const, value: "variable.blode.co" }],
        permanent: true,
        source: "/:path*",
      },
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
