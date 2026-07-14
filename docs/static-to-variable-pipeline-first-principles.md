# Static to variable pipeline from first principles

This plan defines a durable static-donor-to-variable-font pipeline for Glide. It starts from raw static donor fonts, not from already repaired Glide `.glyphs` sources, and treats the existing repo as a source of proven kernels to extract rather than the final architecture.

## Core model

A variable TrueType `glyf`/`gvar` font is not a sequence of unrelated outlines. It is a default outline plus point deltas attached to variation regions. That means every interpolating glyph needs stable identity across masters:

- Stable glyph presence and glyph naming.
- Stable contour identity and contour order.
- Stable point identity, including point counts and node roles.
- Stable contour start points.
- Stable metrics and phantom points.
- Compatible extrema, segment structure, and implied on-curve/off-curve points after cubic-to-quadratic conversion.

If any of those identities drift, `gvar` deltas target the wrong points. The result can be build failure, distorted interpolation, broken metrics, or visual regressions that only appear at interior weights.

For this project, "perfect variable glyphs" means:

- No unapproved structural mismatch reaches a variable build.
- Every non-identical glyph has intentional point and contour identity.
- Every exact donor checkpoint reconstructs the donor within explicit thresholds.
- Every interior sample is free of collapses, intersections, zero-ink outlines, and severe visual drift.
- Every true shape change is encoded as an intermediate/brace layer, alternate, feature variation, or manual redraw decision instead of being hidden as a frozen outline.

## Research basis

Primary external sources align with the local failure evidence:

- Microsoft OpenType variations docs define variable fonts as default values plus deltas over variation regions, with `gvar` deltas targeting glyph points and phantom points for metrics: <https://learn.microsoft.com/en-us/typography/opentype/spec/otvaroverview> and <https://learn.microsoft.com/en-us/typography/opentype/spec/otvarcommonformats>.
- `fontTools.varLib.interpolatable` is the official local tool for finding wrong contour order and broader master interpolatability problems: <https://fonttools.readthedocs.io/en/latest/varLib/interpolatable.html>.
- `fontTools.cu2qu` must convert related curves across multiple fonts together when TrueType output needs interpolation-compatible quadratic splines: <https://fonttools.readthedocs.io/en/stable/cu2qu/index.html>.
- `designspaceLib` provides the model for axes, sources, rules, variable fonts, instances, and `STAT` data: <https://fonttools.readthedocs.io/en/latest/designspaceLib/index.html>.
- `fontmake` is the build orchestrator for Glyphs, UFO, and designspace sources into static and variable binaries: <https://github.com/googlefonts/fontmake>.
- Glyphs documents intermediate/brace layers for per-glyph interpolation correction and alternate/bracket layers for shapes that should switch rather than interpolate continuously: <https://glyphsapp.com/learn/intermediate-layers> and <https://handbook.glyphsapp.com/en/single-page/>.

## Current repo baseline

`packages/variable-gen` is the current repair home, but it is still script-first. The reusable package directory at `packages/variable-gen/src/README.md` is only a placeholder. Existing scripts contain useful behavior:

- `packages/variable-gen/scripts/repair_circular_sources.py` has the current repair runner and source mutation flow.
- `packages/variable-gen/scripts/audit_variable_font.py` has the broad audit, build, sampling, and report flow.
- `packages/variable-gen/scripts/manifest_tools.py` has current manifest handling.
- `packages/variable-gen/scripts/validate_residual_glyphs.py` has focused residual validation logic.
- `packages/variable-gen/manifests/circular-triage.json` is the current authoritative per-glyph repair strategy manifest.

`packages/glyph-forge-engine` is a read-only QA and advisory layer over `variable-gen` reports. It renders, scores, stages, recommends, and solves, but it must not write back into `packages/variable-gen` reports. Useful kernels:

- `packages/glyph-forge-engine/python/render_glyph.py`
- `packages/glyph-forge-engine/python/score_glyph.py`
- `packages/glyph-forge-engine/python/build_scores.py`
- `packages/glyph-forge-engine/python/recommend_strategy.py`
- `packages/glyph-forge-engine/python/solve_glyph.py`

Future orchestration should become manifest-driven modules under `packages/variable-gen/src/variable_gen/`, while current scripts become thin CLI wrappers or compatibility shims.

## Donor inventory principle

Inventory starts from static donor fonts in `cabinet/Circular/`, not from `glide-variable.glyphs` or `glide-variable-italic.glyphs`. The repaired Glide sources are outputs/checkpoints, not the canonical input for static-to-variable conversion.

Current Circular donor coverage:

- Roman: 8 static donor weights in `cabinet/Circular/Circular/`.
- Italic: 8 static donor weights in `cabinet/Circular/Circular Italic/`.
- Current Glide variable source: 3 masters per roman/italic source (`100`, `400`, `950`).

The pipeline must preserve all donor checkpoints in the manifest even when the compiled variable source chooses fewer interpolation masters, brace layers, or localized repair strategies.

