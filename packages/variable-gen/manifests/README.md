# Manifests

This directory now contains the active repair manifest for the Circular donor pipeline:

- `circular-triage.json`
- `circular-sources.v2.json`

The manifest controls per-family and per-glyph strategy decisions, including:

- `rebuild_notdef`
- `reference_fallback`
- `manual_review`

It is consumed by:

- `packages/variable-gen/scripts/repair_sources.py`
- `variable_gen.cli inventory`
- `variable_gen.cli compatibility`
- `variable_gen.cli pipeline-status`

`circular-triage.json` remains the current repair-strategy manifest. `circular-sources.v2.json` is the first-principles donor inventory manifest: it lists all eight roman and eight italic static donors, records the live Glide `.glyphs` files as generated repair targets, and is read by the new manifest-driven `inventory` command.

The same source manifest is also used by the raw donor compatibility analyzer. `pipeline-status` does not parse the manifest directly; it reads the generated stage artifacts and reports the promotion verdict.

The broader target manifest shape is described in:

- [first-principles pipeline](../../../docs/static-to-variable-pipeline-first-principles.md)
- [manifest schema](../../../docs/static-to-variable-manifest-schema.md)
