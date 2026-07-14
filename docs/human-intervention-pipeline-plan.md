# Human intervention pipeline plan

This plan turns the static-to-variable workflow into an operator loop: run a coherent stage, stop only when a human decision is required, review evidence in Glyph Forge, stage decisions, apply with a dry-run/backed-up CLI, then resume from the correct stage.

## Research Basis

- Next.js App Router pages are Server Components by default; use Client Components only for interactive filters and buttons. <https://nextjs.org/docs/app/getting-started/server-and-client-components>
- Route Handlers are the App Router API primitive, but this app should keep mutation routes narrow and fixed, not expose arbitrary command execution. <https://nextjs.org/docs/app/getting-started/route-handlers>
- Server Components can read local JSON from the server side without shipping report data or file paths to the browser. <https://nextjs.org/docs/app/getting-started/fetching-data>
- Local app rules require the Next app to read synced `public/` artifacts at request time. `packages/variable-gen` data must flow through the glyph-forge sync step.

## Intervention Model

Every stage has one of these operator states:

- `clear`: stage passed; keep moving.
- `diagnostic`: stage failed but does not block promotion.
- `needs_human`: stage failed and needs a glyph/source decision.
- `ready_to_apply`: human decisions are staged and need CLI dry-run/apply.
- `needs_rerun`: stage data is stale or missing; rerun the stage.

The app joins evidence by `family/glyph` from:

- `public/broken-glyphs.json`
- `public/glyph-scores.json`
- `public/cell-scores.json`
- `public/strategy-suggestions.json`
- `public/solver-results.json`
- `public/pipeline-status.json`
- `public/blocker-residual-validation.md`
- `packages/glyph-forge-engine/manifests/pending-triage-edits.json`

Writeback remains staged-first:

1. UI writes pending decisions only.
2. Human runs the existing dry-run/apply CLI.
3. Pipeline resumes from `repair_build`.

## Phases

### Phase 1: Coherent Stage Surface

- [x] Add a private pipeline CLI with named stages.
- [x] Add `pipeline:app` for the intervention app.
- [x] Print the intervention workspace URL when status is red.
- [x] Sync pipeline status and blocker residual reports into the app public cache.

### Phase 2: Intervention Data Contract

- [x] Build a server-only dashboard adapter that composes pipeline status, glyph scores, solver output, suggestions, residual failures, and pending edits.
- [x] Classify stage states as `clear`, `diagnostic`, `needs_human`, `ready_to_apply`, or `needs_rerun`.
- [x] Classify glyph review rows as required decisions, candidates, or backlog.
- [x] Extend pending decisions beyond strategy-only edits for fields such as `repair_bucket`, `base_glyph`, `brace_weights`, and deferral decisions.

### Phase 3: Bespoke Next.js Intervention Workspace

- [x] Add `/interventions` as a dedicated operator workspace.
- [x] Show blocking stage failures, residual blocker cards, human queue rows, pending decisions, and resume commands in one screen.
- [x] Allow inline staging of heuristic/solver strategies through the existing `/api/triage/stage` endpoint.
- [x] Keep apply as a CLI-mediated dry-run/backed-up operation.
- [x] Add a focused workbench view with a queue rail, selected glyph evidence, and `stage best & next` throughput actions.

### Phase 4: Human Handoff DX

- [x] Keep exact resume commands visible and copyable.
- [x] Keep optional source-mutating `isolate_blockers` explicit.
- [x] Add CLI `--handoff` modes for prompt/auto/off behavior.
- [x] Add CLI top-N loupe URLs for current blockers.
- [x] Add stale-artifact detection so the app warns before reviewing old pipeline data.

### Phase 5: Validation

- [x] Run `npm --workspace @static-to-variable/studio run prebuild`.
- [x] Run `npm --workspace @static-to-variable/studio run build`.
- [x] Run `npm --workspace @static-to-variable/cli run typecheck`.
- [x] Verify `/interventions` responds from the local dev server.
