# stv build service

Runs the static-to-variable font pipeline on the server. The Vercel-static
frontend (`apps/web`) uploads a set of static weights; a Node API route drops
them into a job dir and runs this service to produce a variable font.

## What it does

Given a job dir containing uploaded static fonts, the service:

1. `config_gen.py` — reads each font's weight (OS/2 `usWeightClass` + name
   table) and generates a validated v3 `stv.config.json` plus `donors/<id>.ttf`.
2. `runner.py` — runs the from-scratch pipeline against that config and emits
   NDJSON progress the API tails and re-emits to the browser as SSE:

   ```
   bootstrap → rebuild → normalize → build → release
   ```

   The output is a packaged variable TTF + WOFF2 under the config's release dir.

The pipeline itself lives in the `variable-gen` package (imported, never
reimplemented). `runner.py` runs as a subprocess so native crashes or a
non-converging `fontmake` run can be hard-killed without taking down the API.

## Runtime: Sandbox vs container

- **Primary — Vercel Sandbox.** An ephemeral microVM provisioned per request.
  It runs `setup.sh` to build the engine venv, exports `STV_FONTMAKE`, then runs
  the pipeline. See `setup.sh` for the contract.
- **Fallback — container.** `Dockerfile` bakes the same venv into an image.
  Build/run **linux/amd64 only** (see gotchas).

## Running locally

Provision the engine once (from the repo root), then run the pipeline against a
job dir. `setup.sh` prints the `export STV_FONTMAKE=...` line to stdout:

```bash
eval "$(./services/build/setup.sh /tmp/stv-venv)"   # sets STV_FONTMAKE
python services/build/runner.py <job_dir>
```

The job dir must already contain `stv.config.json` and `donors/<id>.ttf` (as
written by `config_gen.generate_config`). `runner.py` writes the pipeline's
chatty output to `<job_dir>/build.log` and keeps stdout as pure NDJSON.

During package development you can skip `setup.sh` and use the repo's own venv:
`uv run python services/build/runner.py <job_dir>` (build.py::`_fontmake` falls
back to the repo `.venv` when `STV_FONTMAKE` is unset).

## setup.sh contract

```
./services/build/setup.sh [venv_dir]
```

- Venv dir resolves from `$1`, then `$STV_VENV`, then `/tmp/stv-venv`.
- Idempotent: reuses an existing venv, reinstalls the engine.
- Prints `export STV_FONTMAKE=<venv>/bin/fontmake` to **stdout** (progress goes
  to stderr), so callers can `eval "$(...)"` it.

## Dependencies & gotchas

The engine pulls fonttools, glyphsLib, **fontmake**, ufoLib2, numpy, scipy,
Pillow, Brotli, zopfli, and **skia-pathops** (requires Python ≥ 3.11).

- **skia-pathops is amd64-only.** It ships manylinux (glibc) x86_64 wheels —
  no musl wheel (so no Alpine) and no reliable arm64. The container pins
  `python:3.11-slim-bookworm` on `linux/amd64`.
- **`STV_FONTMAKE` is load-bearing.** Job dirs have no local `.venv`, so
  `build.py::_fontmake` can't fall back to one. The caller (Sandbox, container,
  or local shell) must export `STV_FONTMAKE=<venv>/bin/fontmake` before running
  the pipeline. The container sets it via `ENV`; `setup.sh` prints it.
