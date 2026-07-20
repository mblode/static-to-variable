# Source layout

Implementation modules for `variable-gen`, the config-driven build engine the CLI orchestrates.

## Modules

- `variable_gen.config` — load and validate the v3 `stv.config.json`.
- `variable_gen.bootstrap` — synthesize a minimal `.glyphs` source from a style's default donor.
- `variable_gen.rebuild` — rebuild each style's masters from its donors onto a shared, interpolation-compatible structure.
- `variable_gen.reconstruct_compatible` — the per-glyph outline reconstruction engine.
- `variable_gen.normalize` — normalize donor-inherited glyph height defects.
- `variable_gen.designspace` — export UFOs and a corrected `.designspace`.
- `variable_gen.build` — build the variable font(s) with fontmake and run the per-weight fidelity check.
- `variable_gen.release` — finalize metadata and emit release TTF + WOFF2.
- `variable_gen.split` — split a variable font back into static weights.
- `variable_gen.audit_support` — geometry metrics and interpolation checks used by the audit gate.
- `variable_gen.pipeline` — summarize stage artifacts and promotion gates.
- `variable_gen.outlines` / `variable_gen.common` — shared outline and path/hashing/JSON helpers.
- `variable_gen.cli` — package CLI for the pipeline commands (`rebuild`, `build`, `release`, ...) plus `pipeline-status` and `split`.
