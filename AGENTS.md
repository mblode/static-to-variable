# static-to-variable

Static font to variable font pipeline. npm workspaces coordinate a TypeScript CLI, a Python font engine, and the Next.js showcase.

## Setup

```bash
npm ci
uv sync
```

- Give every git worktree its own `.venv`; never symlink `.venv` between worktrees. A shared editable install points at whichever checkout `uv` synced last and makes parallel agents run the wrong engine.
- `uv` shares its download cache automatically, so isolated environments do not redownload the Python toolchain.

## Verification tiers

```bash
npm run check:node       # formatting and lint, about 1s
npm run verify:node      # check + TypeScript typecheck + Vitest
npm run verify:python    # ruff + mypy + Pytest
npm run verify           # commit gate: both runtime suites
npm run verify:full      # push/CI gate: verify + production build + minimal font build

# Narrow edit loops
npm --workspace static-to-variable run test -- src/config.test.ts
uv run pytest -q packages/variable-gen/tests/test_rebuild_plan.py
```

CI runs `verify:node` and `verify:python` in parallel, then keeps the packaged CLI/font-build assertions in the separate `e2e` job.

## Workspace contracts

- `packages/cli` is the published `static-to-variable` npm package. It orchestrates the engine; build and repair logic belongs in `packages/variable-gen`.
- `packages/variable-gen` is the private Python engine. Run it through `uv run`, not global Python.
- `apps/web` is the marketing site and showcase. Follow @apps/web/AGENTS.md when editing it.
- Glide's licensed donors and project config live in the sibling private `../static-to-variable-glide` repository. Never copy donor fonts or generated sources here.

## Font-pipeline gotchas

- `rebuild` regenerates every master layer from donor fonts and overwrites the `.glyphs` source. Put durable outline changes in donors or the private drawing stage, not the generated source.
- `build` only triggers `rebuild` when the source is missing. After donor or reconstruction changes, run `rebuild` explicitly before `build` or you will compile a stale source.
- A config's `root` controls donor, source, output, UFO, release, and report paths. Keep commands and promotion reports on the same config root; a report from another fixture or worktree is not evidence.
- `npm run test` covers JavaScript/TypeScript only. Use `npm run verify` for a commit gate.
- `npm run pipeline -- run all` drives the committed minimal fixture. For another family, pass its config directly to `variable_gen.cli` or the public `static-to-variable build --config ...` command.
- `STV_JOBS=1` is a debugging mode, not a speed setting. The default uses available cores; record any override with benchmark evidence.

## Generated and licensed files

Do not commit donor fonts, `.glyphs` sources, `master_ufo`, reports, release output, caches, `.venv`, or `node_modules`; `.gitignore` is authoritative. The committed showcase/web font assets documented there are deliberate exceptions.

## References

- Engineering index: @docs/engineering/README.md
- Python engine details: @packages/variable-gen/AGENTS.md
- CLI details: @packages/cli/AGENTS.md
- Human contribution flow: @CONTRIBUTING.md
