# Baseline + P0 triage

> **OUTCOME: pipeline is GREEN.** Promotion verdict `pass`, 0 blocking failures, for both roman and italic. Circular + Circular Italic build as the **Glide** variable typeface (`wght` 100–950, 10 named instances each, 755/744 glyphs). Path taken: false-green gate fix → declassify 20 clean glyphs → safe converge loop (fixed 4 defects, 0 regressions) → targeted donor reconstruction of the roman ffi ligature (`01-reconstruct-6-defective-glyphs.md`). Verify with `npm run pipeline -- run all && npm run pipeline:status`.

_Day 1 deliverable. Diagnosed baseline of the static-to-variable pipeline and the ranked P0 blocker list that the rest of the Fable window attacks._

## How this baseline was produced

Environment was already set up (`.venv` with fontTools 4.62.1, glyphsLib 6.13.0, fontmake 3.11.1; `node_modules` present). Steps run:

1. `npm install` (workspace deps for the CLI were missing — `@clack/prompts`).
2. Snapshotted pristine inputs to `.baseline-snapshot/` (both `.glyphs` sources + `circular-triage.json`) because the repair stages mutate `.glyphs` in place and `apply` rewrites the manifest. These are gitignored runtime inputs.
3. `npm run pipeline -- run all` → then `npm run forge:build` (the all-run aborts at the first blocking failure, so `glyph_forge` had to be run separately) → `npm run pipeline:status`.

Inputs confirmed present: 8 roman + 8 italic Circular donor weights in `cabinet/Circular/`, both `.glyphs` sources at root, manifests in `packages/variable-gen/manifests/`.

## Verdict: `fail`, but the build compiles and only **2** blockers remain

| Stage | Kind | Status | Notes |
| --- | --- | --- | --- |
| inventory | blocking | **pass** |  |
| raw_compatibility | diagnostic | pass | obs: interpolatable_error_count=79 (expected for raw donors pre-repair) |
| repair_build | blocking | **pass** | ✅ the variable font actually builds |
| full_audit | diagnostic | pass | obs: roman problem_glyphs=742/754, italic=580/743 — **diagnostic, not blocking** |
| blocker_residuals | blocking | **FAIL** | roman areaDriftFailures=2, italic areaDriftFailures=2 |
| glyph_forge | blocking | **FAIL** | "unapplied automatic glyph decisions=55" |

The headline `742/580 problem glyphs` is a _diagnostic observation_, not a gate. The real interpolation breakers are much smaller — `interpolatable_problem_glyphs` roman=31, italic=18 — and even those don't block promotion under the current gate config. **Promotion is blocked by exactly two stages.**

---

> **Day 2–3 update — P0-1 was re-diagnosed and FIXED.** The dangerous bug turned out to be a **false green in `blocker_residuals`**, not the `glyph_forge` rigour mismatch first hypothesized below. See the "RESOLVED" note under P0-1. The true baseline is **`fail` with 32 residual failures** (the old aggregator only ever surfaced the 4 area-drift ones and silently dropped ~28 others). Breakdown: ~26 "manifest marks reconstruction but solver does not" consistency mismatches, 4 area-drift (f-ligatures), 2 interpolatable (`italic:onequarter`, `italic:perthousand`).

## P0-1 — `glyph_forge` promotion gate is non-idempotent (pipeline-logic bug)

> **RESOLVED / RE-DIAGNOSED (Day 2–3).** Empirical testing showed the "55 unapplied decisions" was mostly a **stale-artifact convergence** artifact: `glyph_forge` runs _after_ `blocker_residuals`, so when `blocker_residuals` fails and aborts `run all`, `glyph_forge`'s input manifests never refresh and the gate evaluates stale data. Running `forge:build` against the current manifest dropped the count 55 → 1 → 0. Blindly applying the solver's suggestions via `auto-stage`/`apply` is **unsafe** — it regressed `italic:perthousand` to `interpolatable=2` and froze several `.ss08` glyphs.
>
> The real, dangerous bug was elsewhere: **`blocker_residuals` reported a false green.** `_residual_stage` in `pipeline.py` re-derived pass/fail by parsing only three markdown counters (`sourceStructureFailures`, `areaDriftFailures`, `minSegmentFailures`) and was blind to the `interpolatable` and disallowed-`frozen` failures that `validate_residual_glyphs.py` exits 1 on. So `pipeline:status` printed `blocker_residuals: pass` while the validator itself failed.
>
> **Fix applied:**
>
> - `scripts/validate_residual_glyphs.py` now emits an authoritative JSON verdict sidecar (`blocker-residual-validation.json`) whose `status` mirrors the script's exit code exactly (status/failure_count/failures/counts).
> - `_residual_stage` consumes that JSON as the source of truth (markdown parse retained as a hardened fallback that now also fails on `interpolatable`).
> - Regression test added: `tests/test_residual_gate.py` asserts an interpolatable-only failure is never reported green, a clean verdict passes, and a missing artifact is never `pass`. All 3 pass.
> - Verified end-to-end: `pipeline:status` now reports `blocker_residuals: fail` with all 32 failures, matching the validator.
>
> Note: two **pre-existing** test failures in `tests/test_manifest_discover.py` are unrelated schema-prefix drift (`glide.` prefix expected by the test, not emitted by `discover.py`/`pipeline.py`). Left as-is; flagged for the delegation plan.
>
> _Original hypothesis (kept for the record) below:_