## Failure taxonomy

### P0: build and interpolation blockers

- Topology mismatch: glyph missing, contour count mismatch, point count mismatch, incompatible composite/decomposed state.
- Curve model or segment-type incompatibility, especially after mixed cubic-to-quadratic conversion.
- Frozen fallback debt: a glyph is copied or frozen to make the build pass without an explicit policy, owner, and future repair route.

P0 failures block the variable build or any release candidate.

### P1: quality and maintainability risks

- Contour identity/order ambiguity.
- Start-point mismatch.
- Missing or inconsistent brace/intermediate masters for local shape changes.
- Donor fidelity drift at named static checkpoints.
- Interior interpolation artifacts between donor checkpoints.

P1 failures can be accepted only with documented thresholds, screenshots or score evidence, and an issue/manifest policy.

### P2: feature and alternate strategy

- Alternates, style-set glyphs, and shape switching that should not be forced through one continuous outline.
- Glyph families that need `featureVars`, designspace rules, or named alternate substitution instead of point-compatible interpolation.

P2 items should not block the core pipeline, but the manifest must keep them visible so they do not become silent compatibility hacks.

## Target architecture

Build `packages/variable-gen` as a staged compiler:

1. Discover donor fonts and axis metadata.
2. Normalize sources into a common internal representation.
3. Analyze structural compatibility.
4. Plan repairs and substitutions from a manifest.
5. Apply safe repairs.
6. Build designspaces and variable fonts.
7. Extract checkpoint instances.
8. Validate structure, fidelity, metadata, and artifact freshness.
9. Emit reports consumed by `packages/glyph-forge-engine`.

The canonical pipeline status command is:

```bash
npm --workspace @static-to-variable/variable-gen run pipeline:status
```

It writes `packages/variable-gen/reports/pipeline-status.json` and `packages/variable-gen/reports/pipeline-status.md`. The raw donor compatibility stage is diagnostic because raw static donors are expected to be incompatible before repair. The promotion verdict is based on blocking gates after inventory, repair/build, audit, residual validation, and glyph-forge visual QA.

Initial module shape:

- `variable_gen.manifest`: parse, validate, and version manifests.
- `variable_gen.discover`: scan donor directories and derive weight/style inventory.
- `variable_gen.normalize`: decompose, order, wind, and convert curve models.
- `variable_gen.analyze`: run `fontTools.varLib.interpolatable` plus custom contour/point/metrics checks.
- `variable_gen.repair`: contour assignment, start-point rotation, segment repair, and post-`cu2qu` alignment.
- `variable_gen.substitutions`: declared frozen glyphs, alternates, and shape-switching policies.
- `variable_gen.build`: designspace generation, variable build, checkpoint extraction, and metadata patching.
- `variable_gen.validate`: structural, visual, donor, metadata, and freshness gates.
- `variable_gen.pipeline`: coherent stage status and promotion verdict.
- `variable_gen.reporting`: JSON/Markdown outputs for humans and glyph-forge.

## QA gates

Every candidate build must pass five gates:

1. Structural compatibility: all interpolating glyphs pass glyph presence, contour count/order, point count, segment type, start-point, winding, and phantom-point checks.
2. Donor fidelity: extracted named instances match donor statics within explicit outline, area, bounds, advance-width, and kerning thresholds.
3. Interior quality: sampled in-between weights are checked for intersections, zero-ink outlines, short segments, contour collapse, and severe drift.
4. Compiled font metadata: `fvar`, `avar`, `STAT`, `name`, `OS/2`, `hhea`, glyph order, cmap coverage, and named instances match the manifest.
5. Artifact freshness: reports, manifests, generated designspaces, compiled fonts, checkpoint instances, and glyph-forge caches are all derived from the same manifest version and source hashes.

`packages/glyph-forge-engine` scores are hard gates for visual regression and coverage. Solver recommendations are advisory until a vector rebuild proves the suggested repair and the rebuilt glyph passes the structural and fidelity gates.

Initial hard gate thresholds:

- Inventory: missing donors, unreadable donors, hash mismatches, missing axis locations, and path resolution errors must all be `0`.
- Compatibility: P0 blockers, unapproved fallbacks, missing policies, interpolatable errors, and phantom-point errors must all be `0`.
- Exact donor fidelity: point deviation starts at `<= 0.5` units and area drift starts at `<= 1.0%`, matching the current audit defaults.
- Interior quality: minimum segment length starts at `>= 2.0` units; zero-ink outlines, contour collapse, and new intersections must be `0`.
- Artifact freshness: manifest hash, donor hashes, build input hashes, report hashes, and glyph-forge cache metadata must agree for a candidate build.

## Phased plan

### Phase 1: document and inventory the pipeline

- [x] Create this first-principles plan.
- [x] Add a manifest schema draft that distinguishes raw donors, normalized working sources, generated Glide sources, and compiled outputs.
- [x] Add a donor inventory command design for the 8 roman and 8 italic Circular static weights.
- [x] Map current scripts to future module owners.
- [x] Define JSON report contracts needed by glyph-forge.
- [x] Define hard gate thresholds for P0/P1/P2 classification.

