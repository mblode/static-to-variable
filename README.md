# static-to-variable

Convert a family of static fonts into a single variable font. You point it at your static weights (and styles) with a small `stv.config.json`, and it rebuilds interpolation-compatible masters, normalizes them, builds the variable font with [fontmake](https://github.com/googlefonts/fontmake), checks per-weight fidelity, and finalizes the OpenType name/`STAT`/`fvar` metadata.

It handles the hard case: **independent static cuts that don't interpolate** (different contour counts, point structure, or start points across weights). A config-driven repair engine reconciles them to a shared structure, with per-glyph strategies for the ones that need special handling.

## How it works

A TypeScript CLI orchestrates a Python engine (fontTools / glyphsLib / fontmake):

```
static fonts (donors)  ─▶  rebuild  ─▶  normalize  ─▶  build (fontmake)  ─▶  variable font
        stv.config.json drives every step
```

## Requirements

- **Node** ≥ 24.11
- **Python** ≥ 3.11
- **[uv](https://docs.astral.sh/uv/)** — provisions the Python environment

## Quick start

```bash
git clone https://github.com/mblode/static-to-variable.git
cd static-to-variable
npm install            # TS deps + git hooks
npm run setup:python   # uv sync — provisions the Python engine

# Scaffold a config, then edit it to point at your static fonts:
npm run pipeline -- init      # writes ./stv.config.json

# Build the variable font(s):
npm run pipeline -- build --config stv.config.json
npm run pipeline -- release --config stv.config.json
```

Check your environment at any time:

```bash
npm run pipeline -- doctor
```

## Configuration

Everything font-specific lives in an `stv.config.json` (schema v3) — family metadata, axes and the named-instance ladder, per-style donors and masters, vertical metrics, per-glyph repair strategies, and output paths.

- Schema: [`schemas/stv-config.schema.json`](schemas/stv-config.schema.json)
- Worked example: [`examples/glide/`](examples/glide) (the Glide typeface; the licensed donor fonts themselves are not included)

## CLI commands

| Command | Purpose |
| --- | --- |
| `init` | Scaffold a starter `stv.config.json`. |
| `build` | Rebuild masters, normalize, and build the variable font(s). |
| `release` | Finalize metadata and emit release TTF + WOFF2. |
| `doctor` | Report environment readiness (node, python, uv, config). |
| `run` / `step` / `status` / `list` | Advanced QA pipeline: inventory, compatibility, repair, audit, and a promotion-gate report. |

Flags follow standard conventions: `--json` for machine output, non-zero exit on failure (`2` usage, `3` environment), progress on stderr, `NO_COLOR` respected.

## Repository layout

| Package | Purpose |
| --- | --- |
| [`packages/cli`](packages/cli) | The `static-to-variable` CLI (published to npm). |
| [`packages/variable-gen`](packages/variable-gen) | Python engine: config-driven rebuild/normalize/build/release + repair and audit. |
| [`packages/glyph-forge-engine`](packages/glyph-forge-engine) | Python renderer + QA-manifest builder feeding the studio. |
| [`apps/studio`](apps/studio) | Next.js visual-QA UI (grid, loupe, triage). A repo-only dev tool, not part of the npm package. |

## Fonts are not included

Donor fonts, `.glyphs` sources, generated fonts, and reports are gitignored — they are licensed inputs or build outputs, not source. Bring your own via the config.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE.md)