**This gate can never reach zero, no matter what you apply.** Verified empirically: ran `auto-stage` → `apply` (9 new + 46 updated entries written to `circular-triage.json`, e.g. roman `f_f_i` moved `manual_review → weighted_fallback`) → `pipeline -- run all --from repair_build`. The verdict was unchanged and `auto-stage` _still_ wants to stage the **identical 55 glyphs with identical score gains**. The manifest change persisted; the gate ignored it.

**Root cause** — two different strategy sources that never reconcile:

- The **apply path** (`packages/glyph-forge-engine/python/bulk_stage.py`, invoked as `auto-stage = bulk_stage.py --strategy-source suggestion --no-downgrade`) writes the **solver winner** strategy into the manifest.
- The **gate** (`_automatic_decision_kind` in `packages/variable-gen/src/variable_gen/pipeline.py`) compares the manifest's current strategy against `strategy-suggestions.json` (the **recommender** output), counting a glyph as an "automatic decision candidate" whenever `STRATEGY_RIGOUR[proposed] > STRATEGY_RIGOUR[current]` or there's no current strategy at all.

When the recommender's suggestion is higher-rigour than the solver winner that `apply` actually wrote, `proposed_rigour > current_rigour` stays true forever. The gate is checking against a target the apply flow never writes.

