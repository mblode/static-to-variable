import path from "node:path";

import type { NextConfig } from "next";

import { basePath, siteUrl } from "./lib/config";

const root = import.meta.dirname;

const isDev = process.env.NODE_ENV === "development";

/**
 * PostHog is reverse-proxied through r.blode.co, and posthog-js lazy-loads its
 * extension bundles from `api_host`, so the origin belongs in `script-src` as
 * well as `connect-src`.
 *
 * The fallback is the deployed proxy rather than "": this file is evaluated at
 * build time, and an env var that is only bound on production would otherwise
 * ship previews a CSP that silently blocks analytics.
 */
const posthogOrigin =
  process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://r.blode.co";

const contentSecurityPolicy = [
  "default-src 'self'",
  // 'unsafe-inline' is not optional: Next inlines the RSC flight payload as a
  // <script>. 'unsafe-eval' is dev-only, for the Turbopack HMR runtime.
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""} ${posthogOrigin}`,
  `connect-src 'self' ${posthogOrigin}`,
  "img-src 'self' data: blob:",
  "style-src 'self' 'unsafe-inline'",
  // blob: and data: so a font parsed or generated in the browser can be
  // registered through FontFace without tripping the policy. This app is the
  // marketing surface for a CLI pipeline today, but the demo it fronts is
  // exactly that shape.
  "font-src 'self' data: blob:",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'self'",
  "upgrade-insecure-requests",
].join("; ");

/**
 * blode.co deliberately skips zone paths in its own `headers()`, because two
 * Content-Security-Policy headers on one response are intersected by the
 * browser rather than overridden. So this zone owns its response headers.
 *
 * No `Cross-Origin-Resource-Policy`: `same-origin` would need a `cross-origin`
 * override on every OG route, and missing one kills a share card silently.
 * HSTS is already set at the edge.
 */
const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=()",
  },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  // Served at blode.co/static-to-variable via the blode.co host app's
  // multi-zone rewrite.
  assetPrefix: basePath,
  basePath,
  reactStrictMode: true,
  // Monorepo: pin the file-tracing root to the repo root so Vercel's build
  // doesn't mis-detect it.
  outputFileTracingRoot: path.join(root, "..", ".."),
  headers() {
    // Every matching rule applies in array order and a later one wins per
    // header key, so a catch-all must come first or it overwrites the
    // per-path rules after it.
    //
    // `/:path*` rather than `/(.*)`: `headers` sources are basePath-prefixed,
    // and `/static-to-variable/(.*)` does not match the bare
    // `/static-to-variable` the zone rewrite actually requests. The `*`
    // modifier makes the segment optional, so it covers the zone root as well
    // as everything under it.
    return Promise.resolve([
      {
        headers: securityHeaders,
        source: "/:path*",
      },
    ]);
  },
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
