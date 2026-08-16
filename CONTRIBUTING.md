# Contributing

Thanks for your interest in static-to-variable. This is a Node + Python monorepo: a TypeScript CLI (`packages/cli`, published to npm) that orchestrates a Python font engine (`packages/variable-gen`), plus a Next.js web tool (`apps/web`).

## Prerequisites

- **Node** ≥ 24.11 (`.nvmrc`/`fnm` friendly)
- **Python** ≥ 3.11
- **[uv](https://docs.astral.sh/uv/)** — manages the Python env and lockfile

## Setup

```bash
npm install          # JS/TS deps + lefthook git hooks (via prepare)
npm run setup:python # uv sync — provisions .venv with the Python package + dev tools
```

Run both commands inside every git worktree. Do not symlink `.venv` between worktrees: the engine is installed editable, so a shared environment switches between checkout paths and makes parallel work unreliable.

## Everyday commands

```bash
npm run verify:node   # format/lint + TypeScript + Vitest
npm run verify:python # ruff + mypy + Pytest
npm run verify        # both; required before a commit
npm run verify:full   # verify + production builds + minimal font fixture
```

Use file-scoped tests while editing:

```bash
npm --workspace static-to-variable run test -- src/config.test.ts
uv run pytest -q packages/variable-gen/tests/test_rebuild_plan.py
```

Lint and format run automatically on commit via lefthook (oxlint/oxfmt for JS/TS/JSON, ruff for Python) — scoped to staged files.

## Pull requests

- Keep changes focused; match the surrounding code style.
- Every user-facing change to the `static-to-variable` package needs a changeset so it gets versioned and released:

  ```bash
  npm run changeset
  ```

  CI fails PRs that change the published package without one.

- Run `npm run verify`. Use `npm run verify:full` when the change affects font construction, packaging, or release output.

## Fonts and the engine

The engine is generic: point it at your own static fonts via an `stv.config.json` (see `schemas/stv-config.schema.json` and the worked example in `examples/inter/`). The committed `examples/minimal` uses OFL-licensed Inter subset donors; don't commit other font binaries or `.glyphs` sources.

## Releases

Publishing is automated: merging changesets to `main` opens a "Version Packages" PR; merging that publishes `static-to-variable` to npm via OIDC trusted publishing. No manual `npm publish`.

The system shape and verification caveats are indexed in [`docs/engineering/README.md`](docs/engineering/README.md).
