# Static to variable report contracts

This document defines the JSON contracts emitted by `variable-gen` and consumed by `glyph-forge`. `variable-gen` owns report generation. `glyph-forge` reads reports, renders evidence, scores visuals, and emits its own freshness metadata without writing back to `variable-gen` reports.

Most stage reports include:

- `schema_version`: report schema version.
- `report_type`: one of the report types below.
- `manifest_id` and `manifest_hash`.
- `source_hashes`: IDs and hashes consumed by the report.
- `generated_at`: UTC timestamp when a report is intentionally time-stamped. Deterministic snapshot reports may omit this field when freshness is proven entirely by manifest and source hashes.
- `generator`: tool name, version, and command when available.
- `family_id` and `style` when report scope is family-specific.

`pipeline_status` is an aggregate report over other reports. It includes its own `hard_gates` envelope and stage artifact paths, but it does not duplicate every source hash from every consumed report.

## Inventory report

Purpose: describe raw donor coverage before normalization or repair.

Required fields:

- `report_type`: `inventory`.
- `families`: family-keyed raw donor entries with donor ID, path, axis location, source hash, glyph count, cmap count, metrics summary, name summary, glyph coverage, cmap coverage, and generated repair targets.
- `source_hashes`: donor ID to source hash map.
- `summary`: family counts, donor counts, missing donors, and warning counts.
- `hard_gates`: inventory gate fields described below.

Minimum hard gate fields:

- `missing_required_donors`
- `unreadable_donors`
- `hash_mismatch`

Donor axis locations and path shapes are validated when the manifest is loaded, so the inventory gate does not repeat those checks.

## Compatibility report

Purpose: classify glyph-level structural compatibility before and after normalization or repair.

Required fields:

- `report_type`: `compatibility`.
- `stage`: `raw`, `normalized`, `repaired`, or `built_checkpoint`.
- `families`: family-keyed records. Each family has `donors`, `glyphs`, and `summary`.
- `summary`: aggregate counts across all families.
- `hard_gates`: compatibility gate fields described below.

Per-glyph records must include:

- `glyph_name`
- `status`: `pass`, `warning`, `blocked`, or `not_applicable`.
- `severity`: `P0`, `P1`, or `P2`.
- `issue_count`
- `issue_type_counts`
- `issues`: normalized `fontTools.varLib.interpolatable` issue records. Later analyzer phases may add custom `checks`, `evidence`, and `policy_id` fields, but the raw donor analyzer does not invent those yet.

Minimum hard gate fields:

- `p0_blocker_count`
- `unapproved_fallback_count`
- `missing_policy_count`
- `interpolatable_error_count`
- `phantom_point_error_count`

## Repair plan

Purpose: declare planned repairs, substitutions, alternates, and blocked glyphs before mutation or build.

Required fields:

- `report_type`: `repair_plan`.
- `plan_id`
- `input_stage`
- `output_stage`
- `actions`: ordered repair action records.
- `blocked_glyphs`
- `reconstruction_required`
- `hard_gates`: repair-planning gate fields described below.

Repair action records must include:

- `action_id`
- `glyph_name`
- `action_type`: `contour_assignment`, `start_point_rotation`, `winding_normalization`, `segment_coercion`, `node_split`, `brace_layer`, `alternate`, `freeze`, `drop`, or `manual`.
- `source_ids`
- `expected_output_target`
- `safety`: `safe`, `review`, or `blocked`.
- `policy_id` when the action uses fallback or alternate behavior.

Minimum hard gate fields:

- `blocked_action_count`
- `unsafe_auto_action_count`
- `fallback_without_policy_count`
- `reconstruction_required_count`

## Build metadata

Purpose: prove which inputs produced designspaces, checkpoint instances, and compiled variable fonts.

Required fields:

- `report_type`: `build_metadata`.
- `build_id`
- `inputs`: manifest, donors, generated sources, repair plans, and hashes.
- `outputs`: designspaces, variable fonts, checkpoint instances, web fonts, and hashes.
- `axis_metadata`: `fvar`, `avar`, `STAT`, named instances, and axis bounds.
- `font_metadata`: relevant `name`, `OS/2`, `hhea`, cmap, glyph order, and metrics summary.
- `commands`: build commands and tool versions when available.
- `hard_gates`: build gate fields described below.

