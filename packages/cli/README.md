# static-to-variable

Turn separate font weight files into one variable font.

Got a font as thin, regular, and bold files? Point this at them and get back one file you can slide between. See it working first at [variable.blode.co](https://variable.blode.co): live demos built from Google Fonts that never had a variable version.

## Quick start

```bash
npm install -g static-to-variable
static-to-variable init    # creates ./stv.config.json
```

Open `stv.config.json` and change two things: the paths to your font files, and the weight each one is (100 for thin, 400 for regular, 900 for black). Then:

```bash
static-to-variable build
```

Your variable font is in `build/`. Needs [Node](https://nodejs.org) 24.11+, [Python](https://www.python.org) 3.11+, and [uv](https://docs.astral.sh/uv/); the bundled font engine sets itself up the first time you build. Run `static-to-variable doctor` to check your setup.

## Commands

```bash
static-to-variable init      # scaffold ./stv.config.json
static-to-variable build     # rebuild -> normalize -> build
static-to-variable release   # finalize + WOFF2
static-to-variable doctor    # environment readiness
static-to-variable --version
static-to-variable --help
```

`build` and `release` read `./stv.config.json` by default; pass `--config <path>` to use another. Inside a repo checkout, `list` / `run` / `step` / `status` drive the advanced QA pipeline.

## Conventions

- `build`, `release`, and `doctor` take `--json` for a machine-readable summary on stdout; human progress always goes to stderr, so piped stdout stays clean.
- Configs are validated against `schemas/stv-config.schema.json` before any engine work starts; violations name the offending path.
- Exit codes: `0` success, `1` failure, `2` usage error (bad flag, missing or invalid config), `3` environment error, `130` interrupted.
- Errors carry a stable `STV_*` code and a suggested fix; `NO_COLOR` is respected on both streams.

## Configuration

Everything font-specific lives in `stv.config.json` (schema v3): family metadata, axes and named instances, per-style donors and masters, vertical metrics, per-glyph repair strategies, and output paths. See [`schemas/stv-config.schema.json`](https://github.com/mblode/static-to-variable/blob/main/schemas/stv-config.schema.json) and the [`examples/glide/`](https://github.com/mblode/static-to-variable/tree/main/examples/glide) worked example.

## License

[MIT](https://github.com/mblode/static-to-variable/blob/main/LICENSE.md)
