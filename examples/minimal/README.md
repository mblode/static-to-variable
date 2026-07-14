# Minimal example

A tiny, self-contained project that builds a variable font from three static [Inter](https://github.com/rsms/inter) weights — the generic smoke test that `static-to-variable` works on a non-Glide font, from scratch, with no pre-existing `.glyphs` source.

- `donors/` — Inter Thin/Regular/Black, subset to basic Latin (OFL-1.1, see `donors/OFL.txt`). These are the only committed binaries in the repo.
- `stv.config.json` — a v3 config with paths relative to this directory.
- `build/` — generated output (gitignored): the bootstrapped `minimal.glyphs` source and `minimal-vf.ttf`.

## Build it

```bash
static-to-variable build --config examples/minimal/stv.config.json
# in a checkout: npm run pipeline -- build --config examples/minimal/stv.config.json
```

Because the config's `source` doesn't exist yet, the engine bootstraps a `.glyphs` source from the default-master donor, then rebuilds the masters from all three donors and builds `build/minimal-vf.ttf` (a `wght` 100–900 variable font). This example is also the CI end-to-end fixture.
