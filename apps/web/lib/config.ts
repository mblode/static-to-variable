/**
 * This app is served at blode.co/variable, proxied by the blode.co host app's
 * multi-zone rewrite. `basePath` is imported by next.config.ts so the prefix
 * lives in exactly one place.
 */
export const basePath = "/variable";

/**
 * `basePath` covers next/link and route handlers. It does NOT cover raw
 * `<a href>`, `<img src>`, `next/image` src, or client-side `fetch` to an API
 * route, so those go through this helper.
 */
export const asset = (path: string) => `${basePath}${path}`;

export const siteUrl = `https://blode.co${basePath}`;

export const siteName = "static-to-variable";
