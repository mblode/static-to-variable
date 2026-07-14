# Codebase cleanup plan

This checklist tracks the cleanup pass after the static-to-variable pipeline work.

## Phase 1: Research and classify

- [x] Inspect current worktree status and diff scale.
- [x] Split review across worktree hygiene, Python quality, docs/contracts, and pipeline semantics.
- [x] Identify scratch churn versus source/report artifacts.

## Phase 2: Python cleanup

- [x] Add shared `variable_gen.common` helpers for family selection, JSON report writing, path display, artifact resolution, and hashing.
- [x] Remove private cross-module imports from analyzer code.
- [x] Close compatibility analyzer font handles with `ExitStack`.
- [x] Reject string and boolean numeric manifest values.
- [x] Make pipeline status robust against invalid JSON artifacts.
- [x] Make missing residual summaries block instead of silently passing.

## Phase 3: Contract cleanup

- [x] Align manifest schema docs with implemented axis fields.
- [x] Add explicit `donor_values` and `output_values` to the Circular source manifest.
- [x] Align compatibility report docs with the emitted family-keyed JSON shape.
- [x] Add the aggregate `pipeline_status` report contract.
- [x] Clarify implemented CLI commands in package READMEs.

## Phase 4: Gate cleanup

- [x] Separate diagnostic raw donor compatibility observations from blocking promotion failures.
- [x] Rename repair/build status to the narrower strict compatibility build gate.
- [x] Treat full audit as diagnostic in pipeline status; tracked residuals and glyph-forge blocker verdicts remain blocking.
- [x] Split glyph-forge visual QA counts into blocking verdicts and backlog verdicts.

## Phase 5: Verification

- [x] Regenerate inventory, raw compatibility, and pipeline status reports.
- [x] Run unit tests.
- [x] Run Python compile checks.
- [x] Run `git diff --check`.
- [x] Confirm no scratch `master_ufo` or `__pycache__` churn remains.
