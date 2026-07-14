# @static-to-variable/glyph-forge-engine

SVG renderer + broken-glyph manifest that backs the `@static-to-variable/studio` Next.js audit UI.

Read-only relationship with `@static-to-variable/variable-gen`: ingests its audit JSON reports, never writes to them.

## Run

```bash
npm run ingest   # variable-gen audit JSONs + seed lists → manifests/broken-glyphs.json
npm run cache    # bulk render missing (glyph × weight × source) SVGs to public-cache/svg/
npm run build    # ingest, force-refresh SVG cache, score, recommend, solve
npm run auto-stage            # stage every untriaged non-reconstruction decision
npm run reconstruction-stage  # stage only whole-glyph reconstruction decisions
```

Single-glyph render for debugging:

```bash
../../.venv/bin/python python/render_glyph.py \
  --family italic --glyph agrave.ss02 --weight 500 --source glide
```

## Outputs

- `manifests/broken-glyphs.json` — union of audit-flagged + user-seed glyphs with verdict + strategy cross-ref
- `manifests/glyph-scores.json` / `cell-scores.json` — visual QA scores for queue sorting and evidence cells
- `manifests/strategy-suggestions.json` / `solver-results.json` — heuristic and solver recommendations. Human staging is reserved for solver-flagged `requiresReconstruction` cases; ordinary bad outlines are handled by automatic strategies.
- `public-cache/svg/{family}/{glyph}/{weight}-{source}.svg` — per-cell outlines (8 donor weights × 2 sources)

`apps/studio`'s `scripts/sync-cache.ts` copies these plus pipeline status handoff reports into its `public/` at dev/build time. The `/interventions` route reads those synced artifacts and stages decisions through the existing pending-triage file. Pending edits can carry a strategy plus whitelisted manifest fields such as `repair_bucket`, `base_glyph`, `brace_weights`, `priority`, and deferral metadata; `npm run apply -- --dry-run` previews the merge before mutating `variable-gen`'s triage manifest.

`manual_review` now has a narrow meaning: the solver found a whole glyph whose raw Circular masters change structure enough that donor copy, weighted fallback, and reference fallback cannot produce an acceptable variable shape. Those glyphs are marked with `repair_bucket: "reconstruction_required"` and remain visible in the `/interventions` reconstruction queue.

## Weight mapping

Uses Circular donor's native 8 weights (read from each OTF's `OS/2.usWeightClass` at ingest time):

| Circular name | wght value |
| ------------- | ---------- |
| Thin          | 250        |
| Light         | 300        |
| Regular       | 400        |
| Book          | 450        |
| Medium        | 500        |
| Bold          | 700        |
| Black         | 900        |
| ExtraBlack    | 950        |

Glide is instanced at those same values for 1:1 apples-to-apples comparison.
