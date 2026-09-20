# Product documentation

The published docs are MDX pages configured by `docs/docs.json`. Engineering guidance lives under `docs/engineering` and is not part of the product-doc navigation.

## Checks

- Run `npm run verify` from the repository root for code examples and repository integrity.
- The BlodeMD CLI is not installed by this repository. Do not claim `blodemd dev`, `validate`, or `push` passed unless the external CLI is available and the command was actually run.

## Conventions

- Use active voice, second person, concise sentences, and sentence-case headings.
- Bold interface labels; wrap commands, paths, fields, and code identifiers in backticks.
- Update `docs.json` when navigation or branding changes.
- Keep implementation and contributor detail in `docs/engineering` or `CONTRIBUTING.md`, then link to it rather than duplicating it in product pages.
- Do not publish licensed donor paths or private Glide pipeline details.

## References

- Engineering index: @engineering/README.md
- Public CLI behavior: @../packages/cli/README.md
- Public project overview: @../README.md
