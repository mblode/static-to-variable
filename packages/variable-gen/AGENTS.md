# variable-gen engine

Python engine that reconstructs donor outlines, compiles variable fonts, restores OpenType layout, and emits release artifacts.

## Commands

```bash
uv run pytest -q packages/variable-gen/tests
uv run pytest -q packages/variable-gen/tests/test_rebuild_plan.py
uv run mypy
uv run ruff check packages/variable-gen
uv run ruff format --check packages/variable-gen/src packages/variable-gen/tests

# Real fixture; rebuild mutates its ignored generated source
uv run python -m variable_gen.cli rebuild --config examples/minimal/stv.config.json --style all
uv run python -m variable_gen.cli build --config examples/minimal/stv.config.json --style all
```

## Module contracts

- `config.py` owns config parsing, path resolution, and design-space validation. Do not resolve project paths again in callers.
- `reconstruct_compatible.py:reconstruct` is the pure per-glyph compatibility seam. `rebuild.py` owns family/row scheduling and writes reconstructed layers back to Glyphs sources.
- `build.py` owns fontmake compilation, collapse detection, fidelity checks, layout attachment, and build reports. The CLI stays a thin command adapter.
- `release.py` owns final naming, metadata, and webfont/static outputs. Repairs that must survive every release belong before or inside this stage, not in a manual postprocessor.

## Gotchas

- `rebuild` is destructive to generated `.glyphs` sources. Tests should use temporary projects; production drawings must live in durable donors or an explicitly authored optical stage.
- Rebuilds have no persistent glyph-result cache today: every invocation reconstructs every donor-backed glyph. Use a narrow unit test during edits and run the real fixture only when the reconstruction seam changes.
- The reconstruction worker payload is pure and deterministic. Preserve input ordering and output equivalence when changing parallelism; compare serial and parallel results in `test_rebuild_plan.py`.
- Multi-axis reconstruction runs weight interpolation independently inside each optical row. Never flatten `wght × opsz` coordinates into a fake one-dimensional scalar.
- Fidelity is measured from rendered union area, not raw contour area. Overlapping same-winding contours make raw area comparisons lie.
- A config's `root` is the project boundary. Reports written under one project root must not be mixed with the workspace-root pipeline status from another fixture.
- `build` reuses an existing source. If donors or reconstruction logic changed, run `rebuild` first.

## Performance work

- Benchmark with the committed minimal fixture and report the cold command, worker count, glyph count, and wall time.
- Optimise at the existing pure `reconstruct` seam before splitting the algorithm. Content-addressed per-glyph reuse is safe only when its key covers donor outlines, locations, reference position, reconstruction constants/code version, and configured strategy.
- Keep worktree environments isolated. Sharing a symlinked editable `.venv` causes `uv` to switch the installed source path between concurrent checkouts.

## References

- Architecture: @../../docs/engineering/architecture.md
- Verification: @../../docs/engineering/verification.md
- Engine overview: @README.md
