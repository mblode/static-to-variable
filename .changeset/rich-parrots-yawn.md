---
"static-to-variable": minor
---

Keep kerning weight-aware and give the output a rasterizer baseline.

Builds preferred a whole-table `varLib` merge of the donors' layout and fell back — silently — to a static port whenever that merge refused. It refused often, and for reasons that had nothing to do with kerning: independently compiled statics disagree about `aalt` alternate sets and mark-glyph-set coverage, neither of which can vary by weight. Every such font shipped with Bold rendering Regular's kern values.

There is now a tier between the two. It ports the default donor's layout as before, then varies just the kern values from the other donors, reading values rather than structure — so the donors can disagree about anything else and the kerning still tracks the axis. Builds report it as `layout: variable-kern`.

Output also gets a `gasp` table and a `prep` program with dropout control, matching Google Fonts' baseline for variable fonts. Set `output.hinting` to `"none"` to opt out.

A new `layout` promotion gate compares each build against its donor and blocks on a lost feature tag, dropped kern pairs, a dropped GDEF, no layout at all, kerning frozen while the donors carry it, or a missing hinting baseline. It judges built output, so a project that has not built yet is reported rather than blocked. The build writes `reports/layout-report.json` for it, and `build --json` now carries the layout tier and hinting summary.
