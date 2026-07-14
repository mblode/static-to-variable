# Source layout

Implementation modules for `variable-gen`. See [the technical spec](../../../docs/variable-gen-technical-spec.md) for the broader design.

## Modules

- `variable_gen.manifest` — load and validate manifest v2 inputs.
- `variable_gen.discover` — inspect static donor fonts and emit inventory reports.
- `variable_gen.analyze` — run raw donor interpolatability analysis and emit compatibility reports.
- `variable_gen.pipeline` — summarize stage artifacts and promotion gates.
- `variable_gen.common` — shared path, hashing, family-selection, and JSON report helpers.
- `variable_gen.cli` — package CLI for `inventory`, `compatibility`, and `pipeline-status`.
