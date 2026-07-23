---
"static-to-variable": patch
---

Normalize generated vertical metrics so the text caret and default line box hug the glyphs. The release step now rebuilds hhea/OS2 ascent and descent from the font's own ascender/descender ink, zeroes the line gap, sets USE_TYPO_METRICS, and keeps the win box wide enough for accents — fixing the inflated caret that towered above the caps in editors.
