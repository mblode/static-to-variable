import path from "node:path";

import type { NextConfig } from "next";

import { basePath } from "./lib/config";

const root = import.meta.dirname;

const nextConfig: NextConfig = {
  // Served at blode.co/variable via the blode.co host app's multi-zone rewrite.
  assetPrefix: basePath,
  basePath,
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
  /**
   * Keep the non-canonical hostnames out of the index.
   *
   * Every page here canonicalises to blode.co/variable, but the app also
   * answers on variable.zone.blode.co (the origin blode.co proxies to) and on
   * its *.vercel.app aliases. Those hostnames sit inside the
   * `sc-domain:blode.co` Search Console property, so left alone they are a
   * crawlable duplicate of the whole site.
   *
   * `x-forwarded-host` is the discriminator, not `host`: the multi-zone rewrite
   * proxies to the origin, so the incoming `host` is variable.zone.blode.co for
   * real blode.co traffic too. `x-forwarded-host` keeps the hostname the client
   * actually asked for, which is blode.co when proxied and the origin only on a
   * direct hit. Matching on `host` here would noindex the live site.
   */
  headers() {
    return Promise.resolve([
      {
        headers: [{ key: "X-Robots-Tag", value: "noindex" }],
        has: [
          {
            key: "x-forwarded-host",
            type: "header" as const,
            value: String.raw`.*\.zone\.blode\.co|.*\.vercel\.app`,
          },
        ],
        source: "/:path*",
      },
    ]);
  },
  redirects() {
    return Promise.resolve([
      {
        basePath: false,
        destination: "https://blode.co/variable",
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
        // basePath: false so `source` matches the raw incoming path rather than
        // being prefixed to /variable/:path*.
        //
        // No loop: blode.co/variable proxies to variable.zone.blode.co, whose
        // host does not match, so that request falls through to the app.
        basePath: false,
        destination: "https://blode.co/variable/:path*",
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
