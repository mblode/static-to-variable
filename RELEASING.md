# Releasing

`static-to-variable` (the `packages/cli` package) publishes to npm via [changesets](https://github.com/changesets/changesets) and GitHub Actions OIDC [trusted publishing](https://docs.npmjs.com/trusted-publishers) — no `NPM_TOKEN`.

## One-time setup (manual, account/repo owner)

These can't be automated and must be done once before the first publish:

1. **Reserve the npm name** — the package is `static-to-variable`. Confirm it's available or owned by you: `npm view static-to-variable` (404 = available).
2. **Configure the npm Trusted Publisher** for the package on npmjs.com → package settings → "Trusted Publisher" → GitHub Actions:
   - Repository: `mblode/static-to-variable`
   - Workflow: `.github/workflows/npm-publish.yml` For a brand-new package name, do one initial manual publish to create it (`cd packages/cli && npm publish --access public`) or create the package shell in the npm UI, then enable the trusted publisher for automated releases.
3. **GitHub repo settings** → Actions → General:
   - Workflow permissions: "Read and write".
   - Enable "Allow GitHub Actions to create and approve pull requests" (changesets opens the "Version Packages" PR).

## Cutting a release

1. Add a changeset for user-facing changes: `npm run changeset` (commit it).
2. Merge to `main`. The Release workflow opens/updates a **Version Packages** PR that bumps the version and updates the changelog.
3. Merge the Version Packages PR. The workflow re-runs and publishes to npm via OIDC with provenance.
4. Verify: `npm view static-to-variable version`.

The initial changeset (`initial-public-release`) is already in `.changeset/`, so the first Version Packages PR will propose `0.1.0`.