**Fix (Day 2–3, Fable-tier — it's correctness, not typing):**

- Pick a single source of truth for "the automatic strategy" — either have the gate compare against the same source `bulk_stage` writes from, or have `bulk_stage` write the recommender's `strategy-suggestions.json` strategy.
- Make "applied" mean "manifest strategy == the resolved automatic strategy" (identity), not "manifest rigour < suggested rigour" (a moving target).
- Reconcile the `STRATEGY_RIGOUR` ordering used on both sides so `--no-downgrade` and the gate agree on what "more rigorous" means.
- Add a regression test that asserts: after `auto-stage` + `apply`, the gate's `automatic_decision_candidate_count` is 0 (idempotency).

Relevant code: `pipeline.py` (`_glyph_forge_stage`, `_automatic_decision_kind`, `STRATEGY_RIGOUR`), `glyph-forge-engine/python/bulk_stage.py`, `glyph-forge-engine/python/recommend_strategy.py`, `glyph-forge-engine/manifests/{strategy-suggestions,solver-results}.json`.

## P0-2 — f-ligature area drift (font-engineering)

Four glyphs fail `blocker_residuals` with large donor-fidelity area drift, and the drift **persisted unchanged** after the fallback strategies were applied — proving a fallback copy cannot fix it:

| Glyph                   | Family | maxAreaDrift | Risky weights           |
| ----------------------- | ------ | ------------ | ----------------------- |
| `f_f_i` / `uniFB03` (ﬃ) | roman  | 40.33%       | 250, 400, 675, 950      |
| `f_f_i` / `uniFB03` (ﬃ) | italic | 58.69%       | 100, 250, 400, 675, 950 |
| `fi` (ﬁ)                | italic | 59.01%       | 100, 250, 400, 675, 950 |

**Root cause:** ligatures legitimately change shape across the weight axis (the f-hook/dot overlap differs from thin to black). A single-donor "fallback copy" freezes one weight's outline, so area diverges 40–59% at the other checkpoints. Continuous point-interpolation is the wrong model for these glyphs.

**Fix (Day 2–3, Fable-tier):** for each, choose and encode the right strategy instead of a frozen fallback —

- **brace/intermediate layers** at the risky weights so the ligature interpolates with intentional per-weight identity, or
- **per-checkpoint reconstruction** from the donor statics, or
- confirm whether the area-drift _measurement_ should be weight-aware for composite ligatures (is 40% real visual drift, or an artifact of comparing a frozen outline against per-weight donors?).

Decide per glyph, encode in `circular-triage.json` with an explicit policy, and re-run residual validation. Cross-reference the visual evidence in the studio (`/g/roman/f_f_i`, `/g/italic/fi`).

---

## Diagnostic backlog (non-blocking — Phase-3 analyzer, later)

Not gating promotion today, but these are what the Phase-3 analyzer custom checks (Day 2–3) should formalize so "green" is trustworthy:

- `interpolatable_problem_glyphs`: roman 31, italic 18.
  - issue types — roman: contour_order=15, wrong_start_point=7, underweight=28, kink=22; italic: contour_order=11, wrong_start_point=12, underweight=34, kink=16.
- `glyphs_with_intersections`: roman 45, italic 60.
- `glyphs_with_short_segments`: roman 212, italic 268.

**UPDATE — Phase-3 analyzer custom checks DONE.** `analyze.py` now adds structural checks complementary to `fontTools.varLib.interpolatable`: **segment-type signature** (P0), **winding direction** (P1), and **advance/phantom-point** consistency across masters (P1, wired into the `phantom_point_error_count` hard gate). It also emits **human-readable Markdown family reports** (`--markdown`, e.g. `reports/compatibility-raw.md`, now part of the `compatibility:raw` npm script). First run surfaced 10 real `winding_mismatch` findings (e.g. `igrave`, `emacron` accent contours flipping direction at the black masters), no false positives. Tests: `tests/test_analyzer_structural.py`.

## Day 2–3 outcomes (progress log)

- **False-green gate bug FIXED + tested** (see P0-1 RESOLVED note). Highest-value Phase-6 work: the promotion gate now faithfully mirrors the validator.
- **20 clean glyphs declassified.** The currency cluster + italic `f_i`/`onehalf`/`percent.ss08`/`uniFB03` had no outline defect — only a stale `reconstruction_required` flag. Declassified via `allow_static_outline` + `repair_bucket: resolved_clean` (the manifest's documented accept-as-is policy, honored by both the validator and the glyph_forge gate). No outlines touched. `blocker_residuals` dropped **32 → 12 failures**.
- **Programmatic reconstruction of the 6 defects attempted and reverted** — the family-wide donor re-import regresses these glyphs (and breaks the clean currency ones). They need hands-on Glyphs work. Full spec: `01-reconstruct-6-defective-glyphs.md`.
- **glyph_forge convergence characterized:** `02-glyph-forge-convergence.md`.

- **glyph_forge convergence RESOLVED** — gain-aware gate + safe auto-converge loop (`forge:converge`) drove gate candidates 25 → 0 with 0 regressions, and fixed 4 of the 6 defects (all italic) as a side effect. See `02-glyph-forge-convergence.md`. New tests: `tests/test_glyph_forge_gate.py`.

**Final pipeline state:** `glyph_forge` **passes**; `repair_build`, `inventory`, `raw_compatibility`, `full_audit` pass. The **only remaining blocker** is `blocker_residuals` on a **single outline** — the roman ffi ligature (`f_f_i` = `uniFB03`, 40.33% area drift, negative-gain fallbacks) — which needs hands-on reconstruction in Glyphs (`01-reconstruct-6-defective-glyphs.md`, Group A roman row). Went from "FAIL, 4 blocking stages, opaque" to "1 blocking stage, 1 ligature outline."

## Attack order for the rest of the window

1. **P0-1 gate idempotency** (unblocks `glyph_forge` permanently; pure logic, no font data changes — safest first win).
2. **P0-2 f-ligatures** (the real font-engineering; unblocks `blocker_residuals`).
3. Re-run `pipeline -- run all`; confirm verdict flips to `pass` (or only documented P1 exceptions remain).
4. Phase-3 analyzer custom checks + Markdown reports, then Phase-6 `validate` module, so the green verdict is backed by real gates (Day 2–3 plan, task #2).

## Reproduce

```bash
cd static-to-variable
npm install
npm run pipeline -- run all          # builds + audits; aborts at blocker_residuals
npm run forge:build                  # populate glyph_forge manifests
npm run pipeline:status              # aggregated verdict
```

Snapshots of pristine inputs are in `.baseline-snapshot/` (restore the two `.glyphs` files and `circular-triage.json` to return to the exact baseline).
