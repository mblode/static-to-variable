# Static to variable manifest v2 schema

This draft defines the manifest shape for a static-donor-to-variable pipeline. The manifest is the source of truth for inputs, generated repair targets, build outputs, fallback policy, hashes, and path resolution.

## Goals

- Start from raw static donor fonts.
- Keep generated Glide sources separate from canonical donor inventory.
- Make every fallback, alternate, and frozen glyph decision explicit.
- Make every artifact traceable to manifest version plus source hashes.
- Resolve paths deterministically from the repo root.

## Top-level shape

```json
{
  "$schema": "https://glide.local/schemas/static-to-variable-manifest-v2.json",
  "id": "circular-static-donors",
  "version": 2,
  "repo_root": "../../..",
  "axes": [],
  "families": {},
  "policies": [],
  "artifacts": []
}
```

Required top-level fields:

- `version`: integer, must be `2`.
- `id`: stable identifier for report and artifact freshness checks.
- `repo_root`: path anchor, resolved relative to the manifest file.
- `axes`: variable axis definitions.
- `families`: raw donor inventories grouped by style.

Optional top-level fields:

- `policies`: explicit fallback, alternate, brace, bracket, or frozen-glyph policies.
- `artifacts`: expected outputs produced from this manifest.

## Path resolution

All source paths are repo-root-relative. `repo_root` itself is relative to the manifest file unless it is absolute. Absolute source paths should not be used in portable manifests.

```json
{
  "repo_root": "../../..",
  "families": {
    "italic": {
      "donors": [
        {
          "path": "cabinet/Circular/Circular Italic/Circular-RegularItalic.otf"
        }
      ]
    }
  }
}
```

Paths with spaces, such as `cabinet/Circular/Circular Italic/...`, are stored as literal strings. Consumers must use structured path APIs and must not split on spaces.

## Axes

Axes describe the designspace, donor checkpoints, and generated output metadata.

```json
{
  "tag": "wght",
  "name": "Weight",
  "minimum": 100,
  "default": 400,
  "maximum": 950,
  "donor_values": [250, 300, 400, 450, 500, 700, 900, 950],
  "output_values": [100, 400, 950],
  "map": [
    [250, 250],
    [300, 300],
    [400, 400],
    [450, 450],
    [500, 500],
    [700, 700],
    [900, 900],
    [950, 950]
  ]
}
```

Required fields:

- `tag`: OpenType axis tag.
- `minimum`, `default`, `maximum`: compiled axis bounds.
- `donor_values`: all raw static donor checkpoints to preserve in validation.
- `output_values`: masters or named instances expected in generated outputs.

For Glide/Circular, raw donors start at `250`, while the generated Glide source and compiled axis include a `100` thin master. Keep those separate: `minimum` describes the compiled output axis, `donor_values` describes the raw static checkpoint inventory, and `output_values` describes generated source masters or named output checkpoints.

## Raw donor entries

Raw donors are canonical input files. They are never treated as generated or repair outputs.

```json
{
  "roman": {
    "name": "Circular",
    "style": "roman",
    "donors": [
      {
        "id": "roman-book",
        "name": "Book",
        "path": "cabinet/Circular/Circular/Circular-Book.otf",
        "location": { "wght": 450 },
        "role": "donor",
        "sha256": "optional-expected-sha256"
      }
    ]
  }
}
```

Required donor fields:

- `id`: stable unique donor key.
- `name`: source style/checkpoint name.
- `path`: repo-relative source font path.
- `location`: axis location for this donor.

Optional fields include `role` and expected `sha256`. Glyph counts, cmap counts, metrics metadata, and name records are discovered into inventory reports rather than hand-maintained in the manifest.

## Generated repair targets

Repair targets are derived working sources, generated Glide sources, or build inputs. They must point back to raw donors and repair policies.

```json
{
  "id": "glide-variable-roman",
  "path": "glide-variable.glyphs",
  "role": "generated_repair_target",
  "master_locations": [{ "wght": 100 }, { "wght": 400 }, { "wght": 950 }]
}
```

Required fields:

- `id`: stable generated source key.
- `path`: repo-relative generated or working source path.
- `role`: `generated_repair_target`, `normalized_source`, `build_input`, or another declared generated input role.
- `master_locations`: axis locations represented by the generated source.

## Fallback and alternate policy

No glyph may be frozen, substituted, dropped, or shape-switched implicitly.

```json
{
  "policy_id": "roman-dollar-fallback",
  "scope": {
    "style": "roman",
    "glyphs": ["dollar"]
  },
  "policy_type": "alternate",
  "reason": "continuous_interpolation_wrong_model",
  "axis_ranges": [{ "axis": "wght", "min": 700, "max": 950 }],
  "source": "circular-roman-900",
  "replacement": "dollar.boldAlternate",
  "release_gate": "requires_visual_and_structural_pass",
  "owner": "team-fonts",
  "expires": null
}
```

Allowed `policy_type` values:

- `freeze`: copy one approved outline across a range.
- `alternate`: use an alternate glyph or feature rule.
- `bracket`: switch shape across an axis range.
- `brace`: add an intermediate correction layer.
- `drop`: remove only when coverage policy allows it.
- `manual`: block automation until a reviewed source is provided.

Every policy must include `reason`, `scope`, `source`, `release_gate`, and `owner`. Frozen fallbacks must include an exit criterion or explicit permanent approval.

## Output artifacts

Artifacts describe expected files produced from the manifest. They are checked for freshness against manifest and source hashes.

```json
{
  "artifact_id": "glide-variable-roman-ttf",
  "kind": "variable_font",
  "path": "fonts/glide-variable.ttf",
  "style": "roman",
  "derived_from": ["glide-roman-variable-source"],
  "requires_hashes": [
    "manifest",
    "circular-roman-100",
    "circular-roman-400",
    "circular-roman-950"
  ],
  "validation_report": "packages/variable-gen/reports/audit/roman/build-metadata.json"
}
```

Artifact kinds include:

- `normalized_source`
- `repair_plan`
- `designspace`
- `variable_font`
- `checkpoint_instance`
- `web_font`
- `inventory_report`
- `compatibility_report`
- `validation_summary`
- `glyph_forge_cache`

## Source hashes

Hashes are used for reproducibility and cross-report freshness. Use `sha256` unless a future schema version declares otherwise.

```json
{
  "source_hashes": {
    "manifest": "sha256:...",
    "circular-roman-400": "sha256:...",
    "glide-roman-variable-source": "sha256:..."
  }
}
```

Directory sources must be hashed as a deterministic digest over normalized relative file paths and bytes. Reports and artifacts must record the manifest hash and all source hashes they consumed.
