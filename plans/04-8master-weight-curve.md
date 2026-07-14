# Glide as an 8-master variable font matching Circular's weight curve

## Problem

After the 3-master fix, the extremes were right but **intermediate weights were too heavy** and the "thin" weights weren't thin — visible across the numerals/ punctuation row. 3 masters (100/400/950, using Circular Thin/Book/ExtraBlack) can't follow Circular's real 8-weight curve, so linear interpolation overshot (`VF@250` ≈ 1.23× Circular Thin; `zero@675` ≈ 1.50×).

## Fix

Rebuilt Glide as a **true 8-master variable font** — one master per Circular weight — on a conventional **100–900 axis, default 400**, where each named weight equals its Circular donor:

| Glide | 100 | 200 | 300 | 400 | 500 | 700 | 800 | 900 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| name | Thin | ExtraLight | Light | Regular | Medium | Bold | ExtraBold | Black |
| donor | Thin | Light | Regular | Book | Medium | Bold | Black | ExtraBlack |

`SemiBold (600)` interpolates Medium↔Bold. Result: every named weight matches its donor at **median 1.000**, intermediate weights interpolate monotonically with no overshoot, the numerals row is uniform, and Thin = Circular Thin.

## Scripts (reproducible)

```bash
.venv/bin/python packages/variable-gen/scripts/rebuild_8master.py --font all
npm run build:glide
```

- **`rebuild_8master.py`** — restructures each `.glyphs` source to 8 masters and populates every glyph from the matching `cabinet/Circular` donor. Donor glyphs are resolved by **codepoint** when the source name differs (source uses `rcommaaccent`, donors use `uni0157`). Per-glyph handling:
  - in donors + compatible → 8 donor outlines (donor-faithful).
  - `zero` → Circular's `zero` is non-monotonic in the donors (Bold zero is malformed/short), so its middle masters are interpolated linearly from the clean Thin/ExtraBlack extremes → smooth monotonic ramp.
  - not in donors (≈283 italic accents/superscripts Circular Italic lacks) → keep their prior weight variation by sampling the previous 3-master interpolation at the 8 axis positions.
- **`build_glide.py`** — export designspace → fontmake (`--keep-overlaps`), freezing any cu2qu-incompatible leftover to Book, then a per-named-weight fidelity check against each mapped donor.
- **`cabinet/export_designspace.py`** — axis 100–900 default 400, 9 named instances (Thin…Black) with `usWeightClass`, and STAT axis labels (Regular elidable, Regular↔Bold RIBBI link).

## Best practices honoured

Variable TrueType with overlaps kept (no `removeOverlap`); default 400 is a real master; conventional CSS axis; family "Glide"; separate Roman/Italic files; fvar named instances + STAT.

## Two donor cuts, and why we use both

There are two cuts of Circular on disk (both under the gitignored `cabinet/Circular/`):

| cut | weights | interpolation-compatible? | draws `2 3 $ ¢` correctly? |
| --- | --- | --- | --- |
| **Cabinet** `Circular/`, `Circular Italic/` | 8 (Thin…ExtraBlack) | **yes** — 0 contour/point mismatches across weights | **no** — frozen weight |
| **Circular XX** (Lineto LL XX 3.0) `CircularXX/` | 8 + italics | **no** — 267 glyphs mismatch across weights | **yes** |

`audit_donors.py` proved the Cabinet cut is _corrupt_ for a few glyphs whose strokes don't thicken across weights: `2`/`3`/`$`/`cent` keep a **constant fill density** at every weight (so at Thin they read heavy, at Black light, vs their siblings), and `zero` dips at Bold. But the Cabinet cut is the only one that is **interpolation-compatible** (a hard requirement — Circular XX would freeze 267 glyphs if used as masters). So Glide is built from the Cabinet cut and the few corrupt glyphs are rebuilt by `synth_weight_glyphs.py`.

## Weight synthesis (synth_weight_glyphs.py)

For `2`, `3`, `$`, `cent`: take ONE clean Circular master (`CircularStd-Book`, quadratic TTF) as the **shared point structure** for all 8 Glide masters, and offset it along point normals per master so its fill density matches the Cabinet **digit-median** density at that weight. One structure across masters ⇒ still interpolation-compatible; a real per-weight stroke offset ⇒ no longer frozen. Result: `2`/`3` now track their siblings exactly (density 0.360→0.640 Thin→Black, verified in the built VF) — confirmed visually thin at Thin and heavy at Black.

- A _quadratic_ base is used on purpose: offsetting a cubic and letting fontmake's cu2qu re-split it produced per-master point-count mismatches (froze `two`); an already-quadratic base passes through cu2qu unchanged.
- `zero` is left to the Cabinet donor — its only defect is a minor Bold dip and its counter contour offsets less cleanly.

## Figure normalization (normalize_glyphs.py)

Runs after synthesis. Flags a letter/figure only when its box is inconsistent with its Regular master — floats above the baseline (`float_up > 30`) or falls short of the cap (`falls_short > 40`); innate overshoot (ymin only going negative, e.g. `6 9 o 0`) is never flagged, so round glyphs keep their bloom. Flagged glyphs are mapped onto the Regular master's vertical box (scale + shift Y, X and point structure untouched → still interpolation-compatible).

Pipeline (one command, `npm run rebuild:glide`): `rebuild_8master → synth_weight_glyphs → normalize_glyphs → build_glide`.

## Residual

- **`$` / `cent`** still freeze to Book in the build: they are thin glyphs with large counters, the normal-offset balloons them at the heavy end, and after the glyphsLib quad→cubic round-trip cu2qu finds their segment counts incompatible. Frozen-at-Book matches the Cabinet cut's own (already near-frozen) `$`, so it is no regression — `$` reads slightly heavy at Thin / light at Black. A clean fix needs `$`/`¢` redrawn as interpolation-compatible masters (a type-design task).
- build_glide's fidelity check counts the synthesized glyphs as "off vs donor" at some weights — expected, since they intentionally no longer match the defective Cabinet donor.

## Residual (hands-on follow-up)

- **Roman** (12 glyph-weights): `uni216F.ss08` (frozen, cu2qu), `uni0122.ss01`, `uni0157.ss03` — stylistic-set alternates not in cmap, so not codepoint- resolvable; they sample (slightly light).
- **Italic** (6): `at` (@, frozen — cu2qu point-count mismatch) and `uni0326` (combining comma-below). The ≈283 italic glyphs Circular Italic lacks keep their sampled 3-master progression (vary, but not donor-faithful).
- The default Regular fvar instance name needs a small metadata pass.
