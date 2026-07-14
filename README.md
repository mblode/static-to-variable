# static-to-variable

Turn a family of static fonts into one variable font.

[![npm](https://img.shields.io/npm/v/static-to-variable)](https://www.npmjs.com/package/static-to-variable)

```bash
npm install -g static-to-variable
```

```bash
static-to-variable init                            # make a config
static-to-variable build --config stv.config.json  # build the font
```

Needs Node 24.11+, Python 3.11+, and [uv](https://docs.astral.sh/uv/). Config options are in the [schema](schemas/stv-config.schema.json), with a worked [example](examples/glide).

[MIT](LICENSE.md)
