import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";

import {
  createGenerationJob,
  getRepoRoot,
  readGenerationJob,
  requiredGenerationSourcePaths,
  resolveArtifactPath,
} from "../lib/generation.server";

const REQUIRED_ARTIFACTS = [
  "roman-variable-ttf",
  "italic-variable-ttf",
  "pipeline-status-json",
  "reconstruction-report-json",
] as const;

async function main(): Promise<void> {
  const jobIdArg = valueAfter("--job-id");
  const jobId = jobIdArg ?? (await createAndRunStrictJob());
  const job = await readGenerationJob(jobId);

  if (!["succeeded", "needs_review"].includes(job.status)) {
    throw new Error(
      `Generation job ${job.id} ended with status ${job.status}: ${job.error ?? "no error"}`
    );
  }

  for (const artifactId of REQUIRED_ARTIFACTS) {
    const { artifact, path: artifactPath } = await resolveArtifactPath(
      job.id,
      artifactId
    );
    const sha256 = await sha256File(artifactPath);
    if (artifact.sha256 && artifact.sha256 !== sha256) {
      throw new Error(
        `${artifact.id} hash mismatch: ${artifact.sha256} != ${sha256}`
      );
    }
    console.log(
      `${artifact.id}: ${artifact.fileName} ${artifact.size} bytes sha256=${sha256}`
    );
  }

  await validateFonts(job.id);
  if (job.status === "needs_review") {
    await resolveArtifactPath(job.id, "blocker-residuals-md");
    console.log("review boundary: residual blocker report is present");
  }

  console.log(
    `generation smoke passed: ${job.id} status=${job.status} verdict=${job.pipelineVerdict ?? "unknown"}`
  );
}

async function createAndRunStrictJob(): Promise<string> {
  const repoRoot = getRepoRoot();
  const files: File[] = [];
  for (const targetPath of requiredGenerationSourcePaths()) {
    const source = path.join(repoRoot, targetPath);
    if (!existsSync(source)) {
      throw new Error(`Missing required local smoke input: ${targetPath}`);
    }
    const bytes = await readFile(source);
    files.push(new File([bytes], path.basename(targetPath)));
  }

  const job = await createGenerationJob({ files, useWorkspaceSources: false });
  console.log(
    `created strict generation job ${job.id} with ${files.length} source files`
  );

  const command = process.platform === "win32" ? "npm.cmd" : "npm";
  const result = spawnSync(
    command,
    [
      "--workspace",
      "@static-to-variable/studio",
      "run",
      "generation:run",
      "--",
      job.id,
    ],
    { cwd: repoRoot, stdio: "inherit" }
  );
  if (result.status !== 0) {
    throw new Error(
      `generation runner exited with ${result.status ?? "unknown"}`
    );
  }
  return job.id;
}

async function validateFonts(jobId: string): Promise<void> {
  const roman = await resolveArtifactPath(jobId, "roman-variable-ttf");
  const italic = await resolveArtifactPath(jobId, "italic-variable-ttf");
  const repoRoot = getRepoRoot();
  const python = path.join(repoRoot, ".venv", "bin", "python");
  const code = `
import sys
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

for font_path in sys.argv[1:]:
    font = TTFont(font_path)
    axes = {axis.axisTag: (axis.minValue, axis.defaultValue, axis.maxValue) for axis in font["fvar"].axes}
    assert "wght" in axes, f"{font_path}: missing wght axis"
    lo, default, hi = axes["wght"]
    assert lo <= 100 <= hi and lo <= 400 <= hi and lo <= 950 <= hi, f"{font_path}: bad wght axis {axes['wght']}"
    for weight in (100, 400, 950):
        fresh = TTFont(font_path)
        instantiateVariableFont(fresh, {"wght": weight}, inplace=False)
print("font validation ok")
`;
  const result = spawnSync(python, ["-c", code, roman.path, italic.path], {
    cwd: repoRoot,
    encoding: "utf-8",
  });
  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || "font validation failed");
  }
  process.stdout.write(result.stdout);
}

async function sha256File(filePath: string): Promise<string> {
  return createHash("sha256")
    .update(await readFile(filePath))
    .digest("hex");
}

function valueAfter(flag: string): string | undefined {
  const index = process.argv.indexOf(flag);
  return index === -1 ? undefined : process.argv[index + 1];
}

void main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
