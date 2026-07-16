# @static-to-variable/cli

Interactive static-to-variable pipeline stepper for static-to-variable glyphs.

## Commands

```bash
npm --workspace static-to-variable run cli -- --help
npm --workspace static-to-variable run build      # tsdown dual build (cli + library)
npm --workspace static-to-variable run typecheck
npm --workspace static-to-variable run test       # vitest
npm run pipeline -- list
npm run pipeline -- step
```

## Architecture

```text
src/
  cli.ts          # Commander entry point and Clack stepper
  stages.ts       # Stage IDs, commands, aliases, and plan selection
  runner.ts       # Workspace discovery, process execution, status printing
  index.ts        # Public API exports
  types.ts        # Shared TypeScript contracts
```

## Gotchas

- Commands always execute from the static-to-variable workspace root, even when npm starts the workspace script inside `packages/cli`.
- Python stages must call `.venv/bin/python` through the existing `@static-to-variable/variable-gen` npm scripts.
- `repair_build` mutates the live `.glyphs` sources plus generated build/report artifacts (it runs the config-driven `variable_gen.cli rebuild`). Keep it visibly prompted in the stepper.
- Do not make this package write visual QA data directly. It should delegate to `@static-to-variable/glyph-forge-engine`.
- This is the published npm package (`static-to-variable`). It builds with tsdown (ESM, dual cli+library output, shebang via banner — never add a shebang to `src/cli.ts`) and releases via changesets + OIDC. Bump versions with a changeset, not by hand.
