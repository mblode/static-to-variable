# static-to-variable

Turn separate font weight files into one variable font.

[![npm](https://img.shields.io/npm/v/static-to-variable)](https://www.npmjs.com/package/static-to-variable)

Got a font as thin, regular, and bold files? Point this at them and get back one file you can slide between. Or try it in your browser at [variable.blode.co](https://variable.blode.co), with live demos built from Google Fonts that never had a variable version.

Normally you can't just merge the files because they don't line up: each weight is drawn separately. static-to-variable redraws them onto one shared structure so they blend, checks every letter, and skips anything it can't do cleanly instead of breaking it.

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

Add `--help` to any command for its options. `build`, `release`, and `doctor` take `--json` for a machine-readable summary on stdout (human progress always goes to stderr).

Your config is validated against the [published schema](schemas/stv-config.schema.json) before any work starts: unknown keys and malformed fields fail fast with the offending path named.

Exit codes: `0` success, `1` a pipeline step failed, `2` usage (bad flag, missing or invalid config), `3` environment not ready (no Python/uv), `130` interrupted.

## Use with AI agents

Install the skill so Claude Code, Cursor, Codex, and others know how to drive it:

```bash
npx skills add mblode/static-to-variable
```

## License

[MIT](LICENSE.md)
