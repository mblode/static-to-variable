import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import {
  copyFile,
  cp,
  mkdir,
  readFile,
  rm,
  stat,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import type {
  GenerationArtifact,
  GenerationJob,
  GenerationStageId,
  GenerationStageRun,
} from "../lib/generation-types";
import {
  appendGenerationLog,
  formatMissingRequiredTargets,
  getJobDir,
  getJobsRoot,
  getRegisteredTargetInputs,
  getRepoRoot,
  missingRequiredTargets,
  readGenerationJob,
  writeJob,
} from "../lib/generation.server";

const MAX_AUTO_CONVERGENCE_PASSES = 5;

interface CommandResult {
  code: number;
  output: string;
}

const COMMANDS = {
  applyTriage: [
    "npm",
    "--workspace",
    "@static-to-variable/glyph-forge-engine",
    "run",
    "apply",
  ],
  audit: [
    "npm",
    "--workspace",
    "@static-to-variable/variable-gen",
    "run",
    "audit",
  ],
  auditInterpolation: [
    "npm",
    "--workspace",
    "@static-to-variable/variable-gen",
    "run",
    "audit:interpolation",
  ],
  autoStage: [
    "npm",
    "--workspace",
    "@static-to-variable/glyph-forge-engine",
    "run",
    "auto-stage",
  ],
  autoStageDryRun: [
    "npm",
    "--workspace",
    "@static-to-variable/glyph-forge-engine",
    "run",
    "auto-stage",
    "--",
    "--dry-run",
  ],
  glyphForge: [
    "npm",
    "--workspace",
    "@static-to-variable/glyph-forge-engine",
    "run",
    "qa:build",
  ],
  inventory: [
    "npm",
    "--workspace",
    "@static-to-variable/variable-gen",
    "run",
    "inventory",
  ],
  pipelineStatus: [
    "npm",
    "--workspace",
    "@static-to-variable/variable-gen",
    "run",
    "pipeline:status",
  ],
  rawCompatibility: [
    "npm",
    "--workspace",
    "@static-to-variable/variable-gen",
    "run",
    "compatibility:raw",
  ],
  repairSkipImport: [
    "npm",
    "--workspace",
    "@static-to-variable/variable-gen",
    "run",
    "repair:skip-import",
  ],
  repairWithImport: [
    "npm",
    "--workspace",
    "@static-to-variable/variable-gen",
    "run",
    "repair",
  ],
  residualBlockers: [
    "npm",
    "--workspace",
    "@static-to-variable/variable-gen",
    "run",
    "residual:blockers",
  ],
} as const;

const OUTPUTS = [
  {
    contentType: "font/ttf",
    destination: "fonts/glide-variable-vf.ttf",
    id: "roman-variable-ttf",
    label: "Roman variable TTF",
    source: "packages/variable-gen/build/roman/glide-variable-vf.ttf",
  },
  {
    contentType: "font/ttf",
    destination: "fonts/glide-variable-italic-vf.ttf",
    id: "italic-variable-ttf",
    label: "Italic variable TTF",
    source: "packages/variable-gen/build/italic/glide-variable-italic-vf.ttf",
  },
  {
    contentType: "application/json",
    destination: "reports/pipeline-status.json",
    id: "pipeline-status-json",
    label: "Pipeline status JSON",
    source: "packages/variable-gen/reports/pipeline-status.json",
  },
  {
    contentType: "text/markdown; charset=utf-8",
    destination: "reports/pipeline-status.md",
    id: "pipeline-status-md",
    label: "Pipeline status Markdown",
    source: "packages/variable-gen/reports/pipeline-status.md",
  },
  {
    contentType: "application/json",
    destination: "reports/repair-run-summary.json",
    id: "repair-summary-json",
    label: "Repair summary JSON",
    source: "packages/variable-gen/reports/repair/repair-run-summary.json",
  },
  {
    contentType: "text/markdown; charset=utf-8",
    destination: "reports/blocker-residual-validation.md",
    id: "blocker-residuals-md",
    label: "Residual review",
    source:
      "packages/variable-gen/reports/repair/blocker-residual-validation.md",
  },
  {
    contentType: "text/markdown; charset=utf-8",
    destination: "reports/audit-overview.md",
    id: "audit-overview-md",
    label: "Audit overview",
    source: "packages/variable-gen/reports/audit/audit-overview.md",
  },
  {
    contentType: "application/json",
    destination: "reports/broken-glyphs.json",
    id: "broken-glyphs-json",
    label: "Glyph QA manifest",
    source: "packages/glyph-forge-engine/manifests/broken-glyphs.json",
  },
] as const;

async function main(): Promise<void> {
  const jobId = process.argv.at(2);
  if (!jobId) {
    throw new Error("Usage: tsx scripts/run-generation-job.ts <jobId>");
  }

  let job = await readGenerationJob(jobId);
  try {
    await log(job.id, `generation job ${job.id} started\n`);
    job.status = "running";
    job.startedAt = new Date().toISOString();
    job.updatedAt = job.startedAt;
    await writeJob(job);

    const isolatedRepoPath = path.join(
      tmpdir(),
      "static-to-variable-generation-jobs",
      job.id,
      "repo"
    );
    job.isolatedRepoPath = isolatedRepoPath;

    await runStage(job, "prepare_workspace", async () => {
      await prepareIsolatedRepo(isolatedRepoPath);
      return `workspace ready at ${isolatedRepoPath}`;
    });

    await runStage(job, "install_inputs", async () => {
      const installed = await installInputs(job, isolatedRepoPath);
      if (installed === 0) {
        return job.useWorkspaceSources
          ? "no uploaded source targets; using isolated workspace sources"
          : "no uploaded source targets";
      }
      return `installed ${installed} uploaded source target${installed === 1 ? "" : "s"}${job.useWorkspaceSources ? "; missing targets use isolated workspace sources" : ""}`;
    });

    await runCommandStage(
      job,
      "inventory",
      isolatedRepoPath,
      COMMANDS.inventory
    );
    await runCommandStage(
      job,
      "raw_compatibility",
      isolatedRepoPath,
      COMMANDS.rawCompatibility
    );
    await runCommandStage(
      job,
      "repair_build",
      isolatedRepoPath,
      COMMANDS.repairWithImport
    );
    await runCommandStage(
      job,
      "audit_interpolation",
      isolatedRepoPath,
      COMMANDS.auditInterpolation
    );
    await runCommandStage(job, "full_audit", isolatedRepoPath, COMMANDS.audit);
    await runCommandStage(
      job,
      "glyph_forge",
      isolatedRepoPath,
      COMMANDS.glyphForge
    );

    await runStage(job, "auto_convergence", async (stage) => {
      stage.command = "auto-stage/apply/repair/audit loop";
      return await autoConverge(job, isolatedRepoPath);
    });

    await runReviewableCommandStage(
      job,
      "blocker_residuals",
      isolatedRepoPath,
      COMMANDS.residualBlockers
    );
    await runCommandStage(
      job,
      "pipeline_status",
      isolatedRepoPath,
      COMMANDS.pipelineStatus
    );

    await runStage(job, "collect_outputs", async () => {
      const artifacts = await collectOutputs(job, isolatedRepoPath);
      job.artifacts = artifacts;
      const status = await readPipelineStatus(isolatedRepoPath);
      const reviewRequired =
        job.status === "needs_review" || statusNeedsReview(status);
      job.pipelineVerdict =
        reviewRequired || status.verdict !== "pass" ? "fail" : "pass";
      if (job.pipelineVerdict !== "pass") {
        job.status = reviewRequired ? "needs_review" : "failed";
        job.error ??= summarizePipelineFailure(status);
      }
      return `collected ${artifacts.length} artifact${artifacts.length === 1 ? "" : "s"}`;
    });

    if (job.status === "running") {
      job.status = "succeeded";
    }
    job.finishedAt = new Date().toISOString();
    job.updatedAt = job.finishedAt;
    await writeJob(job);
    await log(job.id, `generation job ${job.id} ${job.status}\n`);
  } catch (error) {
    job = await readGenerationJob(jobId).catch(() => job);
    const message = error instanceof Error ? error.message : String(error);
    const running = job.stages.find((stage) => stage.status === "running");
    if (running) {
      running.status = "failed";
      running.error = message;
      running.finishedAt = new Date().toISOString();
    }
    job.status = "failed";
    job.error = message;
    job.finishedAt = new Date().toISOString();
    job.updatedAt = job.finishedAt;
    await writeJob(job);
    await log(job.id, `generation job ${job.id} failed: ${message}\n`);
    process.exitCode = 1;
  }
}

async function prepareIsolatedRepo(destination: string): Promise<void> {
  const repoRoot = getRepoRoot();
  const jobsRoot = path.resolve(getJobsRoot());
  await rm(destination, { force: true, recursive: true });
  await mkdir(path.dirname(destination), { recursive: true });

  await cp(repoRoot, destination, {
    dereference: false,
    filter: (source) => shouldCopyPath(source, repoRoot, jobsRoot),
    recursive: true,
  });

  await linkIfPresent(
    path.join(repoRoot, "node_modules"),
    path.join(destination, "node_modules")
  );
  await linkIfPresent(
    path.join(repoRoot, ".venv"),
    path.join(destination, ".venv")
  );
  await writeFile(
    path.join(
      destination,
      "packages/glyph-forge-engine/manifests/pending-triage-edits.json"
    ),
    "[]\n",
    "utf-8"
  );
}

function shouldCopyPath(
  source: string,
  repoRoot: string,
  jobsRoot: string
): boolean {
  const resolved = path.resolve(source);
  if (resolved === jobsRoot || resolved.startsWith(`${jobsRoot}${path.sep}`)) {
    return false;
  }

  const relative = path.relative(repoRoot, resolved);
  if (!relative) {
    return true;
  }
  const parts = relative.split(path.sep);
  const basename = parts.at(-1);
  if (!basename) {
    return true;
  }

  if (
    basename === ".git" ||
    basename === "node_modules" ||
    basename === ".next" ||
    basename === ".turbo" ||
    basename === ".pipeline-jobs" ||
    basename === "tsconfig.tsbuildinfo"
  ) {
    return false;
  }
  if (relative === ".venv") {
    return false;
  }
  if (relative.startsWith(`packages${path.sep}variable-gen${path.sep}build`)) {
    return false;
  }
  if (relative.startsWith(`cabinet${path.sep}build${path.sep}work`)) {
    return false;
  }
  return true;
}

async function linkIfPresent(
  source: string,
  destination: string
): Promise<void> {
  if (!existsSync(source)) {
    return;
  }
  await rm(destination, { force: true, recursive: true });
  await symlink(source, destination, "dir");
}

async function installInputs(
  job: GenerationJob,
  repoPath: string
): Promise<number> {
  const inputs = await getRegisteredTargetInputs(job);
  if (!job.useWorkspaceSources) {
    const missing = missingRequiredTargets(job);
    if (missing.length > 0) {
      throw new Error(formatMissingRequiredTargets(missing));
    }
  }

  let installed = 0;
  for (const input of inputs) {
    const target = path.join(repoPath, input.targetPath);
    await mkdir(path.dirname(target), { recursive: true });
    await copyFile(input.sourcePath, target);
    installed += 1;
    await log(
      job.id,
      `installed ${input.originalName} -> ${input.targetPath}\n`
    );
  }
  return installed;
}

async function autoConverge(job: GenerationJob, cwd: string): Promise<string> {
  const summaries: string[] = [];
  for (let pass = 1; pass <= MAX_AUTO_CONVERGENCE_PASSES + 1; pass += 1) {
    const dryRun = await runCommand(job.id, cwd, COMMANDS.autoStageDryRun);
    if (dryRun.code !== 0) {
      throw new Error(`auto-stage dry-run failed with exit ${dryRun.code}`);
    }
    const pendingCount = parseWouldStageCount(dryRun.output);
    summaries.push(
      `pass ${pass}: ${pendingCount} automatic decision${pendingCount === 1 ? "" : "s"}`
    );
    if (pendingCount === 0) {
      return summaries.join("; ");
    }
    if (pass > MAX_AUTO_CONVERGENCE_PASSES) {
      break;
    }

    for (const command of [
      COMMANDS.autoStage,
      COMMANDS.applyTriage,
      COMMANDS.repairSkipImport,
      COMMANDS.auditInterpolation,
      COMMANDS.audit,
      COMMANDS.glyphForge,
    ] as const) {
      const result = await runCommand(job.id, cwd, command);
      if (result.code !== 0) {
        throw new Error(
          `${formatCommand(command)} failed with exit ${result.code}`
        );
      }
    }
  }

  throw new Error(
    `automatic convergence did not settle after ${MAX_AUTO_CONVERGENCE_PASSES} mutation passes`
  );
}

function parseWouldStageCount(output: string): number {
  const match = output.match(/would stage\s+(\d+)\s+glyphs?/i);
  return match ? Number(match[1]) : 0;
}

async function collectOutputs(
  job: GenerationJob,
  repoPath: string
): Promise<GenerationArtifact[]> {
  const outputsRoot = path.join(getJobDir(job.id), "outputs");
  await rm(outputsRoot, { force: true, recursive: true });
  await mkdir(outputsRoot, { recursive: true });

  const artifacts: GenerationArtifact[] = [];
  for (const output of OUTPUTS) {
    const source = path.join(repoPath, output.source);
    if (!existsSync(source)) {
      job.warnings.push(`Missing expected artifact: ${output.source}`);
      continue;
    }

    const destination = path.join(outputsRoot, output.destination);
    await mkdir(path.dirname(destination), { recursive: true });
    await copyFile(source, destination);
    const { size } = await stat(destination);
    const sha256 = createHash("sha256")
      .update(await readFile(destination))
      .digest("hex");
    artifacts.push({
      contentType: output.contentType,
      fileName: path.basename(output.destination),
      id: output.id,
      label: output.label,
      relativePath: output.destination,
      sha256,
      size,
    });
  }
  return artifacts;
}

async function runCommandStage(
  job: GenerationJob,
  stageId: GenerationStageId,
  cwd: string,
  command: readonly string[]
): Promise<void> {
  await runStage(job, stageId, async (stage) => {
    stage.command = formatCommand(command);
    const result = await runCommand(job.id, cwd, command);
    if (result.code !== 0) {
      throw new Error(
        `${formatCommand(command)} failed with exit ${result.code}`
      );
    }
    return summarizeCommandOutput(result.output);
  });
}

async function runReviewableCommandStage(
  job: GenerationJob,
  stageId: GenerationStageId,
  cwd: string,
  command: readonly string[]
): Promise<void> {
  const stage = job.stages.find((candidate) => candidate.id === stageId);
  if (!stage) {
    throw new Error(`Unknown generation stage: ${stageId}`);
  }
  if (stage.status === "succeeded") {
    await log(job.id, `\n[stage] ${stage.id} already passed\n`);
    return;
  }

  const started = Date.now();
  stage.status = "running";
  stage.startedAt = new Date(started).toISOString();
  stage.command = formatCommand(command);
  stage.error = undefined;
  job.updatedAt = stage.startedAt;
  await writeJob(job);
  await log(job.id, `\n[stage] ${stage.id}: ${stage.title}\n`);

  const result = await runCommand(job.id, cwd, command);
  stage.finishedAt = new Date().toISOString();
  stage.durationMs = Date.now() - started;
  stage.summary = summarizeCommandOutput(result.output);
  job.updatedAt = stage.finishedAt;

  if (result.code === 0) {
    stage.status = "succeeded";
    await writeJob(job);
    await log(job.id, `[stage] ${stage.id} passed\n`);
    return;
  }

  stage.status = "failed";
  stage.error = `${formatCommand(command)} failed with exit ${result.code}`;
  if (
    stageId === "blocker_residuals" &&
    residualFailureNeedsReview(result.output)
  ) {
    job.status = "needs_review";
    job.error =
      "Human review is required for exact-outline frozen or reconstruction blocker glyphs.";
  } else {
    await writeJob(job);
    await log(job.id, `[stage] ${stage.id} failed: ${stage.error}\n`);
    throw new Error(stage.error);
  }
  await writeJob(job);
  await log(job.id, `[stage] ${stage.id} needs review: ${stage.error}\n`);
}

async function runStage(
  job: GenerationJob,
  stageId: GenerationStageId,
  action: (stage: GenerationStageRun) => Promise<string | undefined>
): Promise<void> {
  const stage = job.stages.find((candidate) => candidate.id === stageId);
  if (!stage) {
    throw new Error(`Unknown generation stage: ${stageId}`);
  }
  if (stage.status === "succeeded") {
    await log(job.id, `\n[stage] ${stage.id} already passed\n`);
    return;
  }
  const started = Date.now();
  stage.status = "running";
  stage.startedAt = new Date(started).toISOString();
  stage.error = undefined;
  job.updatedAt = stage.startedAt;
  await writeJob(job);
  await log(job.id, `\n[stage] ${stage.id}: ${stage.title}\n`);

  try {
    const summary = await action(stage);
    stage.status = "succeeded";
    stage.finishedAt = new Date().toISOString();
    stage.durationMs = Date.now() - started;
    stage.summary = summary;
    job.updatedAt = stage.finishedAt;
    await writeJob(job);
    await log(job.id, `[stage] ${stage.id} passed\n`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    stage.status = "failed";
    stage.error = message;
    stage.finishedAt = new Date().toISOString();
    stage.durationMs = Date.now() - started;
    job.updatedAt = stage.finishedAt;
    await writeJob(job);
    await log(job.id, `[stage] ${stage.id} failed: ${message}\n`);
    throw error;
  }
}

function runCommand(
  jobId: string,
  cwd: string,
  command: readonly string[]
): Promise<CommandResult> {
  const [binary, ...args] = command;
  const resolvedBinary =
    process.platform === "win32" && binary === "npm" ? "npm.cmd" : binary;
  const printable = formatCommand(command);
  return new Promise((resolve, reject) => {
    void log(jobId, `$ ${printable}\n`);
    const child = spawn(resolvedBinary, args, {
      cwd,
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let output = "";
    child.stdout.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      output += text;
      void log(jobId, text);
    });
    child.stderr.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      output += text;
      void log(jobId, text);
    });
    child.on("error", reject);
    child.on("close", (code) => {
      resolve({ code: code ?? 1, output });
    });
  });
}

