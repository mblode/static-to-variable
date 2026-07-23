---
"static-to-variable": patch
---

Revert the vertical-metrics normalization added in 0.4.4. It was chasing a text-caret bug that belongs at the client rendering layer, not in font metrics — rewriting ascent/descent/line gap shifted text baselines for consumers and did not reliably fix the caret on real devices. The release step no longer alters vertical metrics; fonts ship their source metrics.
