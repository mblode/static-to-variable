---
"static-to-variable": patch
---

Preserve independently authored optical master rows. Drawing pipelines can content-address source layers with the optical-authorship user-data marker; incomplete rows, incompatible outlines, and unsafe interpolation now fail with named diagnostics instead of silently donor-freezing the drawings.
