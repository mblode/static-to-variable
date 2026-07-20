---
"static-to-variable": patch
---

Fix the default (Regular) named instance in `build` output: fontmake leaves its fvar subfamily name empty and its PostScript name truncated (e.g. `Family-`), so font menus showed a blank entry. The name repair that already ran at `release` time now runs on the `build` artifact too.
