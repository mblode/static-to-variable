# glyph-forge-engine — agent instructions

Python renderer + manifest builder. Feeds SVGs and a BrokenGlyph JSON into `apps/studio`. Does not run at request time — build cache at dev/build, serve static.

## Run

```bash
# from repo root
npm run forge:build                             # orchestrates ingest + cache
# from this package
../../.venv/bin/python python/ingest_audit_reports.py
../../.venv/bin/python python/build_cache.py
../../.venv/bin/python python/render_glyph.py --family italic --glyph agrave.ss02 --weight 500 --source glide
```

Always run Python through `.venv/bin/python`. Never `python` — the user's global may not have `fontTools`.

## Entry points

| Script | Purpose |
| --- | --- |
| `python/shared.py` | Repo paths, weight mapping, `ITALIC_SEED`/`ROMAN_SEED` lists, font loaders |
| `python/render_glyph.py` | Single-glyph → SVG. CLI + importable `render_to_svg()` |
| `python/ingest_audit_reports.py` | Audit JSON + seed lists + triage manifest → `manifests/broken-glyphs.json` |
| `python/build_cache.py` | Bulk runner: walks the manifest × 8 weights × 2 sources |
| `python/score_glyph.py` | Per-cell void / irregularity / drift scorer |
| `python/build_scores.py` | Bulk scorer → `manifests/{cell,glyph}-scores.json` |
| `python/recommend_strategy.py` | Heuristic rules → `manifests/strategy-suggestions.json` |
| `python/solve_glyph.py` | Raster-space simulator for 3 strategies (`donor_copy`, `reference_fallback`, `weighted_fallback`); picks the one with best projected worst-case → `manifests/solver-results.json` |
| `python/apply_pending_triage.py` | Merges `pending-triage-edits.json` into variable-gen's `circular-triage.json` (dry-run safe) |

## Gotchas

- **Solver simulator is raster-space, not vector**: `solve_glyph.py` blends donor/glide rasters at pixel level. It does not produce real interpolated outlines — projections are void-only (no irregularity / drift). Fidelity is good enough to rank strategies; don't use projected scores as ground truth.
- **`weighted_fallback` needs independent nudge vs validation targets**: Glide masters are at wght 100/400/950; donor anchors are 250/400/950. We nudge Glide masters toward their matching donor anchor, then interpolate between nudged masters to reach the validation weight. Earlier bug: blending toward the same weight used as validation makes the simulation tautologically perfect. Always keep nudge-source and validation-target independent.
- **Donor paths can contain spaces** (e.g. `cabinet/Circular/Circular Italic/` in the gitignored donor drop-in). Use `pathlib.Path` in Python.
- **Instancing variable TTFs**: `fontTools.varLib.instancer.instantiateVariableFont()` returns a new `TTFont` — instance once per weight, reuse.
- **Glyph names with slashes**: the user writes `/agrave.ss02` — that slash is a `.glyphs` source convention, not part of the name. Strip leading `/` at ingest.
- **Cache is idempotent**: `build_cache.py` skips existing SVG files. Delete `public-cache/svg/` to force a full rebuild.
- **The OTF weight-class order is NOT the visual weight order**: Circular has Thin=250, Light=300, **Regular=400**, Book=450, Medium=500, Bold=700, Black=900, ExtraBlack=950. Regular is lighter than Book.

## Do-not

- Do not write to `packages/variable-gen/` from here. Read its reports; never touch its sources.
- Do not hardcode glyph lists inline in `ingest_audit_reports.py`. Edit `ITALIC_SEED` and `ROMAN_SEED` in `shared.py` so future reviewers see the canonical list in one place.
- Do not check `public-cache/svg/` into git. Treat it as build output.

## Manifest shape

`manifests/broken-glyphs.json`: `BrokenGlyph[]`, matching the `src/types.ts` `BrokenGlyph` type. Each entry:

```json
{
  "name": "agrave.ss02",
  "family": "italic",
  "features": ["ss02"],
  "sources": ["audit", "user_seed"],
  "auditVerdict": "high",
  "existingStrategy": "donor_copy",
  "notes": "…"
}
```

`auditVerdict` is derived from variable-gen's `severity_score`:

- 0 → `unknown` (glyph not in audit report)
- 1-49 → `low`
- 50-199 → `medium`
- 200-499 → `high`
- 500+ → `blocker`
- explicit `tracked` bucket if flagged in `reports/repair/tracked-residual-review.md`