interface PipelineStatusStage {
  id?: string;
  summary?: Record<string, unknown>;
  failures?: string[];
}

interface PipelineStatus {
  stages?: PipelineStatusStage[];
  verdict?: string;
}

async function readPipelineStatus(repoPath: string): Promise<PipelineStatus> {
  const statusPath = path.join(
    repoPath,
    "packages/variable-gen/reports/pipeline-status.json"
  );
  return JSON.parse(await readFile(statusPath, "utf-8")) as PipelineStatus;
}

function statusNeedsReview(status: PipelineStatus): boolean {
  const glyphForge = status.stages?.find((stage) => stage.id === "glyph_forge");
  const unresolvedReconstruction =
    glyphForge?.summary?.unresolved_reconstruction_required_count;
  if (
    typeof unresolvedReconstruction === "number" &&
    unresolvedReconstruction > 0
  ) {
    return true;
  }

  return (status.stages ?? []).some((stage) =>
    (stage.failures ?? []).some((failure) =>
      failure.includes("exact-outline frozen")
    )
  );
}

function residualFailureNeedsReview(output: string): boolean {
  return output
    .split(/\r?\n/)
    .some(
      (line) =>
        line.includes("exact-outline frozen") ||
        line.includes("whole-glyph reconstruction")
    );
}

function summarizePipelineFailure(status: PipelineStatus): string {
  const failures = (status.stages ?? [])
    .flatMap((stage) =>
      (stage.failures ?? []).map((failure) => `${stage.id}: ${failure}`)
    )
    .slice(0, 5);
  if (failures.length > 0) {
    return failures.join("; ");
  }
  if (statusNeedsReview(status)) {
    return "Whole-glyph reconstruction review is required.";
  }
  return `Pipeline status verdict is ${status.verdict ?? "unknown"}.`;
}

function summarizeCommandOutput(output: string): string | undefined {
  const lines = output
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  return lines.at(-1)?.slice(0, 240);
}

function formatCommand(command: readonly string[]): string {
  return command
    .map((arg) =>
      /^[A-Za-z0-9_./:@=-]+$/.test(arg) ? arg : JSON.stringify(arg)
    )
    .join(" ");
}

async function log(jobId: string, text: string): Promise<void> {
  await appendGenerationLog(jobId, text);
}

void main();
