# variable-gen

`variable-gen` is the config-driven static-to-variable font engine: it rebuilds independently-drawn static weights onto a shared, interpolation-compatible structure and builds the variable font. Everything is driven by a v3 `stv.config.json` (see `schemas/stv-config.schema.json`).

Docs:

- [First-principles static-to-variable pipeline](../../docs/static-to-variable-pipeline-first-principles.md)
- [Manifest v2 schema](../../docs/static-to-variable-manifest-schema.md)
- [Report contracts](../../docs/static-to-variable-report-contracts.md)

## Current scope

The package can:

- bootstrap a minimal `.glyphs` source from a default-master donor
- rebuild every master from its donors onto one shared point structure (`rebuild`), applying per-glyph strategies from the config
- normalize donor-inherited height defects (`normalize`)
- export UFO/designspace checkpoints with corrected axes (`designspace`)
- build variable TTFs with a freeze loop + per-weight fidelity check (`build`)
- finalize metadata and emit release TTF + WOFF2 (`release`)
- inspect a v2 static-donor manifest without mutating source files (`inventory`), run raw donor compatibility diagnostics (`compatibility`), and aggregate the promotion gates (`pipeline-status`)
- audit all glyphs across exact masters and sampled in-between weights (`scripts/audit_variable_font.py`) and validate tracked residual glyphs (`scripts/validate_residual_glyphs.py`)

## Primary entry point

Step through the full pipeline with the workspace CLI:

```bash
npm run pipeline -- step
npm run pipeline -- list
npm run pipeline -- status
```

The CLI delegates to the package scripts below. It does not reimplement repair logic or write glyph-forge data directly.

Run the static donor inventory foundation:

```bash
.venv/bin/python -m variable_gen.cli inventory \
  --manifest packages/variable-gen/manifests/circular-sources.v2.json \
  --output packages/variable-gen/reports/donor-inventory.json
```

Equivalent npm workspace command:

```bash
npm --workspace @static-to-variable/variable-gen run inventory
```

The inventory command is read-only. It starts from the raw Circular donor OTFs, records hashes, font metadata, glyph/cmap coverage, casefold collisions, and hard gate status.

Run the raw donor compatibility analyzer:

```bash
npm --workspace @static-to-variable/variable-gen run compatibility:raw
```

This emits `packages/variable-gen/reports/compatibility-raw.json` from the raw donor OTFs using `fontTools.varLib.interpolatable`. It is expected to fail the compatibility hard gate before repair; the report is the reproducible blocker map for the next phase.

Write the coherent pipeline status report:

```bash
npm --workspace @static-to-variable/variable-gen run pipeline:status
```

This reads the current stage artifacts and writes:

- `packages/variable-gen/reports/pipeline-status.json`
- `packages/variable-gen/reports/pipeline-status.md`

The status report is the promotion surface for the static-to-variable glyph pipeline. Raw donor compatibility and the full audit are diagnostic; inventory, repair/build, blocker residual validation, and glyph-forge visual QA are blocking promotion gates.

## Master rebuild

Rebuild every style's masters from its donors onto a shared, interpolation-compatible structure (config-driven):

```bash
.venv/bin/python -m variable_gen.cli rebuild --config examples/glide/stv.config.json --style all
```

Run only one style by passing its config key (e.g. `--style roman`).

Important outputs:

- Triage manifest (per-glyph strategies consumed by the residual gate):
  - `packages/variable-gen/manifests/circular-triage.json`
- Reconstruction report (read by the `repair_build` promotion gate):
  - `packages/variable-gen/reports/reconstruction-report.json`
- Built variable fonts (after `variable_gen.cli build`):
  - `packages/variable-gen/build/roman/glide-variable-vf.ttf`
  - `packages/variable-gen/build/italic/glide-variable-italic-vf.ttf`

## Comprehensive audit workflow

Run the all-glyph audit workflow for every style:

```bash
.venv/bin/python packages/variable-gen/scripts/audit_variable_font.py --style all
```

Run one style with denser in-between sampling:

```bash
.venv/bin/python packages/variable-gen/scripts/audit_variable_font.py --style italic --samples-per-span 9
```

Run a focused in-between audit that skips donor validation and only prioritizes interior span failures:

```bash
.venv/bin/python packages/variable-gen/scripts/audit_variable_font.py --style all --interpolation-only
```

What it does:

- exports the live `.glyphs` source to UFOs + designspace
- runs `fontTools.varLib.interpolatable` across all designspace sources
- builds a variable TTF
- samples interior weights inside each adjacent master span
- audits every glyph in every sampled instance for intersections, zero-ink outlines, and short segments
- validates exact master instances against the Circular donor statics across all glyphs
- writes family JSON + Markdown reports plus an overview summary

Interpolation-only mode:

- skips exact-master donor comparison entirely
- keeps the full sampled-weight audit artifacts
- separates interior span risk from endpoint-only risk
- ranks glyphs by `interpolatable` issues plus interior sampled failures only
- writes suffixed reports so the focused run does not overwrite the default audit

Audit outputs:

- Per-family JSON:
  - `packages/variable-gen/reports/audit/roman/roman-variable-audit.json`
  - `packages/variable-gen/reports/audit/italic/italic-variable-audit.json`
  - `packages/variable-gen/reports/audit/roman/roman-variable-audit-interpolation-only.json`
  - `packages/variable-gen/reports/audit/italic/italic-variable-audit-interpolation-only.json`
- Per-family Markdown:
  - `packages/variable-gen/reports/audit/roman/roman-variable-audit.md`
  - `packages/variable-gen/reports/audit/italic/italic-variable-audit.md`
  - `packages/variable-gen/reports/audit/roman/roman-variable-audit-interpolation-only.md`
  - `packages/variable-gen/reports/audit/italic/italic-variable-audit-interpolation-only.md`
- All-family overview:
  - `packages/variable-gen/reports/audit/audit-overview.md`
  - `packages/variable-gen/reports/audit/audit-run-summary.json`
  - `packages/variable-gen/reports/audit/audit-overview-interpolation-only.md`
  - `packages/variable-gen/reports/audit/audit-run-summary-interpolation-only.json`

## Notes for implementation

- Prefer Python for the core engine. The current repo already relies on `fontTools`, `glyphsLib`, and UFO tooling.
- Keep the package headless by default.
- Treat Glyphs and FontLab as optional fallback review tools, not mandatory runtime dependencies.
