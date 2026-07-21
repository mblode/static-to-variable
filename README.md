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

Got a variable font and want the individual weights? `static-to-variable split MyFamily-VF.ttf` runs it the other way: one static TTF + WOFF2 per weight, in `static/`.

If anything complains, run `static-to-variable doctor`: it checks Node, Python, uv, and your config, then tells you what to fix.

## Going further

- The config can do much more (italics, named instances, per-glyph fixes). See the [schema](schemas/stv-config.schema.json) and the worked [Inter example](examples/inter).
- Using Claude Code, Cursor, or Codex? `npx skills add mblode/static-to-variable` teaches them the CLI.
- Full command reference, `--json` output, and exit codes: [CLI docs](packages/cli/README.md).

## Font licenses

Converting a font counts as modifying it, and most commercial font EULAs forbid modification even if you never distribute the result. Using this on a commercial font needs written permission from the foundry. Open licenses like the [SIL OFL](https://openfontlicense.org), which covers most of Google Fonts, allow both modification and redistribution of modified versions (watch for Reserved Font Names, which require renaming derivatives). Fonts you made yourself are of course fine. The showcase families on [variable.blode.co](https://variable.blode.co) are all OFL.

## License

The code is [MIT](LICENSE.md). The fonts you build with it keep their own licenses.

---

Crafted by [<img src="https://matthewblode.com/avatar-circle.png" width="20" align="top" />](https://matthewblode.com) [Matthew Blode](https://matthewblode.com)
