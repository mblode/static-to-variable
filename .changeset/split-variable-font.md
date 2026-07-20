---
"static-to-variable": minor
---

Add `static-to-variable split <font>`: the reverse of `build`. Point it at a variable font and it pins each step along the `wght` axis into standalone static weights, writing a TTF + WOFF2 per weight (each named so they install side by side). No config needed; other axes are pinned to their default. Supports `--out`, `--step`, and `--json`.
