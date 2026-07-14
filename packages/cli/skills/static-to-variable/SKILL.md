---
name: static-to-variable
description: Convert a family of static fonts into a variable font from an stv.config.json. Use when the user wants to build a variable font from static weights/styles, scaffold or edit an stv.config.json, or run/inspect the static-to-variable pipeline stages.
---

# static-to-variable

Convert a family of static fonts into a single variable font, driven by an `stv.config.json`. Runs inside a `static-to-variable` checkout (it locates the Python engine and uv-managed environment there).

## Core workflow

| Command | What it does |
| --- | --- |
| `static-to-variable init` | Scaffold a starter `stv.config.json` in the current directory |
| `static-to-variable build --config stv.config.json` | Rebuild masters → normalize → build the variable font(s) |
| `static-to-variable release --config stv.config.json` | Finalize metadata and emit release TTF + WOFF2 |
| `static-to-variable doctor` | Report environment readiness (node, python, uv, config) |

In a checkout these run via `npm run pipeline -- <command>`.

## Advanced QA pipeline

| Command | What it does |
| --- | --- |
| `static-to-variable list` | Show available pipeline stages and delegated commands |
| `static-to-variable run all --dry-run` | Preview the full default stage plan |
| `static-to-variable step` | Interactively step through the default stage plan |
| `static-to-variable status --read` | Print the current aggregate promotion-gate status |

## Conventions

- `--json` for machine output; progress on stderr.
- Exit codes: `0` success, `1` failure, `2` usage, `3` environment.
- Everything font-specific lives in `stv.config.json` (see `schemas/stv-config.schema.json` and `examples/glide/`).
