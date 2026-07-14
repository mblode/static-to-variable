#!/usr/bin/env tsx
/**
 * Mirror packages/glyph-forge-engine/public-cache/svg/ and manifests/broken-glyphs.json
 * into apps/studio/public/ before dev or build.
 *
 * Runs as predev/prebuild. Idempotent.
 */
import { cp, mkdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Computed via fileURLToPath (not import.meta.dirname) because this script runs
// under tsx, where import.meta.dirname is undefined.
const appRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  ".."
);
const repoRoot = path.resolve(appRoot, "..", "..");

const enginePackageRoot = path.resolve(
  repoRoot,
  "packages",
  "glyph-forge-engine"
);
const engineCache = path.resolve(enginePackageRoot, "public-cache", "svg");
const engineManifest = path.resolve(
  enginePackageRoot,
  "manifests",
  "broken-glyphs.json"
);
const engineGlyphScores = path.resolve(
  enginePackageRoot,
  "manifests",
  "glyph-scores.json"
);
const engineCellScores = path.resolve(
  enginePackageRoot,
  "manifests",
  "cell-scores.json"
);
const engineSuggestions = path.resolve(
  enginePackageRoot,
  "manifests",
  "strategy-suggestions.json"
);
const engineSolverResults = path.resolve(
  enginePackageRoot,
  "manifests",
  "solver-results.json"
);
const variableGenReports = path.resolve(
  repoRoot,
  "packages",
  "variable-gen",
  "reports"
);
const variableGenPipelineStatus = path.resolve(
  variableGenReports,
  "pipeline-status.json"
);
const variableGenBlockerResiduals = path.resolve(
  variableGenReports,
  "repair",
  "blocker-residual-validation.md"
);

const targetSvgDir = path.resolve(appRoot, "public", "svg");
const targetManifest = path.resolve(appRoot, "public", "broken-glyphs.json");
const targetGlyphScores = path.resolve(appRoot, "public", "glyph-scores.json");
const targetCellScores = path.resolve(appRoot, "public", "cell-scores.json");
const targetSuggestions = path.resolve(
  appRoot,
  "public",
  "strategy-suggestions.json"
);
const targetSolverResults = path.resolve(
  appRoot,
  "public",
  "solver-results.json"
);
const targetPipelineStatus = path.resolve(
  appRoot,
  "public",
  "pipeline-status.json"
);
const targetBlockerResiduals = path.resolve(
  appRoot,
  "public",
  "blocker-residual-validation.md"
);

async function exists(filePath: string): Promise<boolean> {
  try {
    await stat(filePath);
    return true;
  } catch {
    return false;
  }
}

async function main() {
  await mkdir(path.resolve(appRoot, "public"), { recursive: true });
  const hasManifest = await exists(engineManifest);

  if (await exists(engineCache)) {
    await cp(engineCache, targetSvgDir, { force: true, recursive: true });
    console.log(`studio: synced SVG cache → ${targetSvgDir}`);
  } else {
    console.warn(
      `studio: no SVG cache at ${engineCache} yet. Grid will render missing-thumbnail placeholders until you run \`npm run forge:build\`.`
    );
  }

  if (hasManifest) {
    await cp(engineManifest, targetManifest, { force: true });
    console.log(`studio: synced manifest → ${targetManifest}`);
  } else {
    await writeFile(targetManifest, "[]\n", "utf-8");
    console.warn(
      `studio: no manifest at ${engineManifest}; wrote an empty UI manifest. Run \`npm run forge:build\` after pipeline outputs exist.`
    );
  }

  for (const [src, dst, label] of [
    [engineGlyphScores, targetGlyphScores, "glyph-scores"],
    [engineCellScores, targetCellScores, "cell-scores"],
    [engineSuggestions, targetSuggestions, "strategy-suggestions"],
    [engineSolverResults, targetSolverResults, "solver-results"],
    [variableGenPipelineStatus, targetPipelineStatus, "pipeline-status"],
    [
      variableGenBlockerResiduals,
      targetBlockerResiduals,
      "blocker-residual-validation",
    ],
  ] as const) {
    if (await exists(src)) {
      await cp(src, dst, { force: true });
      console.log(`studio: synced ${label} → ${dst}`);
    } else {
      console.log(
        `studio: no ${label} at ${src} (optional — run \`npm run forge:build\` to generate)`
      );
    }
  }
}

main().catch((error) => {
  console.error("studio: sync failed");
  console.error(error);
  process.exit(1);
});
