---
name: static-to-variable
description: Build a variable font from a set of static font files with the static-to-variable CLI. Covers reading each weight, authoring stv.config.json, running the build, handling glyphs that don't interpolate, and previewing the result. Use when the user wants to "make a variable font from static weights", "combine these OTFs into a variable font", "add a weight axis", "convert static fonts to variable", "use static-to-variable", or "build a wght axis from Thin/Regular/Bold files".
---

# static-to-variable

Turn a set of static font weights (separate OTF/TTF files) into one variable font with a weight axis, using the `static-to-variable` CLI. It rebuilds the glyphs so they interpolate, builds the font with fontmake, and writes the OpenType metadata.

- **IS:** authoring an `stv.config.json`, running the CLI to produce a variable font from static files, and previewing it.
- **IS NOT:** drawing or hinting glyphs, editing an existing variable font, or hand-writing fontTools/fontmake scripts (this CLI wraps that).

## Install

```bash
npm install -g static-to-variable
```

Needs Node >= 24.11, Python >= 3.11, and [uv](https://docs.astral.sh/uv/). Outside a repo checkout the CLI provisions its own Python engine on first `build` (needs uv on PATH). Run `static-to-variable doctor` to confirm the environment.

## Workflow

```text
- [ ] 1. Read each static file's weight (OS/2 usWeightClass)
- [ ] 2. Write stv.config.json (axis + one donor + one master per weight)
- [ ] 3. static-to-variable build --config stv.config.json
- [ ] 4. Verify the output font (fvar axis, named instances, interpolate a mid value)
- [ ] 5. Preview over HTTP with a wght slider
```

### 1. Read the weights, don't guess them

The axis position for each file comes from its `OS/2.usWeightClass`. Read it; static families often use non-standard ranges (e.g. Operator Mono is 275-400, not 100-900):

```bash
uv run --with fonttools python -c "import sys; from fontTools.ttLib import TTFont; [print(f, TTFont(f)['OS/2'].usWeightClass) for f in sys.argv[1:]]" *.otf
```

### 2. Author stv.config.json

`static-to-variable init` scaffolds a starter; edit it. Every path is relative to the config file. One donor and one master per weight; the master's `location.wght` must match that file's weight, and its `donorId` must reference a donor `id`. Exactly one master needs `"default": true`. It is strict JSON: no comments or trailing commas. `source` need not exist yet (it is bootstrapped from the default-master donor).

```json
{
  "version": 3,
  "id": "myfamily",
  "family": {
    "name": "My Family VF",
    "version": "1.000",
    "vendor": "MYCO",
    "designer": "Name",
    "designerUrl": "https://example.com",
    "vendorUrl": "https://example.com"
  },
  "axes": [
    {
      "tag": "wght",
      "name": "Weight",
      "minimum": 100,
      "default": 400,
      "maximum": 900,
      "namedInstances": { "100": "Thin", "400": "Regular", "900": "Black" }
    }
  ],
  "styles": {
    "roman": {
      "italic": false,
      "source": "build/myfamily.glyphs",
      "output": "build/myfamily-vf.ttf",
      "donors": [
        {
          "id": "thin",
          "name": "Thin",
          "path": "donors/MyFamily-Thin.otf",
          "location": { "wght": 100 }
        },
        {
          "id": "regular",
          "name": "Regular",
          "path": "donors/MyFamily-Regular.otf",
          "location": { "wght": 400 }
        },
        {
          "id": "black",
          "name": "Black",
          "path": "donors/MyFamily-Black.otf",
          "location": { "wght": 900 }
        }
      ],
      "masters": [
        { "name": "Thin", "donorId": "thin", "location": { "wght": 100 } },
        {
          "name": "Regular",
          "donorId": "regular",
          "location": { "wght": 400 },
          "default": true
        },
        { "name": "Black", "donorId": "black", "location": { "wght": 900 } }
      ]
    }
  },
  "output": {
    "dir": "build",
    "releaseDir": "build/release",
    "formats": ["ttf", "woff2"]
  }
}
```

Use 2-5 masters. More masters follow the design more closely but demand more glyphs interpolate cleanly. A minimal axis is just the two extremes plus a default.

### 3. Build

```bash
static-to-variable build --config stv.config.json    # rebuild, normalize, build
static-to-variable release --config stv.config.json  # plus finalized metadata + WOFF2
```

`build` bootstraps a `.glyphs` source from the default-master donor when `source` doesn't exist, rebuilds every master from the donors so they share one structure, then builds the font. Read the run output: `reconstructed` glyphs were made interpolatable; `ai-pending` / frozen glyphs could not reconcile (a genuine topology difference across weights) and are held to one master, so they render correctly but don't vary. A handful is normal for independently-drawn statics.

### 4. Verify

```bash
uv run --with fonttools python -c "
from fontTools.ttLib import TTFont; from fontTools.varLib.instancer import instantiateVariableFont; import copy
f=TTFont('build/myfamily-vf.ttf'); print('axes', [(a.axisTag,a.minValue,a.defaultValue,a.maxValue) for a in f['fvar'].axes])
instantiateVariableFont(copy.deepcopy(f), {'wght': (f['fvar'].axes[0].minValue+f['fvar'].axes[0].maxValue)/2}); print('interpolates OK')"
```

### 5. Preview

`file://` blocks `@font-face`, so serve over HTTP. Minimal previewer with a live weight slider:

```html
<style>
  @font-face {
    font-family: VF;
    src: url("build/myfamily-vf.ttf");
  }
  body {
    font-family: VF;
    font-variation-settings: "wght" var(--w, 400);
  }
</style>
<input
  type="range"
  min="100"
  max="900"
  value="400"
  oninput="document.body.style.setProperty('--w',this.value)"
/>
<h1>The quick brown fox 0123456789</h1>
```

```bash
python3 -m http.server 8137   # then open http://localhost:8137/preview.html
```

To show every glyph, read the font's `cmap` and render one cell per codepoint, each using the variable font so the slider reweights them all at once.

## Commands

| Command | What it does |
| --- | --- |
| `init` | Scaffold a starter `stv.config.json`. |
| `build` | Rebuild the masters and build the variable font. |
| `release` | Finalize metadata and write TTF + WOFF2. |
| `doctor` | Report Node, Python, uv, mode (checkout vs standalone), and config. |

`--json` gives machine output; exit codes are `0` ok, `1` failure, `2` usage, `3` environment.

## Gotchas

- **Axis positions are the files' real `usWeightClass`.** Setting `location.wght` to round numbers that don't match the files produces a wrong or collapsed axis.
- **Exactly one master must be `"default": true`.** The bootstrapped source and the fallback for frozen glyphs both come from it.
- **The `source` file does not need to exist** for a brand-new family; it is synthesized from the default-master donor. Point `source`/`output` inside `dir`.
- **Standalone mode provisions a uv venv on first build** (a one-time delay) and caches it; `doctor` shows `mode: standalone` vs `checkout`. It needs uv present.
- **Independently-drawn statics won't all interpolate.** Glyphs with different contour counts or point structure across weights get frozen; that is the tool working, not an error. Check the `underweight` list in the build output.
- **Known quirk (current versions):** the default named instance (e.g. Regular) can ship with a blank name record; the instance still exists in `fvar`.
