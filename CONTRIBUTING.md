# Contributing

Thanks for your interest in static-to-variable. This is a Node + Python monorepo: a TypeScript CLI (`packages/cli`, published to npm) that orchestrates a Python font engine (`packages/variable-gen`, `packages/glyph-forge-engine`), plus an optional Next.js studio (`apps/studio`) used only inside the repo.

## Prerequisites

- **Node** ≥ 24.11 (`.nvmrc`/`fnm` friendly)
- **Python** ≥ 3.11
- **[uv](https://docs.astral.sh/uv/)** — manages the Python env and lockfile

## Setup

```bash
npm install          # JS/TS deps + lefthook git hooks (via prepare)
npm run setup:python # uv sync — provisions .venv with the Python packages + dev tools
```

## Everyday commands

```bash
npm run check        # oxlint + oxfmt (ultracite)
npm run typecheck    # tsc across cli + studio
npm run test         # vitest (cli)
npm run build        # tsdown (cli) + next build (studio)
uv run pytest packages/variable-gen/tests   # Python tests
```

Lint and format run automatically on commit via lefthook (oxlint/oxfmt for JS/TS/JSON, ruff for Python) — scoped to staged files.

## Pull requests

- Keep changes focused; match the surrounding code style.
- Every user-facing change to the `static-to-variable` package needs a changeset so it gets versioned and released:

  ```bash
  npm run changeset
  ```

  CI fails PRs that change the published package without one.

- Make sure `check`, `typecheck`, `test`, `build`, and `pytest` all pass.

## Fonts and the engine

The Glide/Circular sources and donor fonts are **licensed and not included** in this repository (they are gitignored). The engine is generic: point it at your own static fonts via an `stv.config.json` (see `schemas/stv-config.schema.json` and the worked example in `examples/glide/`). Never commit font binaries or `.glyphs` sources.

## Releases

Publishing is automated: merging changesets to `main` opens a "Version Packages" PR; merging that publishes `static-to-variable` to npm via OIDC trusted publishing. No manual `npm publish`.
