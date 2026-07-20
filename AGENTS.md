# static-to-variable — agent instructions

Static-glyphs → variable-font pipeline. Node + Python monorepo using npm workspaces and Turbo.

## Workspace map

Each workspace has its own `AGENTS.md` with route maps, gotchas, and conventions:

@packages/cli/AGENTS.md

(`packages/variable-gen` is Python-only; see its `README.md` for entry points. `apps/web` is the public web tool.)

## Commands

```bash
npm run setup:python     # uv sync — provisions .venv with the Python package + dev tools
npm run dev              # the web app (apps/web) in dev
npm run build            # turbo build (cli via tsdown, web via next)
npm run typecheck        # turbo typecheck (cli + web)
npm run check            # oxlint + oxfmt (ultracite)
npm run test             # turbo test (vitest)
npm run pipeline -- list # pipeline stages
npm run pipeline -- run all  # run the full pipeline
npm run pipeline:status  # promotion-gate report
uv run pytest            # Python tests (variable-gen)
uv run mypy              # typecheck the variable_gen package
npm run changeset        # add a changeset before opening a release PR
```

## Rules

- **Run Python through the uv-managed env** (`uv run python …`, or the provisioned `.venv/bin/python`) — `fontTools`, `glyphsLib`, and `fontmake` are installed there, not on the global PATH. `uv sync` recreates it from `uv.lock`.
- The CLI delegates to the `@static-to-variable/variable-gen` workspace. Do not reimplement build or repair logic inside `packages/cli`.
- Only the `static-to-variable` CLI package is published (npm, via changesets + OIDC). The web app and Python engine workspace stay private.

## Do not commit

Donor fonts, uploaded `.glyphs` files, generated TTFs, report directories, app job state, `.venv`, `node_modules`, or SVG caches. The `.gitignore` is the source of truth.
