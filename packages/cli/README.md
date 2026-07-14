# static-to-variable

Convert a family of static fonts into a single variable font, guided by an `stv.config.json`. The CLI rebuilds interpolation-compatible masters, normalizes them, builds the variable font with fontmake, checks per-weight fidelity, and finalizes the OpenType metadata — orchestrating a Python engine (fontTools / glyphsLib / fontmake).

> Runs inside a `static-to-variable` checkout, where it locates the engine and the uv-managed Python environment. See the [repository README](https://github.com/mblode/static-to-variable#readme) for setup.

## Commands

```bash
static-to-variable init                         # scaffold ./stv.config.json
static-to-variable build   --config stv.config.json   # rebuild -> normalize -> build
static-to-variable release --config stv.config.json   # finalize + WOFF2
static-to-variable doctor                        # environment readiness
static-to-variable --version
static-to-variable --help
```

| Command | Purpose |
| --- | --- |
| `init` | Scaffold a starter `stv.config.json`. |
| `build` | Rebuild masters, normalize, and build the variable font(s). |
| `release` | Finalize metadata and emit release TTF + WOFF2. |
| `doctor` | Report environment readiness (node, python, uv, config). |
| `list` / `run` / `step` / `status` | Advanced QA pipeline: inventory, compatibility, repair, audit, and a promotion-gate report. |

## Conventions

- `--json` prints machine-readable output to stdout; progress goes to stderr.
- Exit codes: `0` success, `1` failure, `2` usage error, `3` environment error.
- Errors carry a stable `STV_*` code and a suggested fix; `NO_COLOR` is respected.

## Configuration

Everything font-specific lives in `stv.config.json` (schema v3): family metadata, axes and named instances, per-style donors and masters, vertical metrics, per-glyph repair strategies, and output paths. See [`schemas/stv-config.schema.json`](https://github.com/mblode/static-to-variable/blob/main/schemas/stv-config.schema.json) and the [`examples/glide/`](https://github.com/mblode/static-to-variable/tree/main/examples/glide) worked example.

## License

[MIT](https://github.com/mblode/static-to-variable/blob/main/LICENSE.md)
