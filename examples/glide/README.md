# Glide — worked example

This directory holds the real-world config that drives the Glide build: [`stv.config.json`](./stv.config.json). It is the reference for what a complete `stv.config.json` (schema v3) looks like — a full family with two styles (roman + italic), a weight axis with a named-instance ladder, eight donors per style, three interpolation masters, per-glyph strategies, vertical metrics, and output layout.

Glide is derived from **Circular** (Lineto). **The Circular donor `.otf` files and the `.glyphs` sources are licensed and are NOT included in this repo.** You cannot build Glide without your own licensed copies. This example exists to document the config format, not to ship a buildable font.

## Expected donor layout

Paths in the config resolve against the repo root (`repoRoot: "../.."`). To run the build locally you would need the following, none of which are committed:

```
<repo-root>/
  glide-variable.glyphs              # roman source (styles.roman.source)
  glide-variable-italic.glyphs       # italic source (styles.italic.source)
  cabinet/Circular/
    Circular/                        # roman donors
      Circular-Thin.otf
      Circular-Light.otf
      Circular-Regular.otf
      Circular-Book.otf
      Circular-Medium.otf
      Circular-Bold.otf
      Circular-Black.otf
      Circular-ExtraBlack.otf
    Circular Italic/                 # italic donors
      Circular-ThinItalic.otf
      ... (same eight weights, "Italic" suffix)
```

> **Note on the master cut.** The shipped 3-master build actually reads its master geometry from the corrected **CircularXX** cut (`cabinet/Circular/CircularXX/CircularXX-{Thin,Book,ExtraBlack}.otf`), placed at wght 100 / 400 / 950. This example lists the eight per-weight `Circular` donors (matching `packages/variable-gen/manifests/circular-sources.v2.json`) and maps the three masters onto Thin / Book / ExtraBlack. See the report notes if you need the config to point at the CircularXX files instead.

## Building locally

With the licensed sources in place:

```bash
npm run setup:python          # uv sync
npm run rebuild:glide         # rebuild 3-master sources from donors
npm run build:glide           # export designspace + fontmake -> build/*/*.ttf
```

Release artifacts (TTF + WOFF2) are staged under `packages/variable-gen/build/release/`.
