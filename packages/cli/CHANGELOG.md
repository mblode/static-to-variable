# static-to-variable

## 0.4.0

### Minor Changes

- d636805: Ship an open-source worked example and slim the pipeline. The reference config is now `examples/inter` (OFL Inter) instead of a proprietary donor set, and `init`/docs point there. The pipeline drops the internal visual-QA layer: `run`/`step`/`list`/`status` now cover the master rebuild, interpolation/full audits, and status report only, and `status` no longer takes `--handoff`/`--top`. Removed the opt-in AI redraw escape hatch; incompatible glyphs keep their deterministic frozen fallback.
- d636805: Add `static-to-variable split <font>`: the reverse of `build`. Point it at a variable font and it pins each step along the `wght` axis into standalone static weights, writing a TTF + WOFF2 per weight (each named so they install side by side). No config needed; other axes are pinned to their default. Supports `--out`, `--step`, and `--json`.

### Patch Changes

- 9da34aa: Stop common glyphs from freezing at one weight in generated variable fonts. The reconstruction step made outlines share a point count but not per-segment structure, so fontmake's cubic→quadratic (cu2qu) conversion then rejected glyphs like `e`, `U`, and `j` as incompatible and the build froze them to a single master (visible as letters stuck thin/heavy while their neighbours varied). Reconstruction now requires an identical per-segment `(op, point-count)` shape across masters and routes anything else through the uniform all-line resample, which is cu2qu-safe. On Kanit this cut build-frozen glyphs from ~37 to 1.
- 7bd6c34: Stop round glyphs (o, O, zero and their variants) freezing at one weight for TrueType donors that draw them as all-off-curve contours (e.g. Titillium Web). Such a contour is recorded with no `moveTo` and an implied on-curve endpoint, which the reconstruction's ring parser mis-read as a single point and discarded, forcing a freeze. It now expands the implied on-curve nodes before resampling, and adds a rotation-aligned uniform fallback for round contours whose start points drift across masters. On Titillium Web this cut frozen glyphs from ~39 to 5.

## 0.3.2

### Patch Changes

- 971235e: Point the package homepage at variable.blode.co.

## 0.3.1

### Patch Changes

- 014597d: Fix the default (Regular) named instance in `build` output: fontmake leaves its fvar subfamily name empty and its PostScript name truncated (e.g. `Family-`), so font menus showed a blank entry. The name repair that already ran at `release` time now runs on the `build` artifact too.

## 0.3.0

### Minor Changes

- deaf6f1: `init` now detects the font files in your folder, reads their real weights and names from each file, and writes an `stv.config.json` that builds without hand editing. Confirm the file list and the family name, then run `build`. Non-interactive shells (CI, agents) still get the starter template, and `build`/`release` docs now lean on the `./stv.config.json` default.

## 0.2.0

### Minor Changes

- d68571f: Harden the CLI and consolidate on the config-driven pipeline.

  - `stv.config.json` is now validated against the published JSON schema (`schemas/stv-config.schema.json`) before any engine work starts. Unknown keys and malformed fields fail fast with the offending path named.
  - Invalid configs now exit with code 2 (usage) instead of 1, matching missing configs; `release` validates the config the same way `build` does.
  - `build` and `release` support `--json` for a machine-readable summary.
  - `NO_COLOR` and piped output are respected everywhere; stage progress goes to stderr while reports and JSON stay on stdout.
  - `run --top` rejects 0; interrupted runs exit 130 consistently.
  - Error codes cleaned up: new `STV_CONFIG_EXISTS` for `init` collisions and `STV_STATUS_REPORT_MISSING` for absent pipeline reports; dead codes removed.

## 0.1.1

### Patch Changes

- fa218ba: Simplify the README to a short, customer-facing landing page.
