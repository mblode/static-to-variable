# static-to-variable documentation

Product documentation is written in MDX and configured by `docs.json`.

- `index.mdx` introduces the product.
- `quickstart.mdx` covers the first successful build.
- `cli-reference.mdx` documents public commands.
- `engineering/README.md` indexes contributor and agent-facing architecture and verification guidance; it is not part of the product navigation.

BlodeMD owns local preview, validation, and publishing. Its CLI is external to this repository, so install or authenticate it separately before running `blodemd dev`, `blodemd validate`, or `blodemd push`.
