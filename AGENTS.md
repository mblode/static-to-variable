# static-to-variable — agent instructions

Static-glyphs → variable-font pipeline. Node + Python monorepo using npm workspaces and Turbo.

## Workspace map

Each workspace has its own `AGENTS.md` with route maps, gotchas, and conventions:

@apps/studio/AGENTS.md @packages/cli/AGENTS.md @packages/glyph-forge-engine/AGENTS.md

(`packages/variable-gen` is Python-only; see its `README.md` for entry points.)

## Commands

```bash
npm run setup:python     # uv sync — provisions .venv with both Python packages + dev tools
npm run dev              # studio at https://static-to-variable.localhost
npm run build            # turbo build (cli via tsdown, studio via next)
npm run typecheck        # turbo typecheck (cli + studio + glyph-forge types)
npm run check            # oxlint + oxfmt (ultracite)
npm run test             # turbo test (vitest)
npm run pipeline -- list # pipeline stages
npm run pipeline -- run all  # run the full pipeline
npm run pipeline:status  # promotion-gate report
npm run forge:build      # rebuild SVG cache for the studio
uv run pytest            # Python tests (variable-gen + glyph-forge)
uv run mypy              # typecheck the variable_gen package
npm run changeset        # add a changeset before opening a release PR
```

## Rules

- **Run Python through the uv-managed env** (`uv run python …`, or the provisioned `.venv/bin/python`) — `fontTools`, `glyphsLib`, and `fontmake` are installed there, not on the global PATH. `uv sync` recreates it from `uv.lock`.
- The CLI delegates to the `@static-to-variable/variable-gen` and `@static-to-variable/glyph-forge-engine` workspaces. Do not reimplement repair or render logic inside `packages/cli`.
- Only the `static-to-variable` CLI package is published (npm, via changesets + OIDC). The studio app and Python engine workspaces stay private.

## Do not commit

Donor fonts, uploaded `.glyphs` files, generated TTFs, report directories, app job state, `.venv`, `node_modules`, or SVG caches. The `.gitignore` is the source of truth.
