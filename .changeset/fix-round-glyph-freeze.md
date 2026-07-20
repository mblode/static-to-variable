---
"static-to-variable": patch
---

Stop round glyphs (o, O, zero and their variants) freezing at one weight for TrueType donors that draw them as all-off-curve contours (e.g. Titillium Web). Such a contour is recorded with no `moveTo` and an implied on-curve endpoint, which the reconstruction's ring parser mis-read as a single point and discarded, forcing a freeze. It now expands the implied on-curve nodes before resampling, and adds a rotation-aligned uniform fallback for round contours whose start points drift across masters. On Titillium Web this cut frozen glyphs from ~39 to 5.
