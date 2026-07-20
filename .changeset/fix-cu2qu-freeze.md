---
"static-to-variable": patch
---

Stop common glyphs from freezing at one weight in generated variable fonts. The reconstruction step made outlines share a point count but not per-segment structure, so fontmake's cubic→quadratic (cu2qu) conversion then rejected glyphs like `e`, `U`, and `j` as incompatible and the build froze them to a single master (visible as letters stuck thin/heavy while their neighbours varied). Reconstruction now requires an identical per-segment `(op, point-count)` shape across masters and routes anything else through the uniform all-line resample, which is cu2qu-safe. On Kanit this cut build-frozen glyphs from ~37 to 1.
