# Verification

## Tiers

| Tier | Command | Run when |
| --- | --- | --- |
| Narrow | `npm --workspace static-to-variable run test -- <file>` or `uv run pytest -q <file>` | During an edit loop |
| Node | `npm run verify:node` | TypeScript, CLI, config, or web changes |
| Python | `npm run verify:python` | Engine, schema, or font-pipeline changes |
| Commit | `npm run verify` | Before every commit |
| Full | `npm run verify:full` | Before pushing changes that affect builds or releases |

CI deliberately runs the Node and Python halves in parallel, using the same component commands as local verification. Its `e2e` job adds packaged-CLI, minimal-font, invalid-config, doctor, and bundled-engine assertions.

## Worktrees

Run both installers inside each worktree:

```bash
npm ci
uv sync
```

Do not symlink `.venv` between worktrees. `variable-gen` is installed editable, so `uv` rewrites the environment's source path to the checkout most recently synced. Parallel agents sharing that environment can silently execute another branch and also spend time repeatedly uninstalling and reinstalling the package. `uv`'s download cache is already shared safely.

Use `npm run test -- --force` when you specifically need an uncached Turbo test run. Normal cached runs are valid for identical inputs, but replayed logs may contain a path from the worktree that originally populated the cache.

## Commands that can mislead

- `npm run test` covers Vitest only. It does not run the Python engine suite; use `npm run verify` for a repository gate.
- The web workspace currently has no Vitest files and uses `--passWithNoTests`; its meaningful gates are typecheck and production build.
- `build` reuses an existing generated source. It does not prove donor or reconstruction changes unless `rebuild` ran first.
- `npm run pipeline -- run all` targets the committed minimal fixture, not an arbitrary external config.
- `status` reports red gates but exits zero unless `--fail-on-red` is supplied. A promotion script must request that flag and must read reports from the same project root as the built font.
- A report filename alone does not identify its inputs. Confirm config root, version, and artifact hashes before using it as release evidence.

## Reconstruction benchmarks

Record all of the following so results can be compared:

- engine commit
- config path and style
- cold or warm inputs
- glyph count and optical-row count
- `STV_JOBS` value or default worker count
- wall time
- output hash and serial/parallel equivalence result

`STV_JOBS=1` keeps debugging tracebacks readable. It is not the default performance baseline.
