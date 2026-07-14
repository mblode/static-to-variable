# Reconstruction spec: defective glyphs (RESOLVED)

> **DONE — pipeline is GREEN.** All 6 defects are resolved and the static-to-variable promotion verdict is `pass` (0 blocking failures) for both roman and italic. Circular + Circular Italic now build as the **Glide** variable typeface (wght 100–950, 10 named instances each).
>
> The roman ffi ligature (`f_f_i` = `uniFB03`) was fixed by **targeted per-glyph donor reconstruction** (not a broad re-import, which regresses): its source masters had a wrong 62-node outline drifting 40% from the donor. The fix copies the Circular donor ffi outline **directly** into each Glide master, matching the master→donor mapping the audit validates against (`FONT_PLANS.donor_paths_by_master_name`): Thin←Circular-Thin, Regular←Circular-**Book**, ExtraBlack←Circular-ExtraBlack. Key lessons:
>
> - Copy the donor outline **directly** per master — do NOT extrapolate. Normal glyphs' Thin(100) master IS the Circular-Thin(250) outline as-is; the audit compares instance@100 against Circular-Thin, so an extrapolated thin shows a false ~39% "drift" (the same gap every glyph would show — see note below).
> - Use the **exact** validation donors. The Regular master maps to Circular-**Book**, not Circular-Regular.
> - The three donors (Thin/Book/ExtraBlack) are point-compatible, so the copied masters interpolate cleanly (strict path_order/node_count/start all 0).
> - Then declassify the glyph (`allow_static_outline` + `resolved_clean`) since it is now donor-faithful.
>
> Reusable technique for any future single-glyph reconstruction: extract the donor outline via `DecomposingRecordingPen`, write into the GSLayer via `layer.getPen()`, set `layer.width` to the donor width, rebuild `--font <fam> --skip-import`, and re-audit.
>
> _Note (latent gate quirk, not blocking):_ the donor-fidelity check compares the Thin master (axis weight 100) against Circular-Thin (design weight 250). That is apples-to-oranges for any glyph whose 100-master is a true extrapolation, but it is harmless here because every master outline is the donor outline as-is. If a future design genuinely extrapolates below 250, exclude sub-donor-range master weights from the area-drift gate.

> _Historical: 5 of 6 were resolved automatically first._ The safe converge loop (`02-glyph-forge-convergence.md`) fixed all 4 italic defects (`f_f_i`, `fi`, `onequarter`, `perthousand`) via gain-positive, non-regressing fallback strategies. **Only the roman ffi ligature remains** — `f_f_i` and `uniFB03` are the same outline (40.33% area drift), with negative-gain fallbacks (so no automatic strategy helps; the converge loop correctly left it alone). It is the **sole remaining `blocker_residuals` failure** and the only glyph needing hands-on reconstruction — see Group A, roman row.

_Day 2–3 deliverable. The remaining `blocker_residuals` failures after the 20 clean glyphs were declassified. Programmatic reconstruction was attempted and **regresses** these — see "Why not automated" — so they need hands-on work in Glyphs.app. This spec is precise enough to execute glyph-by-glyph._

## Context

The "26-glyph reconstruction backlog" split into **20 clean** glyphs (declassified as resolved via `allow_static_outline` — no outline defect) and **6 genuinely defective** glyphs. These 6 are the only remaining `blocker_residuals` failures.

## Why not automated (evidence)

The repo's reconstruction primitive is `populate_circular_glyphs.py`, which re-imports donor outlines for an **entire family** (no per-glyph mode). Running the full repair _with_ re-import (`repair_circular_sources.py --font all`, without `--skip-import`) was tried with a snapshot safety net. Result:

- Total problem glyphs **rose** (roman 742→764, italic 580→601).
- Previously-clean currency glyphs became interpolation-**broken** (e.g. italic `dollar` → `interpolatable=8`, roman `dollar` → `interpolatable=3`).
- The ligature area-drift turned into interpolatable errors, not a fix.

Conclusion: the live `.glyphs` masters have been hand-refined _beyond_ what the importer produces; a fresh import destroys that refinement. The change was reverted. These 6 need outline-level work a human does in Glyphs, where visual judgement is safe. Snapshots of the pre/post states are in `.baseline-snapshot/`.

## The 6 glyphs

### Group A — f-ligatures (area drift, master outlines don't track donor)

| Glyph | Family | Drift | Risky weights | Note |
| --- | --- | --- | --- | --- |
| `f_f_i` (=`uniFB03`, ﬃ) | roman | 40.33% | 250, 400, 675, 950 | `f_f_i` and `uniFB03` are the same outline — fix once, mirror. |
| `f_f_i` | italic | 58.69% | 100, 250, 400, 675, 950 |  |
| `fi` (ﬁ) | italic | 59.01% | 100, 250, 400, 675, 950 |  |

- **Symptom:** each has matching path counts across masters (interpolation- _compatible_), but the interpolated area drifts 40–59% from the donor static — including at the **Regular(400) master itself**, which means the master outline is not the donor's actual ligature shape.
- **Fix in Glyphs:**
  1. Open `glide-variable.glyphs` / `glide-variable-italic.glyphs`.
  2. For each master (Thin 100 / Regular 400 / ExtraBlack 950), redraw the ligature from the corresponding Circular donor weight so the master outline matches the donor (paste the donor ﬁ/ﬃ outline, keep contour order + start points consistent across masters).
  3. Add **intermediate (brace) layers** at the risky weights `{250}` and `{675}` (the repair pipeline already generates `{250}`/`{675}` UFOs for italic, confirming these are the correction points) so the weight progression tracks the donor instead of interpolating linearly.
  4. roman `f_f_i` and `uniFB03` are identical — fix one, copy to the other.

### Group B — fraction / mark glyphs (single interpolation incompatibility)

| Glyph         | Family | Defect             | Risky weights  |
| ------------- | ------ | ------------------ | -------------- |
| `onequarter`  | italic | `interpolatable=1` | 250, 400, 675  |
| `perthousand` | italic | `interpolatable=1` | (master-level) |

- **Symptom:** one contour-order / start-point / segment incompatibility between masters (one issue each), causing an interpolation error.
- **Fix in Glyphs:** open the glyph, run _Path → Correct Path Direction for all masters_, then verify contour **start points** and **contour order** match across Thin/Regular/ExtraBlack (Glyphs "Show Master Compatibility" view). These are small, surgical fixes — likely a single rotated start point or swapped contour on one master.

## After fixing (verification loop)

For each glyph, after editing the source:

```bash
cd static-to-variable
.venv/bin/python packages/variable-gen/scripts/repair_circular_sources.py --font all --skip-import
npm --workspace @static-to-variable/variable-gen run audit
npm run forge:build
npm --workspace @static-to-variable/variable-gen run residual:blockers   # exit 0 = clean
npm run pipeline:status                                                   # blocker_residuals: pass
```

When a ligature is genuinely fixed, also remove its stale `strategy: manual_review` + `repair_bucket: reconstruction_required` flag in `packages/variable-gen/manifests/circular-triage.json` (or declassify like the 20 clean glyphs if its outline is accepted as-is), so the "manifest marks reconstruction but solver does not" consistency failure clears too.

## Target

`blocker_residuals` goes from 12 failures (6 glyphs) to **0**, at which point the only remaining blocker is the `glyph_forge` convergence backlog (see `02-glyph-forge-convergence.md`).