Exit criteria:

- The repo has a single agreed plan for starting from static donors.
- The immediate module boundaries are clear enough to implement without changing font data.
- No code, reports, fonts, or generated artifacts are changed in this phase.

Immediate Phase 1 repo changes:

- [x] Add `docs/static-to-variable-pipeline-first-principles.md`.
- [x] Follow-up: add `docs/static-to-variable-manifest-schema.md` with a versioned schema and examples.
- [x] Follow-up: add `docs/static-to-variable-report-contracts.md` for `variable-gen` to `glyph-forge` handoff.

### Phase 2: manifest v2 and donor discovery

- [x] Implement manifest loading in `packages/variable-gen/src/variable_gen/`.
- [x] Represent all Circular donor weights explicitly for roman and italic.
- [x] Record file paths, source hashes, glyph counts, cmap coverage, weight values, style names, and metrics metadata.
- [x] Validate that current 3-master Glide sources are marked as generated or repair targets, not canonical donor inventory.
- [x] Emit an inventory report without mutating source files.

Exit criteria:

- Running discovery produces a deterministic donor inventory for both families.
- Missing glyphs and style-set differences are visible before repair begins.
- The manifest can explain every input file used by later phases.

### Phase 3: compatibility analyzer

- [ ] Extract analyzer kernels from `audit_variable_font.py`.
- [x] Run official `fontTools.varLib.interpolatable` checks.
- [ ] Add custom checks for contour order, start points, segment types, winding, node counts, bounds, advances, and phantom points.
- [x] Classify every failure as P0, P1, or P2.
- [x] Emit machine-readable glyph summaries and family JSON reports.
- [ ] Add human-readable Markdown family reports.

Exit criteria:

- Every glyph has a compatibility status before repair.
- P0 blockers are reproducible from the manifest and source hashes.
- P1/P2 issues have enough evidence for repair planning or triage.

### Phase 4: repair planner and safe repair kernels

- [ ] Convert current triage behavior from script flow into manifest-driven repair plans.
- [ ] Extract safe kernels from `repair_circular_sources.py` and related helper code.
- [ ] Apply repairs in this order: glyph-set reconciliation, contour assignment, winding normalization, start-point rotation, segment coercion, node splitting, post-`cu2qu` start-point repair.
- [ ] Require every repair to emit `safe`, `review`, or `blocked`.
- [ ] Preserve traceability from donor outline to normalized outline to repaired outline.

Exit criteria:

- Safe repairs are repeatable and auditable.
- Blocked glyphs cannot silently fall through as frozen copies.
- Manual or solver-assisted repairs are represented as manifest decisions.

### Phase 5: build and checkpoint extraction

- [ ] Generate designspaces from repaired sources.
- [ ] Build variable TrueType outputs with deterministic axis and metadata handling.
- [ ] Extract static checkpoint instances at all donor weights.
- [ ] Patch or validate `fvar`, `avar`, `STAT`, `name`, and metric tables from manifest data.
- [ ] Keep build artifacts segregated from source manifests and reports.

Exit criteria:

- Roman and italic variable builds compile from manifest-defined inputs.
- All donor checkpoints can be regenerated from the variable fonts.
- Metadata matches the manifest and does not depend on hardcoded script paths.

### Phase 6: validation and glyph-forge gates

- [ ] Validate named checkpoint fidelity against raw donor statics.
- [ ] Validate interior sampled weights between adjacent donor checkpoints.
- [ ] Ingest reports into `packages/glyph-forge-engine` without write-back.
- [ ] Treat glyph-forge visual scores and coverage as hard regression gates.
- [ ] Treat solver output as advisory until the vector rebuild passes Phase 3 through Phase 5 gates.

Exit criteria:

- A build cannot pass with unresolved P0 failures.
- P1 exceptions are explicit and reviewed.
- Glyph-forge visual evidence is synchronized to the same manifest/source hash set as the compiled font.

### Phase 7: alternates and shape switching

- [ ] Identify glyphs where continuous interpolation is the wrong model.
- [ ] Encode alternate policies, substitution ranges, feature rules, or non-interpolating fallbacks in the manifest.
- [ ] Verify that alternates preserve user-facing glyph coverage and metrics.
- [ ] Add QA for substitution boundaries and named instances.

Exit criteria:

- Shape-switching glyphs have explicit policies.
- No alternate is introduced only as an implicit contour-compatibility workaround.
- Generated fonts retain predictable behavior at donor and interior weights.

## Non-goals for the first implementation

- Do not regenerate release fonts as part of documentation or inventory work.
- Do not mutate `glide-variable*.glyphs` until the manifest and analyzer can explain the donor-to-repair path.
- Do not make glyph-forge the source of repair truth.
- Do not accept frozen glyphs without manifest policy and exit criteria.
- Do not hardcode Circular paths, weights, or glyph policies into module logic.
