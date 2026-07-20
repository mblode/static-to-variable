---
"static-to-variable": minor
---

Ship an open-source worked example and slim the pipeline. The reference config is now `examples/inter` (OFL Inter) instead of a proprietary donor set, and `init`/docs point there. The pipeline drops the internal visual-QA layer: `run`/`step`/`list`/`status` now cover the master rebuild, interpolation/full audits, and status report only, and `status` no longer takes `--handoff`/`--top`. Removed the opt-in AI redraw escape hatch; incompatible glyphs keep their deterministic frozen fallback.
