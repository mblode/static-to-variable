# Glide — worked example

This directory holds the real-world config that drives the Glide build: [`stv.config.json`](./stv.config.json). It is the reference for what a complete `stv.config.json` (schema v3) looks like — a full family with two styles (roman + italic), a weight axis with a named-instance ladder, three donors and three interpolation masters per style, per-glyph strategies, vertical metrics, and output layout.

Glide is derived from **Circular** (Lineto). **The Circular donor `.otf` files and the `.glyphs` sources are licensed and are NOT included in this repo.** You cannot build Glide without your own licensed copies. This example exists to document the config format, not to ship a buildable font.

## Expected donor layout

Paths in the config resolve against the repo root (`"root": "../.."` in the config). To run the build locally you would need the following, none of which are committed:

```
<repo-root>/
  glide-variable.glyphs              # roman source (styles.roman.source)
  glide-variable-italic.glyphs       # italic source (styles.italic.source)
  cabinet/Circular/CircularXX/       # corrected CircularXX cut, three weights per style
    CircularXX-Thin.otf              # wght 100
    CircularXX-Book.otf              # wght 400 (default master)
    CircularXX-ExtraBlack.otf        # wght 950
    CircularXX-ThinItalic.otf
    CircularXX-BookItalic.otf
    CircularXX-ExtraBlackItalic.otf
```

The `.glyphs` sources are regenerated from the donors by the rebuild (bootstrapped automatically when absent). The separate eight-weight `Circular` donor set listed in `packages/variable-gen/manifests/circular-sources.v2.json` feeds the diagnostic inventory/compatibility reports, not the master geometry.

## Building locally

With the licensed donors in place:

```bash
npm run setup:python          # uv sync
npm run rebuild:glide         # rebuild 3-master sources from donors (+ normalize + build)
npm run build:glide           # or: just export designspace + fontmake -> build/*/*.ttf
```

Release artifacts (TTF + WOFF2) are staged under `packages/variable-gen/build/release/`.
