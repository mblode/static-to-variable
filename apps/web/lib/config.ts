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

/**
 * The product, as it is written for a reader: title templates, breadcrumbs and
 * the JSON-LD `name`. The lowercase `static-to-variable` is the npm package and
 * the repo, and stays that way wherever the command is meant.
 */
export const productName = "Static to Variable";

/**
 * `og:site_name` is `Matthew Blode` on every blode.co path, zones included.
 * All 33 zones are one site, and the product is already in `og:title`, so this
 * is the only slot in the share card left to say who made the thing. See
 * blode-co/apps/web/.claude/knowledge/zone-conventions.md Rule 9.
 */
export const ogSiteName = "Matthew Blode";
