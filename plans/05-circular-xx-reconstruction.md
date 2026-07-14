# Reconstructing Circular XX into a variable font

## Problem

Glide used to be built from the **Cabinet Circular** cut — the only one on disk that was interpolation-compatible (0 mismatches across weights) — but it was corrupt for `2 3 $ ¢` (frozen weight), patched with a synthesis hack.

The **Circular XX** cut (Lineto LL XX 3.0) draws every glyph correctly, but ships as independent statics. `fontTools.varLib.interpolatable` over its 8 weights: **604/755 glyphs with problems, 477 with hard structural mismatches** (different node/contour counts). So XX can't be used as variable masters directly — building from it froze 477 glyphs.

The pipeline only _detected_ this (`solve_glyph.py:reconstruction_status`) and routed to a human queue. Nothing made incompatible masters compatible.

## What was built

`packages/variable-gen/scripts/reconstruct_compatible.py` — a deterministic glyph **compatibility reconstruction engine**. For each glyph it takes the 8 XX donor outlines and, when their structures disagree, re-expresses every master in one shared point structure so they interpolate, each still matching its own weight.

`reconstruct(outlines_by_pos)` pipeline, cheapest-first, re-checked each step:

1. already compatible → pass through unchanged (curves preserved exactly).
2. flatten each contour to a **dense ring** (curves sampled) with **corner anchors** detected from the real curve tangents (handles), not neighbour nodes — so a smooth circle node is never mistaken for a corner.
3. **contour-order** match to a reference master (centroid + area).
4. **winding + start-point** alignment per contour.
5. **corner-anchored arc-length resampling**: between matched corners, resample to a shared point count by arc length; fully-smooth contours (`o`, bowls) use a canonical topmost-point anchor. Output is an all-line contour with identical structure across masters.
6. **corner-angle sweep** — retries a few thresholds when corner counts straddle.
7. **reference projection** — when corner counts still disagree (same contour count), place the _reference_ master's anchors on every master by normalised arc length, so no per-master corner agreement is needed.
8. **overlap union** (skia-pathops) — tried when masters disagree on contour _count_ and the pieces overlap.

### Result (roman; italic similar)

755 glyphs: **264 already-compatible + 476 reconstructed = 740 (98%)**, **14 left** for the AI fallback. Build froze 15 (was **477** from raw XX). Verified visually across all 9 weights: round glyphs smooth, weight ramp even, the numeral / punctuation row uniform — `2 3 $ ¢` now natively correct from XX (no synthesis).

## Integration (XX is now the donor)

- `rebuild_8master.py`: `PLANS` donor dirs/stems → `cabinet/Circular/CircularXX`, master metrics → XX (`capHeight 709, xHeight 481, asc 986, desc -277`); each glyph whose 8 donor signatures differ is passed through `reconstruct()`. Writes `packages/variable-gen/reports/reconstruction-report.json`.
- `synth_weight_glyphs.py` deleted (XX draws `2/3/$` correctly).
- `build_glide.py` freeze loop is now only a safety net (parses the "in glyph NAME:" error format too).
- `npm run rebuild:glide` = `rebuild_8master → normalize_glyphs → build_glide`.
- Donors live under the gitignored `cabinet/Circular/CircularXX/` — keep them locally; the build depends on them.

## Quality gate + the counter-closing fix (AI-discovered)

Every reconstruction must now pass a **quality gate** (`_quality_offenders`): its ink area must stay within 6% of the donor at every master. The risky fallbacks (reference projection, merge-to-min bridging) can deform a glyph badly — measured `dollar` swinging 115% in area, `uni216F` 349% — so the gate rejects those and the glyph freezes clean (renders at Book, doesn't vary) rather than shipping deformed.

`dollar` was the flagship hard case. An AI subagent diagnosed it (see `ai_dollar_probe.py`): the contour-count swing is NOT the bar merging — it's the two **S-counters closing** at heavy weights (negative-area holes vanishing). The fix, generalised into `_counter_closing()`: split each master into body + counters (by signed area), match counters to slots across weights by centroid, **synthesise the closed (heavy) counters** by shrinking a light template toward the collapse point, reconstruct each family independently, recombine. `dollar` now reconstructs to 3 contours / identical structure / 0–0.5% area dev and **varies correctly across the whole range** — verified by rasterising the built VF at all 8 weights.

The counter-closing split was then **generalised** (`_counter_closing`): treat every contour as a slot, match each master's contours to slots by centroid within the same winding sign, synthesise a slot missing at a weight by shrinking its template toward the merge point, reconstruct each slot family, recombine — so it covers `cent` (a closing counter) and any merging bar/accent, not just `$`.

A **dense corner-angle sweep** (8–48°) was also added: italic `f`, `fi`, `fl` and the f-ligatures have a single threshold-straddling corner that makes corner counts disagree by one and forces the lossy projection path; at a low angle all masters agree and the clean resample path is used. This recovered the whole italic f-family.

## Intermediate-weight collapse fix (start-drift + interpolation gate)

A subtler failure than freezing: glyphs like `C k K !` looked perfect at the 8 masters but COLLAPSED at in-between weights. Three causes, fixed:

- `signature()` (op-sequence + winding) can't see a contour that starts at a different node across masters — all-curve shapes (`C`, `o`) have an identical op-sequence from any start. Added `_starts_aligned`; drifting glyphs are reconstructed instead of copied.
- `rebuild_8master` only called `reconstruct()` when signatures differed, so those drifting glyphs were never caught. It now ALWAYS calls it.
- The quality gate only checked the 8 masters. Added `_interp_ok`: the ink area at each adjacent-master midpoint must stay near the mean (a bad point correspondence collapses it). A glyph that can't reconstruct cleanly now FREEZES to the Regular donor (constant — can't collapse) rather than keeping per-weight donor outlines that build but warp.
- A **uniform arc-length** resample fallback (no corner anchors — dense even points from a canonical start) handles diagonals (`k`) whose corner-anchored runs mis-correspond; uniform correspondence interpolates cleanly. Recovered `k`, `quotedbl`, `eth`, `ij`, the italic combining accents and `yen`.

## Final coverage

|              | already-compatible | reconstructed | frozen |
| ------------ | ------------------ | ------------- | ------ |
| Roman (755)  | 100                | 641           | 14     |
| Italic (744) | 87                 | 649           | 8      |

Down from **477 frozen** building from raw XX. Verified by rasterising the built VFs across a fine weight ramp (incl. the tricky 800–900 zone): the alphabet, numerals, `$ ¢ & @ % k K !`, and the italic `$ ¢ s g ¥ f fi fl ff` all vary cleanly with no collapse.

## Residual: 14 roman / 8 italic freeze clean

`cent` family (its bar stub is a positive-area contour, a different topology than `$`'s counters), `tcommaaccent`, `r.ss03` alternates, a few rare accented variants (`ibreve`, `itilde`, `kcommaaccent`), italic `dollar.tf`, `onehalf.ss08`. These either deform when reconstructed (quality-gate-verified) or can't interpolate cleanly (interp-gate), so they freeze to Regular: they render correctly, just don't vary in weight. All are rare. Varying them too needs per-glyph **AI reconstruction** (proven viable — a subagent cracked `$` via the counter-closing insight) or a hand redraw; the hook is `ai_pending` in the report.

## Follow-ups

- Reconstructed contours are dense **polylines** (all lineTo). Smooth at text sizes; for display-grade output, fit quadratic/cubic curves through the runs.
- A quality gate (reconstructed-vs-donor area/void per weight) to auto-flag any glyph the resampler degraded, instead of trusting interpolatability alone.
