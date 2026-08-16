# Engineering docs

This is the index for agent and contributor-facing engineering guidance. Product documentation remains in the top-level MDX pages and `docs.json` navigation.

| Document | Trust | Consult when |
| --- | --- | --- |
| [Architecture](architecture.md) | Live | Changing workspace ownership, pipeline stages, project-root behavior, or generated artifacts |
| [Verification](verification.md) | Live | Choosing a test tier, setting up a worktree, or interpreting a green command |
| [Contributing](../../CONTRIBUTING.md) | Live | Preparing a pull request or changeset |
| [Python engine](../../packages/variable-gen/README.md) | Live | Working on reconstruction, compilation, layout, or release behavior |
| [CLI reference](../../packages/cli/README.md) | Live | Changing public commands, flags, JSON output, or exit codes |
| [Schema](../../schemas/stv-config.schema.json) | Live | Adding or changing project configuration |
| [Product docs](../index.mdx) | Live | Editing the published introduction and user journey |

Historical reports and generated pipeline output are deliberately not indexed: rebuild them from the current config instead of treating old artifacts as documentation.
