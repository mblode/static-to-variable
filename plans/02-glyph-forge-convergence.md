# glyph_forge "automatic decisions" gate — convergence design

> **IMPLEMENTED & RESOLVED.** `glyph_forge` now **passes**. Two changes landed:
>
> 1. **Gain-aware gate** (`pipeline.py`): `_automatic_decision_kind` no longer flags an upgrade whose solver-projected gain is ≤ `AUTOMATIC_MIN_GAIN` (0.1) — a more-rigorous suggestion with no projected benefit is a treadmill, not a decision. Tests in `tests/test_glyph_forge_gate.py`.
> 2. **Safe auto-converge loop** (`packages/glyph-forge-engine/python/converge.py`, `npm run forge:converge`): loops `stage(gain-positive, no-downgrade) → apply → repair → residual`, accepts a batch only if it introduces **no new `blocker_residuals` failure**, reverts + permanently excludes any regressing glyph, and refreshes candidates via `audit + forge:build` each round.
>
> Result on first run: 3 rounds, **applied 26 glyphs, 0 regressions, gate candidates 25 → 0**, and it additionally **fixed 4 of the 6 residual defects** (italic `f_f_i`/`fi`/`onequarter`/`perthousand`) as a side effect. Residual failures dropped 6 → 2 (the roman ffi ligature only). The design below is what was built.

_Original design notes:_

## Symptom

`glyph_forge` fails with "unapplied automatic glyph decisions=N" (currently ~35: `Abreve`, `ebreve`, `oacute`, `four.dnom`, `perthousand.tf`, `uni00B9`, …). The gate (`_automatic_decision_kind` in `pipeline.py`) flags any glyph where the recommender's suggested strategy is more rigorous than the manifest's current strategy (`STRATEGY_RIGOUR[proposed] > STRATEGY_RIGOUR[current]`), or untriaged.

## Two real problems

1. **Stage ordering starves convergence.** `glyph_forge` runs _after_ `blocker_residuals`. When `blocker_residuals` fails, `run all` aborts before `glyph_forge` re-ingests the manifest, so the gate evaluates **stale** data. The operator must manually loop `auto-stage → apply → forge:build` to converge — it does not converge inside a single `run all`. (Verified: a single round dropped 55→1→0 only via manual re-ingest.)

2. **Applying suggestions is not always safe.** Blindly running `auto-stage`/`apply` over all candidates regressed glyphs — e.g. `italic:perthousand` went to `interpolatable=2` and several `.ss08` glyphs were frozen. So the gate's "just apply the suggestions" remediation can make the font worse, and the suggestions are not all safe to auto-adopt.

## Recommended fix (Fable-tier — it's correctness + workflow)

- **Make convergence safe and bounded.** Add a `forge:converge` workflow that loops `auto-stage(--no-downgrade) → apply → forge:build` until the candidate count is stable, but **only applies a suggestion if the projected gain is positive AND a rebuild keeps the glyph's `blocker_residuals` status green.** A suggestion that would regress residuals (interpolatable, area drift, freeze) must be rejected, not applied. This closes the "applying makes it worse" loop.
- **Decouple the gate from stale data.** Either re-ingest glyph_forge inputs at the start of the `glyph_forge` stage, or move the `auto-stage`/`apply` convergence ahead of `blocker_residuals` so a single `run all` converges.
- **Treat untriaged-with-no-defect glyphs explicitly.** The `untriaged` candidates (e.g. `uni00B9`, `uni2206`, `uni25A1`, `uni25CF`) are glyphs with a suggestion but no manifest entry. Decide per glyph: add a triage entry, or exclude them from the gate if they pass all structural/fidelity checks (mirror the `allow_static_outline` declassification used for the 20 clean currency glyphs).
- **Add a regression test** asserting that after a converge run with no regressions allowed, `automatic_decision_candidate_count == 0` AND `blocker_residuals` did not regress (idempotency + safety).

## Relevant code

- `packages/variable-gen/src/variable_gen/pipeline.py` — `_glyph_forge_stage`, `_automatic_decision_kind`, `STRATEGY_RIGOUR`.
- `packages/glyph-forge-engine/python/bulk_stage.py` — `auto-stage` / `--no-downgrade` logic.
- `packages/glyph-forge-engine/python/apply_pending_triage.py` — apply.
- `packages/glyph-forge-engine/python/recommend_strategy.py` — suggestion + `matchesExisting`.
