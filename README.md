# static-to-variable

Turn a family of static fonts into one variable font.

[![npm](https://img.shields.io/npm/v/static-to-variable)](https://www.npmjs.com/package/static-to-variable) [![license](https://img.shields.io/npm/l/static-to-variable)](LICENSE.md)

Point it at your static weights with a small config file and it builds a variable font: rebuilding the masters so they interpolate, checking every weight, and writing the OpenType metadata. It also handles static cuts that weren't drawn to interpolate (different contours or point order across weights), which is usually the hard part.

## Install

```bash
npm install -g static-to-variable
```

Needs [Node](https://nodejs.org) 24.11+, [Python](https://www.python.org) 3.11+, and [uv](https://docs.astral.sh/uv/). The Python engine installs itself the first time you build.

## Quick start

```bash
# 1. Scaffold a config in your font project
static-to-variable init

# 2. Edit stv.config.json to point at your static fonts and set the axis

# 3. Build the variable font
static-to-variable build --config stv.config.json
```

Not sure your setup is ready? Run `static-to-variable doctor`.

Want to see it work first? The included example builds a variable font from three static Inter weights:

```bash
static-to-variable build --config examples/minimal/stv.config.json
```

## Configure

Everything font-specific lives in `stv.config.json`: the family name, the weight axis and its named instances, your static fonts and the weight each one maps to, per-glyph fixes, and where to write the output. See the [schema](schemas/stv-config.schema.json) and a full worked [example](examples/glide).

## Commands

| Command   | What it does                                          |
| --------- | ----------------------------------------------------- |
| `init`    | Create a starter `stv.config.json`.                   |
| `build`   | Rebuild the masters, then build the variable font(s). |
| `release` | Finalize the metadata and write TTF + WOFF2.          |
| `doctor`  | Check Node, Python, uv, and your config.              |

`--json` prints machine-readable output; add `--help` to any command for options.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE.md)
