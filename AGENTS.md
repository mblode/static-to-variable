# static-to-variable — agent instructions

Static-glyphs → variable-font pipeline. Node + Python monorepo using npm workspaces and Turbo.

## Workspace map

Each workspace has its own `AGENTS.md` with route maps, gotchas, and conventions:

@packages/cli/AGENTS.md

(`packages/variable-gen` is Python-only; see its `README.md` for entry points. `apps/web` is the marketing site and font showcase; it builds nothing, the CLI is the only way to run the pipeline.)

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
- **`rebuild` re-derives every outline from the donors.** It reads the `.glyphs` source only for its glyph roster and a template master (`rebuild.py` `rebuild_style`), then overwrites each layer from the donor fonts. Editing outlines in a `.glyphs` source and then running the pipeline silently discards the edit — change the donors instead. `ensure_source` will synthesise a source from the default donor when none exists, so a new family needs no hand-authored `.glyphs` at all.

## Glide lives in a separate private repo

The Glide and Circular build is not in this repo. It is [mblode/static-to-variable-glide](https://github.com/mblode/static-to-variable-glide), checked out as a sibling at `../static-to-variable-glide` so no licensed foundry material (Circular XX) lands in the public repo. It holds the donors, both `stv.config.json` files, the `.glyphs` sources and the x-height transform, with every path relative to itself:

```bash
.venv/bin/python -m variable_gen.cli build --config ../static-to-variable-glide/configs/glide.json --style all
```

The exception is `apps/web/app/fonts` and `apps/web/lib/og-assets`: those Glide woff2/ttf are committed build artifacts the marketing site needs, same as the showcase fonts.

## Do not commit

Donor fonts, generated `.glyphs` sources, generated TTFs, report directories, `.venv`, `node_modules`, or SVG caches. The `.gitignore` is the source of truth. Two deliberate exceptions, both committed build artifacts: the showcase fonts in `apps/web/public/fonts` (rebuilt with `scripts/rebuild-showcase-fonts.py`) and the Glide webfonts in `apps/web/app/fonts`.
