# Showcase web app

Next.js marketing site and font showcase. It consumes committed webfont assets; it does not build variable fonts.

## Commands

```bash
npm run dev
npm --workspace @static-to-variable/web run typecheck
npm --workspace @static-to-variable/web run build
```

The workspace has no Vitest files. Use typecheck during edits and the production build for route, metadata, and static-generation changes.

## Gotchas

- Font artifacts in `app/fonts`, `lib/og-assets`, and `public/fonts` are deliberate committed inputs. Regenerate them with the repository scripts; do not substitute local donor files.
- Keep font metadata in `lib/fonts.ts` and showcase configuration in `lib/config.ts` aligned with the committed artifacts.
- Do not move font-pipeline logic into this app; it belongs in `packages/variable-gen` and the CLI.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
