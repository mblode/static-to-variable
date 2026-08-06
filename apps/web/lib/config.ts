/**
 * This app is served at blode.co/static-to-variable, proxied by the blode.co
 * host app's multi-zone rewrite. `basePath` is imported by next.config.ts so
 * the prefix lives in exactly one place.
 */
export const basePath = "/static-to-variable";

/**
 * `basePath` covers next/link. It does NOT cover raw `<a href>`, `<img src>`
 * or `next/image` src, so those go through this helper.
 */
export const asset = (path: string) => `${basePath}${path}`;

export const siteUrl = `https://blode.co${basePath}`;

export const siteName = "static-to-variable";
