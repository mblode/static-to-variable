# static-to-variable

Turn a set of static font weights into one variable font.

[![npm](https://img.shields.io/npm/v/static-to-variable)](https://www.npmjs.com/package/static-to-variable)

You give it your static weights (say Thin, Regular, and Black) and a small config file. It builds a single variable font with a weight axis that interpolates smoothly between them.

The hard part it solves: static fonts are usually drawn independently, so their glyphs don't line up (different numbers of points or contours across weights) and won't interpolate. static-to-variable rebuilds them onto a shared structure so they do, then builds and checks the font for you.

## Install

```bash
npm install -g static-to-variable
```

Needs [Node](https://nodejs.org) 24.11+, [Python](https://www.python.org) 3.11+, and [uv](https://docs.astral.sh/uv/). The font engine sets itself up on first run.

## Use it

```bash
# 1. Create a config
static-to-variable init

# 2. Edit stv.config.json: point it at your static fonts and set the weights

# 3. Build the variable font
static-to-variable build --config stv.config.json
```

Run `static-to-variable doctor` if you want to check your setup first.

## Try the example

Builds a variable font from three static Inter weights, so you can see it work before wiring up your own fonts:

```bash
static-to-variable build --config examples/minimal/stv.config.json
```

## Configure

The `stv.config.json` describes your font: its name, the weight axis and named instances, each static file and the weight it maps to, any per-glyph fixes, and where to write the output. See the [schema](schemas/stv-config.schema.json) and a full worked [example](examples/glide).

## Commands

| Command   | What it does                                     |
| --------- | ------------------------------------------------ |
| `init`    | Create a starter `stv.config.json`.              |
| `build`   | Rebuild the weights and build the variable font. |
| `release` | Finalize the metadata and write TTF + WOFF2.     |
| `doctor`  | Check Node, Python, uv, and your config.         |

Add `--help` to any command for its options, or `--json` for machine-readable output.

## Use with AI agents

Install the skill so Claude Code, Cursor, Codex, and others know how to drive it:

```bash
npx skills add mblode/static-to-variable
```

## License

[MIT](LICENSE.md)
