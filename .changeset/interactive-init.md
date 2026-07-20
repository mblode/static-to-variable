---
"static-to-variable": minor
---

`init` now detects the font files in your folder, reads their real weights and names from each file, and writes an `stv.config.json` that builds without hand editing. Confirm the file list and the family name, then run `build`. Non-interactive shells (CI, agents) still get the starter template, and `build`/`release` docs now lean on the `./stv.config.json` default.
