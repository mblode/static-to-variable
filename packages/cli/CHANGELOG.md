# static-to-variable

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
