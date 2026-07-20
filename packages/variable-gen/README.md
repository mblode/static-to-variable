# variable-gen

`variable-gen` is the config-driven static-to-variable font engine: it rebuilds independently-drawn static weights onto a shared, interpolation-compatible structure and builds the variable font. Everything is driven by a v3 `stv.config.json` (see `schemas/stv-config.schema.json`). See [the source layout](src/README.md) for the module map.

## Scope

The package can:

- bootstrap a minimal `.glyphs` source from a default-master donor (`bootstrap`)
- rebuild every master from its donors onto one shared point structure (`rebuild`), applying per-glyph strategies from the config
- normalize donor-inherited height defects (`normalize`)
- export UFO/designspace checkpoints with corrected axes (`designspace`)
- build variable TTFs with a freeze loop + per-weight fidelity check (`build`)
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

`rebuild` writes a reconstruction report (read by the `repair_build` promotion gate) at `packages/variable-gen/reports/reconstruction-report.json`.

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
- Treat Glyphs and FontLab as optional fallback review tools, not mandatory runtime dependencies.
