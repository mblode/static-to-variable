# Generated Manifests

This directory is populated by `npm run forge:build`.

The committed project starts without generated QA manifests so it can be cloned without Glide build artifacts. `apps/studio/scripts/sync-cache.ts` creates an empty `broken-glyphs.json` for fresh UI builds until the first pipeline run.
