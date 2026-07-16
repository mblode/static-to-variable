---
"static-to-variable": minor
---

Harden the CLI and consolidate on the config-driven pipeline.

- `stv.config.json` is now validated against the published JSON schema (`schemas/stv-config.schema.json`) before any engine work starts. Unknown keys and malformed fields fail fast with the offending path named.
- Invalid configs now exit with code 2 (usage) instead of 1, matching missing configs; `release` validates the config the same way `build` does.
- `build` and `release` support `--json` for a machine-readable summary.
- `NO_COLOR` and piped output are respected everywhere; stage progress goes to stderr while reports and JSON stay on stdout.
- `run --top` rejects 0; interrupted runs exit 130 consistently.
- Error codes cleaned up: new `STV_CONFIG_EXISTS` for `init` collisions and `STV_STATUS_REPORT_MISSING` for absent pipeline reports; dead codes removed.