Minimum hard gate fields:

- `build_failed`
- `output_missing`
- `metadata_mismatch`
- `checkpoint_extraction_failed`
- `artifact_hash_missing`

## Validation summary

Purpose: summarize release gates across structure, donor fidelity, interior quality, metadata, and freshness.

Required fields:

- `report_type`: `validation_summary`.
- `candidate_id`
- `build_id`
- `gate_status`: `pass`, `fail`, or `review`.
- `gate_results`: structural compatibility, donor fidelity, interior quality, compiled metadata, artifact freshness, and glyph-forge visual gate.
- `thresholds`: names and values used by validators.
- `exceptions`: approved P1/P2 exceptions with policy IDs and owners.
- `hard_gates`: validation gate fields described below.

Minimum hard gate fields:

- `p0_blocker_count`
- `donor_fidelity_failure_count`
- `interior_quality_failure_count`
- `metadata_failure_count`
- `freshness_failure_count`
- `glyph_forge_failure_count`

## Glyph-forge visual score and freshness metadata

Purpose: let `glyph-forge` publish visual evidence and freshness status against the exact `variable-gen` inputs it read.

Required fields:

- `report_type`: `glyph_forge_visual_scores`.
- `input_reports`: paths and hashes for consumed `variable-gen` reports.
- `manifest_id` and `manifest_hash`.
- `source_hashes`: copied from consumed reports.
- `score_set_id`
- `render_profile`: renderer version, sample weights, image dimensions, and comparison settings.
- `glyph_scores`: per-glyph visual score records.
- `freshness`: hash comparison status against manifest, reports, built fonts, and rendered cache.
- `hard_gates`: glyph-forge gate fields described below.

Per-glyph visual score records must include:

- `glyph_name`
- `weights_sampled`
- `score`
- `status`: `pass`, `warning`, `fail`, or `stale`.
- `failure_reasons`
- `evidence_paths`
- `linked_policy_id` when the glyph uses a fallback or alternate.

Minimum hard gate fields:

- `stale_input_report_count`
- `stale_render_count`
- `missing_render_count`
- `visual_failure_count`
- `coverage_gap_count`

## Pipeline status

Purpose: provide the coherent promotion surface over all stage artifacts.

Required fields:

- `report_type`: `pipeline_status`.
- `verdict`: `pass` or `fail`.
- `summary`: stage counts, blocking stage counts, blocking failure counts, and diagnostic failure counts.
- `stages`: ordered stage records.
- `hard_gates`: aggregate promotion gate.

Stage records must include:

- `id`
- `name`
- `kind`: `blocking` or `diagnostic`.
- `status`: `pass`, `fail`, `missing`, or `invalid`.
- `blocking`: boolean used by the aggregate verdict.
- `artifact`: repo-relative path to the source artifact for that stage.
- `failures`: blocking stage reasons.
- `observations`: non-blocking diagnostic reasons.
- `summary`: compact counters for the stage.

Current stages:

- `inventory`: blocking donor inventory gate.
- `raw_compatibility`: diagnostic raw donor compatibility map.
- `repair_build`: blocking strict source/build gate.
- `full_audit`: diagnostic full audit summary.
- `blocker_residuals`: blocking tracked residual glyph gate.
- `glyph_forge`: blocking visual QA verdict gate.

## Hard gate object

Every report uses the same hard gate envelope so CI, local scripts, and glyph-forge can make consistent decisions.

```json
{
  "hard_gates": {
    "status": "fail",
    "fields": {
      "p0_blocker_count": 3,
      "freshness_failure_count": 0
    },
    "blocking_reasons": [
      {
        "field": "p0_blocker_count",
        "value": 3,
        "threshold": 0,
        "message": "P0 blockers must be resolved before build promotion."
      }
    ]
  }
}
```

Required gate envelope fields:

- `status`: `pass`, `fail`, or `review`.
- `fields`: machine-readable gate counters or booleans.
- `blocking_reasons`: list of failed fields with observed value, threshold, and message.

Reports may add non-blocking `warnings`, but blocking state must be expressible only through `hard_gates`.
