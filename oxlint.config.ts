import { defineConfig } from "oxlint";
import core from "ultracite/oxlint/core";

// We adopt Ultracite's strict `core` ruleset but switch off a small set of
// purely stylistic rules that conflict with conventions this codebase already
// applies consistently. Every correctness / bug-catching rule stays on.
//
//   - func-style / no-use-before-define: the code uses hoisted `function`
//     declarations placed after their call sites (top-down readability). This
//     is a deliberate, consistent style, not a defect.
//   - no-await-in-loop: the pipeline runner awaits stages sequentially on
//     purpose — stages mutate shared sources and must run in order.
//     `Promise.all` here would be a correctness bug.
//   - promise/avoid-new, prefer-await-to-then, prefer-await-to-callbacks:
//     the runner wraps Node's event-based `child_process.spawn` in a Promise,
//     which is the idiomatic way to bridge that callback API.
//   - sort-keys, no-inline-comments, no-nested-ternary, no-negated-condition,
//     require-unicode-regexp, prefer-named-capture-group: cosmetic-only.
//   - unicorn/prefer-import-meta-properties: import.meta.dirname is `undefined`
//     when a script runs under tsx (studio's predev/prebuild, `npm run cli`),
//     so we resolve dirs via fileURLToPath(import.meta.url) instead.
const STYLISTIC_OFF = {
  "unicorn/prefer-import-meta-properties": "off",
  "func-style": "off",
  "no-use-before-define": "off",
  "no-await-in-loop": "off",
  "no-inline-comments": "off",
  "no-nested-ternary": "off",
  "no-negated-condition": "off",
  "sort-keys": "off",
  "require-unicode-regexp": "off",
  "prefer-named-capture-group": "off",
  "unicorn/no-nested-ternary": "off",
  "unicorn/no-negated-condition": "off",
  "promise/avoid-new": "off",
  "promise/prefer-await-to-then": "off",
  "promise/prefer-await-to-callbacks": "off",
} as const;

export default defineConfig({
  extends: [core],
  ignorePatterns: [
    ...core.ignorePatterns,
    "packages/cli/engine/**",
    "**/.pipeline-jobs/**",
  ],
  rules: STYLISTIC_OFF,
});
