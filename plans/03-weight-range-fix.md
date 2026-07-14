# Glide weight-range fix (donor re-derivation, brace removal)

## Problem

The variable build passed the gates but was visually broken: ~52% of glyphs rendered **underweight** at the heavy end of the axis. At ExtraBlack (950), letters like C E F G H S T U V W X Y Z stayed light while A B O P Q R went black, plus stray white specks in round glyphs. `wght=950` instances measured **391/754 roman and 192/453 italic glyphs at <0.92× the donor ExtraBlack ink area** (some as low as 0.28×).

## Root cause

The build added **brace / intermediate master layers** at weights {250} and {675} (from `repair_circular_sources.py`'s interpolation-risk mitigation + `structural_fallback` strategies). glyphsLib turned those into full intermediate masters; every non-brace glyph was filled at those locations with its **Regular** outline, pinning the interpolation through Regular-weight at 250/675 and **compressing the whole weight curve** (Thin too heavy, ExtraBlack too light). The masters themselves were also being distorted by the importer's compatibility-normalization — which is unnecessary, because **all Circular donors are already point-compatible across Thin/Book/ExtraBlack** (755/755 roman, 472/472 italic).

The green verdict missed this: `full_audit` (which flagged ~742 problem glyphs) is non-blocking and `blocker_residuals` only checks ~40 tracked glyphs.

## Fix

Re-derive every glyph's masters **directly from the mapped Circular donor outline** (Thin←Circular-Thin, Regular←Circular-**Book**, ExtraBlack←Circular-ExtraBlack; italic analogous, via `FONT_PLANS.donor_paths_by_master_name`), strip all brace/intermediate layers, and build straight through fontmake. The donor-faithful masters interpolate correctly on their own.

Result: underweight at 950 dropped to **2/754 roman, 7/453 italic**; the whole alphabet renders at uniform, correct weight Thin→ExtraBlack, no specks. Verified visually in the specimen and quantitatively across 100/250/400/675/950.

## Reproducible pipeline

```bash
# 1) re-derive masters from donors + strip braces; auto-revert the few glyphs
#    whose donor outlines don't interpolate (start at a different node, e.g.
#    dollar) to their importer masters so the build stays compatible.
.venv/bin/python packages/variable-gen/scripts/rederive_from_donors.py --font all
# 2) export designspace (fixing the axis) + fontmake + full-weight fidelity check
npm run build:glide        # = packages/variable-gen/scripts/build_glide.py
```

`build_glide.py` reports any glyph <0.92× its donor at 100/250/400/675/950, so weight regressions can't pass silently. **Do not run `repair_circular_sources.py` over these sources** — it re-adds the compressing brace layers.

## Critical files

- `packages/variable-gen/scripts/rederive_from_donors.py` — donor re-derivation, brace strip, interpolatable-based auto-revert of incompatible glyphs.
- `packages/variable-gen/scripts/build_glide.py` — clean build + fidelity check (`npm run build:glide`).
- `cabinet/export_designspace.py` — reused; fixes the glyphsLib axis bug.
- `glide-variable.glyphs` / `glide-variable-italic.glyphs` — re-derived sources (gitignored).

## Remaining edge glyphs (hands-on follow-up)

~9 glyphs still underweight because their donor outlines start a contour at a different node across weights (hard interpolation incompatibility) and they were reverted to their compressed importer masters:

- roman: `uni0157` (rcommaaccent), `emacron`, `uni216F`, `uni00B3`
- italic: `dollar`, `dollar.tf`, `at`, `Igrave`, `Iacute`, `igrave`, a few superscripts/marks

Automated alignment is not safe here — global `strict_align` (contour reorder) broke other glyphs (e.g. `mu`), and rotation-only didn't resolve them. These need per-glyph start-point/contour alignment in Glyphs.app (rotate the offending contour's start to match across masters, then re-derive). `dollar` is the most visible and should be done first.
