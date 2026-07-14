# Next.js File-Dump Generator Plan

Goal: turn Circular static sources into Glide variable fonts from a local Next.js operator app, while keeping human review limited to whole-glyph reconstruction cases.

## Research Findings

- Next.js App Router route handlers support multipart `request.formData()` and Node runtime handlers, which fits local upload and job creation.
- The current CLI pipeline is the source of truth: `@static-to-variable/variable-gen` repairs/builds/audits, `@static-to-variable/glyph-forge-engine` scores and applies non-reconstruction decisions.
- Repair and audit scripts still write repo-root `.glyphs`, `master_ufo/`, report, and build paths. Uploaded jobs must therefore run in an isolated disposable repo, not the live checkout.
- Uploaded donor OTFs are consumed by the full `repair` script. Follow-up convergence can use `repair:skip-import` after triage changes are applied.
- `auto-stage` intentionally skips solver-flagged reconstruction cases. Those become the only intended human handoff.

## Phase 1 — App Shell

- [x] Add `/generate` to `apps/studio`.
- [x] Add upload, job list, stage progress, log, and artifact download UI.
- [x] Keep the workflow separate from the static audit viewer.

## Phase 2 — Job Model

- [x] Store jobs under ignored `apps/studio/.pipeline-jobs/`.
- [x] Track inputs, stages, warnings, logs, outputs, and final verdict in JSON.
- [x] Allow one active local generation job at a time.
- [x] Enforce strict upload mode so missing donor/source/triage targets cannot silently fall back to the workspace.

## Phase 3 — APIs

- [x] Add multipart job creation.
- [x] Add job polling.
- [x] Add log polling.
- [x] Add registered artifact downloads with no arbitrary path serving.

## Phase 4 — Pipeline Runner

- [x] Copy the current checkout into an isolated job repo.
- [x] Symlink local `node_modules` and `.venv` into that isolated repo.
- [x] Overlay recognized uploads onto canonical Circular/Glide paths.
- [x] Default to workspace templates for missing targets; require a complete target set when fallback is disabled.
- [x] Run inventory, raw compatibility, full repair/import, audits, Glyph Forge, residual validation, and pipeline status.
- [x] Loop automatic non-reconstruction staging through apply, repair, audit, and solve until settled.
- [x] Collect variable TTFs and reports into job outputs.

## Phase 5 — Verification

- [x] Typecheck the Next.js app and job runner.
- [x] Build the Next.js app.
- [x] Run a real end-to-end generation job.
- [x] Confirm the job produces roman and italic variable TTF artifacts.
- [x] Confirm non-reconstruction decisions auto-converge before handoff.
- [x] Confirm exact-outline frozen dollar/cent blockers are surfaced as `needs_review`.

## Verification Evidence

Commands run on 2026-04-30:

```bash
npm --workspace @static-to-variable/studio run typecheck
npm --workspace @static-to-variable/studio run build
npm --workspace @static-to-variable/studio run generation:smoke -- --job-id 20260430071955-04ca7ab8
```

E2E job:

- Job id: `20260430071955-04ca7ab8`
- Final status: `needs_review`
- Automatic convergence: `pass 1: 3 automatic decisions; pass 2: 0 automatic decisions`
- Review boundary: exact-outline frozen `cent`/`dollar` blocker report present
- Roman TTF: `glide-variable-vf.ttf`, 381712 bytes, SHA-256 `a203507b00d282b52d5329eb14a6f0643b4e671b385b5cfb900e140e6ab0c1ed`
- Italic TTF: `glide-variable-italic-vf.ttf`, 382376 bytes, SHA-256 `76ece9a032929328141b58fb6041a84e5c34b8f60a91cc63942ac6b78f586fed`
- Font validation: both TTFs open with `fontTools.ttLib.TTFont`, expose `wght`, and instantiate at 100, 400, and 950.

Repeatable commands:

```bash
npm --workspace @static-to-variable/studio run generation:smoke
npm run verify:generation
```

Without `--job-id`, the smoke command creates a strict upload-mode job from the local canonical Circular/Glide source files and runs the full generator synchronously.
