# Inter — worked example

This directory holds a complete `stv.config.json` (schema v3) built on [Inter](https://github.com/rsms/inter) — the reference for what a full config looks like: a family with two styles (roman + italic), a weight axis with a named-instance ladder, three donors and three interpolation masters per style, a per-glyph strategy, vertical metrics, and output layout.

Inter is licensed under the [SIL Open Font License](https://openfontlicense.org), so unlike a proprietary donor set you can download the static weights and build this example yourself. For a tiny, already-buildable variant with committed subset donors, see [`examples/minimal`](../minimal).

## Donor layout

Paths in the config resolve against this directory. Download the static instances from an [Inter release](https://github.com/rsms/inter/releases) and drop them in `donors/`:

```
examples/inter/
  donors/
    Inter-Thin.ttf          # wght 100
    Inter-Regular.ttf       # wght 400 (default master)
    Inter-Black.ttf         # wght 900
    Inter-ThinItalic.ttf
    Inter-Italic.ttf
    Inter-BlackItalic.ttf
```

The `.glyphs` sources under `build/` are bootstrapped from the default-master donor on first run, so you do not need to supply them.

## Build it

```bash
static-to-variable build --config examples/inter/stv.config.json
# in a checkout: npm run pipeline -- build --config examples/inter/stv.config.json
```

Output lands in `build/` (`inter-vf.ttf` plus the italic), and `static-to-variable release` stages the final TTF + WOFF2 under `build/release/`.
