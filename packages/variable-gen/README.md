# variable-gen

`variable-gen` is the config-driven static-to-variable font engine: it rebuilds independently-drawn static weights onto a shared, interpolation-compatible structure and builds the variable font. Everything is driven by a v3 `stv.config.json` (see `schemas/stv-config.schema.json`). See [the source layout](src/README.md) for the module map.

## Scope

The package can:

- bootstrap a minimal `.glyphs` source from a default-master donor (`bootstrap`)
- rebuild every master from its donors onto one shared point structure (`rebuild`), applying per-glyph strategies from the config
- refit temporary compatibility resamples into synchronized cubic spans while keeping real corners at shared point indices and smooth joins tangent-safe between masters
- compare viable split and bridge topologies on interpolated ink when donor contour counts change
- reconstruct detached accents independently when the base letter changes topology
- materialize implicit closing edges before compatibility reconstruction
- normalize donor-inherited height defects (`normalize`)
- export UFO/designspace checkpoints with corrected axes (`designspace`)
- build variable TTFs with a freeze loop + per-weight fidelity check (`build`)
- preserve explicitly marked, independently authored optical rows while making incomplete rows and unsafe interpolation hard build failures (`build`)
- finalize metadata and emit release TTF + WOFF2 (`release`)
- split a variable font back into static weights (`split`)
- aggregate the promotion gates into a status report (`pipeline-status`)
- audit all glyphs across exact masters and sampled in-between weights (`scripts/audit_variable_font.py`)

## Build a font

The usual path is the top-level CLI (`static-to-variable build`), which chains `rebuild -> normalize -> build`. To drive the engine directly:

```bash
.venv/bin/python -m variable_gen.cli rebuild --config examples/inter/stv.config.json --style all
.venv/bin/python -m variable_gen.cli build   --config examples/inter/stv.config.json --style all
.venv/bin/python -m variable_gen.cli release --config examples/inter/stv.config.json --style all
```

Run only one style by passing its config key (e.g. `--style roman`). Outputs land at the `output` paths declared in the config, and `release` stages TTF + WOFF2 under the config's `releaseDir`.

### Independently authored optical rows

The donor-derived `.glyphs` source remains disposable. A drawing pipeline that applies reviewed manual edits after `rebuild` can mark each genuinely authored master layer with this Glyphs user-data entry:

```python
layer.userData["com.mblode.stv.opticalAuthorship"] = f"manual:{drawing_sha256}"
```

The SHA-256 identifies the durable drawing record. Markers are per glyph and per master: the engine never infers authorship from coordinate differences. If one layer is marked at an optical size in a `wght` build, every configured weight master at that optical size must be marked. Missing Thin, Regular, or ExtraBlack drawings fail before compilation with the glyph and exact locations. Complete rows compile from their source geometry. If fontmake reports incompatibility or the existing midpoint-collapse gate fails, the build stops with a named error rather than replacing any authored layer with donor geometry. Donor fidelity checks remain unchanged, and each compiled authored master must retain its source advance to one unit and its rendered ink area within 2% after cubic-to-quadratic conversion.

`rebuild` writes a reconstruction report (read by the `repair_build` promotion gate) at `packages/variable-gen/reports/reconstruction-report.json`. `build` writes a layout report (read by the `layout` promotion gate) at `packages/variable-gen/reports/layout-report.json`.

## OpenType layout, kerning, and hinting

A `.glyphs` source carries outlines and metrics only, so fontmake's variable font has no layout at all. `build` restores it from the donors afterwards, at the best fidelity that compiles:

| tier | what varies with weight | when |
| --- | --- | --- |
| `variable` | kerning and mark attachment | the donors' whole layout tables merge cleanly |
| `variable-kern` | kerning | the merge refuses (donors disagree on `aalt` alternates, mark glyph sets, or per-weight kern coverage — none of which could have varied anyway) |
| `static` | nothing | the donors carry no kerning to vary |

`build` then applies the rasterizer baseline set by `output.hinting`: `smooth` (the default) adds a `gasp` table and a `prep` program with dropout control; `none` ships neither. Donor glyph instructions are not carried over — every outline is redrawn here, so they no longer describe the shapes.

The `layout` gate blocks promotion when a donor feature tag is missing from the output, kerning pairs are lost beyond a small pruning tolerance, a donor's GDEF is dropped, no layout attached at all, kerning is frozen while two or more donors carry it, or the hinting baseline is absent. It judges what a build produced, so a missing report — the staged pipeline stops at rebuild + audit and never calls `build` — is reported without blocking.

## Pipeline status

Step through or report on the pipeline with the workspace CLI:

```bash
npm run pipeline -- step
npm run pipeline -- list
npm run pipeline -- status
```

`pipeline-status` reads the current stage artifacts and writes `reports/pipeline-status.json` + `.md`. The full audit is diagnostic; the master rebuild is a blocking promotion gate.

## Audit

Run the all-glyph audit for every style:

```bash
.venv/bin/python packages/variable-gen/scripts/audit_variable_font.py --style all
```

A focused in-between audit that skips donor validation and only prioritizes interior span failures:

```bash
.venv/bin/python packages/variable-gen/scripts/audit_variable_font.py --style all --interpolation-only
```

What it does:

- exports the live `.glyphs` source to UFOs + designspace
- runs `fontTools.varLib.interpolatable` across all designspace sources
- builds a variable TTF
- samples interior weights inside each adjacent master span
- audits every glyph in every sampled instance for intersections, zero-ink outlines, and short segments
- validates exact master instances against the donor statics across all glyphs
- writes per-family JSON + Markdown reports plus an overview summary under `reports/audit/`

## Notes for implementation

- Prefer Python for the core engine. It relies on `fontTools`, `glyphsLib`, and UFO tooling.
- Keep the package headless by default.
- Treat Glyphs and FontLab as optional fallback review tools, not mandatory runtime dependencies. Opening a rebuilt `.glyphs` source in Glyphs 4 is useful for master browsing and live text preview after `build`.
