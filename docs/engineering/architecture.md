# Architecture

## System shape

`static-to-variable` is one pipeline with three surfaces:

1. `packages/cli` validates user intent and runs stages. It is the only published npm package.
2. `packages/variable-gen` owns font reconstruction, compilation, OpenType finishing, validation, and release output.
3. `apps/web` demonstrates the tool and committed showcase artifacts; it is not part of font compilation.

The private sibling `static-to-variable-glide` owns Glide's licensed donor inputs, durable drawing steps, project config, proofs, and release policy. The public engine must stay family-agnostic.

## Pipeline flow

```text
stv.config.json
  -> donor fonts
  -> rebuild generated Glyphs masters
  -> normalize
  -> export UFO + designspace
  -> fontmake variable TTF
  -> restore layout, kerning, and hinting baseline
  -> validate fidelity and interpolation
  -> release TTF/WOFF2/statics + reports
```

The config's `root` is the project boundary. Donor, source, output, UFO, release, and report paths resolve from it. A workspace may build several projects, so artifact identity is the tuple of project config, engine revision, and input files—not merely a familiar filename.

## Stable seams

- Config and path policy: `packages/variable-gen/src/variable_gen/config.py`
- Per-glyph compatibility: `reconstruct_compatible.py:reconstruct`
- Family and optical-row scheduling: `rebuild.py:rebuild_style`
- Compilation and build gates: `build.py:build_style`
- OpenType layout transfer: `layout.py:attach_layout`
- Final artifact policy: `release.py:release_style`
- User-facing orchestration and exit codes: `packages/cli/src/cli.ts`

Callers should cross these seams rather than duplicate their internal steps. The TypeScript CLI delegates to Python; private family repairs occur before the generic engine compiles the source.

## Determinism and generated data

- Rebuild output is disposable and regenerated from donor inputs. Never treat an edited generated `.glyphs` file as durable source.
- Each optical row reconstructs weight independently, then compatibility is checked across rows. A fake scalar that combines axes is invalid.
- Parallel reconstruction must match serial output exactly. Results are applied in source glyph order, not worker completion order.
- Reports are evidence only when their config root and inputs match the artifact being promoted.
- Licensed donors, generated sources, build directories, reports, and caches remain untracked. Explicit showcase/web fonts are the documented exception.

## Performance model

Per-glyph reconstruction dominates real builds; unit tests and TypeScript checks are comparatively cheap. The current engine recomputes every donor-backed glyph on every `rebuild`, while each glyph's reconstruction is already a pure function. The highest-leverage future optimisation is content-addressed reuse at that seam, keyed by complete donor outlines, axis locations, reference location, strategy, and reconstruction implementation version. A stage-level receipt can then skip UFO/font compilation only when all declared inputs and expected outputs match.

Until those caches exist, use the narrow verification tier during edits, reserve fixture rebuilds for reconstruction changes, and isolate worktree environments so parallel agents do not invalidate one another's editable installs.
