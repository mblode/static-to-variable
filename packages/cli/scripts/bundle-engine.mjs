#!/usr/bin/env node
/**
 * Copies the Python engine into packages/cli/engine/ so `npm pack`/publish can
 * ship it inside the npm package. A globally installed CLI (outside a repo
 * checkout) provisions a managed venv from this bundled copy — see
 * src/python.ts (standalone mode).
 *
 * Source of truth stays in packages/variable-gen and packages/glyph-forge-engine;
 * this only copies. We prune caches, tests, build outputs, and reports to keep
 * the package lean, and we install the two bundled pyprojects together so
 * glyph-forge-engine's `variable-gen` dependency resolves locally (no PyPI).
 */
import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const cliRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  ".."
);
const repoRoot = path.resolve(cliRoot, "../..");
const engineOut = path.join(cliRoot, "engine");

// Directory/file names that never belong in the shipped engine.
const PRUNE = new Set([
  "__pycache__",
  ".venv",
  ".pytest_cache",
  ".turbo",
  "tests",
  "build",
  "reports",
  "public-cache",
  "node_modules",
]);

/** Recursively copy `from` -> `to`, skipping caches, tests, and build junk. */
function copyTree(from, to) {
  cpSync(from, to, {
    recursive: true,
    filter: (src) => {
      const base = path.basename(src);
      if (PRUNE.has(base)) {
        return false;
      }
      return !(base.endsWith(".pyc") || base.endsWith(".tsbuildinfo"));
    },
  });
}

/** Copy a file if it exists; no-op otherwise. */
function copyFile(from, to) {
  if (existsSync(from)) {
    cpSync(from, to);
  }
}

function bundlePackage(name, srcDir, trees, files) {
  const dest = path.join(engineOut, name);
  mkdirSync(dest, { recursive: true });
  for (const tree of trees) {
    const fromTree = path.join(srcDir, tree);
    if (existsSync(fromTree)) {
      copyTree(fromTree, path.join(dest, tree));
    }
  }
  for (const file of files) {
    copyFile(path.join(srcDir, file), path.join(dest, file));
  }
  return dest;
}

rmSync(engineOut, { force: true, recursive: true });
mkdirSync(engineOut, { recursive: true });

bundlePackage(
  "variable-gen",
  path.join(repoRoot, "packages/variable-gen"),
  ["src", "scripts", "manifests"],
  ["pyproject.toml", "README.md"]
);

bundlePackage(
  "glyph-forge-engine",
  path.join(repoRoot, "packages/glyph-forge-engine"),
  ["python"],
  ["pyproject.toml", "README.md"]
);

// glyph-forge-engine depends on `variable-gen` by name. In the monorepo that
// resolves through the root [tool.uv.sources] workspace ref, which is absent in
// the bundled copies. Installing both paths together in one `uv pip install`
// makes the dependency resolve against the local build, so no rewrite is needed
// — but strip any package-level [tool.uv.sources] defensively in case one is
// ever added, since a `workspace = true` ref is meaningless standalone.
stripUvSources(path.join(engineOut, "glyph-forge-engine/pyproject.toml"));

// The MIT license lives at the repo root; copy it into the package so the
// published tarball includes it (packages/cli/package.json `files` lists it).
copyFile(path.join(repoRoot, "LICENSE.md"), path.join(cliRoot, "LICENSE.md"));

console.log(`Bundled engine -> ${path.relative(repoRoot, engineOut)}`);

function stripUvSources(pyproject) {
  if (!existsSync(pyproject)) {
    return;
  }
  const text = readFileSync(pyproject, "utf-8");
  if (!text.includes("[tool.uv.sources]")) {
    return;
  }
  const cleaned = text.replaceAll(
    /\n\[tool\.uv\.sources\][^[]*(?=\n\[|\s*$)/g,
    ""
  );
  writeFileSync(pyproject, cleaned);
}
