# static-to-variable

Turn separate font weight files into one variable font.

[![npm](https://img.shields.io/npm/v/static-to-variable)](https://www.npmjs.com/package/static-to-variable)

Got a font as thin, regular, and bold files? Point this at them and get back one file you can slide between. Try it first at [variable.blode.co](https://variable.blode.co): drop your fonts in and build right in the browser, or explore demos built from Google Fonts that never had a variable version.

You can't just merge the files, because each weight is drawn separately and nothing lines up. static-to-variable redraws them onto one shared structure so they blend, checks every letter, and skips anything it can't convert cleanly instead of breaking it.

## Install

```bash
npm install -g static-to-variable
```

Needs [Node](https://nodejs.org) 24.11+, [Python](https://www.python.org) 3.11+, and [uv](https://docs.astral.sh/uv/). The font engine sets itself up the first time you build.

## Use it

Go to a folder with your font files and run:

```bash
static-to-variable init
```

It finds your fonts, reads their weights, and writes an `stv.config.json` for you. Confirm the list, name the family, and then:

```bash
static-to-variable build
```

Done. Your variable font is in `build/`. When you're happy with it, `static-to-variable release` writes the final TTF and WOFF2.

If anything complains, run `static-to-variable doctor`: it checks Node, Python, uv, and your config, then tells you what to fix.

## Going further

- The config can do much more (italics, named instances, per-glyph fixes). See the [schema](schemas/stv-config.schema.json) and the worked [Glide example](examples/glide).
- Using Claude Code, Cursor, or Codex? `npx skills add mblode/static-to-variable` teaches them the CLI.
- Full command reference, `--json` output, and exit codes: [CLI docs](packages/cli/README.md).

## License

[MIT](LICENSE.md)

---

Crafted by [<img src="https://matthewblode.com/avatar-circle.png" width="20" align="top" />](https://matthewblode.com) [Matthew Blode](https://matthewblode.com)
