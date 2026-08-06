<div align="center">

# [Static to Variable](https://blode.co/static-to-variable)

**Turn a folder of separate weights into one variable font that slides across everything in between**

Point it at your thin, regular, and bold files and it redraws each weight onto a shared skeleton so the outlines interpolate.

<p align="center">
  <a href="https://www.npmjs.com/package/static-to-variable">
    <img src="https://img.shields.io/npm/v/static-to-variable?style=flat&colorA=000000&colorB=000000" />
  </a>
  <a href="https://github.com/mblode/static-to-variable/blob/main/LICENSE.md">
    <img src="https://img.shields.io/github/license/mblode/static-to-variable?style=flat&colorA=000000&colorB=000000" />
  </a>
</p>

</div>

## Demo

Drag the weight axis on a font built by this pipeline.

<p>
<a href="https://blode.co/static-to-variable">
<img alt="View demo" src=".github/assets/demo.svg" width="200" />
</a>
</p>

## Install

```bash
npm install -g static-to-variable
```

Needs [Node](https://nodejs.org/en) 24.11+, [Python](https://www.python.org) 3.11+, and [uv](https://docs.astral.sh/uv/), which the CLI uses to run the font toolchain.

## Quickstart

From a folder holding your static font files:

```bash
static-to-variable init     # finds the fonts, writes stv.config.json
static-to-variable build    # variable font into build/
static-to-variable release  # final TTF and WOFF2
```

Run `static-to-variable doctor` if a stage fails.

## Commands

| Command                                     | Description                                          |
| ------------------------------------------- | ---------------------------------------------------- |
| `static-to-variable init`                   | Scan the folder for fonts and write `stv.config.json` |
| `static-to-variable build`                  | Build the variable font into `build/`                |
| `static-to-variable release`                | Produce the shippable TTF and WOFF2                  |
| `static-to-variable split MyFamily-VF.ttf`  | Reverse it, one static TTF and WOFF2 per weight step  |
| `static-to-variable doctor`                 | Report readiness: node, python, uv, and config       |
| `static-to-variable status`                 | Print the aggregate pipeline status report           |

## Notes

- Bundling static fonts into one file does not work, because their outlines do not correspond point for point. This redraws them instead, and skips any glyph it cannot convert cleanly rather than shipping a broken interpolation.
- Italics, named instances, and per-glyph fixes are config: see the [schema](schemas/stv-config.schema.json) and the [Inter example](examples/inter).
- Teach your coding agent the CLI with `npx skills add mblode/static-to-variable`.
- The full flag reference lives in the [CLI docs](packages/cli/README.md).

## License

The code is MIT. Your fonts keep their own licenses, and that matters: converting a font counts as modifying it, which most commercial EULAs forbid, so you need the foundry's permission. Open licenses like the [SIL OFL](https://openfontlicense.org) (most of Google Fonts) allow it. Your own fonts are fine.

---

Crafted by [<img src="https://blode.co/avatar-circle.png" width="20" align="top" />](https://blode.co) [Matthew Blode](https://blode.co)
