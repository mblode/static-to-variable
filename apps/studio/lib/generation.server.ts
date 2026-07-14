import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import {
  mkdir,
  readFile,
  readdir,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import path from "node:path";

import type {
  GenerationArtifact,
  GenerationInput,
  GenerationInputRole,
  GenerationJob,
} from "./generation-types";
import {
  createInitialGenerationStages,
  isActiveGenerationStatus,
} from "./generation-types";
import { loadProjectConfig } from "./project-config.server";

export const JOBS_DIR_NAME = ".pipeline-jobs";
export const JOB_STATE_FILE = "job.json";
export const JOB_LOG_FILE = "log.txt";
export const MAX_GENERATION_UPLOAD_FILES = 64;
export const MAX_GENERATION_UPLOAD_BYTES = 512 * 1024 * 1024;

export interface CreateGenerationJobOptions {
  files: File[];
  useWorkspaceSources: boolean;
}

interface TargetInput {
  role: GenerationInputRole;
  targetPath: string;
  family?: string;
  weight?: number;
}

// Engine / variable-gen artifacts the config does not describe but the pipeline
// still expects as uploadable inputs.
const AUXILIARY_TARGETS: Record<string, TargetInput> = {
  "circular-triage.json": {
    role: "triage_manifest",
    targetPath: "packages/variable-gen/manifests/circular-triage.json",
  },
  "pending-triage-edits.json": {
    role: "pending_triage",
    targetPath:
      "packages/glyph-forge-engine/manifests/pending-triage-edits.json",
  },
};

const ALLOWED_UPLOAD_EXTENSIONS = new Set([".glyphs", ".json", ".otf", ".ttf"]);

let cachedTargets: Record<string, TargetInput> | null = null;

function getDonorTargets(): Record<string, TargetInput> {
  if (cachedTargets) {
    return cachedTargets;
  }
  const config = loadProjectConfig(getRepoRoot());
  const targets: Record<string, TargetInput> = { ...AUXILIARY_TARGETS };
  for (const [family, style] of Object.entries(config.styles)) {
    for (const donor of style.donors) {
      targets[path.basename(donor.path)] = {
        family,
        role: "donor",
        targetPath: donor.path,
        weight: donor.location.wght,
      };
    }
    targets[path.basename(style.source)] = {
      family,
      role: "glyphs_source",
      targetPath: style.source,
    };
  }
  cachedTargets = targets;
  return targets;
}

function getRequiredSourceTargets(): TargetInput[] {
  return Object.values(getDonorTargets()).filter((target) =>
    ["donor", "glyphs_source", "triage_manifest"].includes(target.role)
  );
}

export function getRepoRoot(): string {
  let current = process.cwd();
  while (true) {
    const packagePath = path.join(current, "package.json");
    try {
      const pkg = JSON.parse(readFileSync(packagePath, "utf-8")) as {
        name?: string;
        workspaces?: unknown;
      };
      if (pkg.name === "static-to-variable" && Array.isArray(pkg.workspaces)) {
        return current;
      }
    } catch {
      // keep walking
    }

    const parent = path.dirname(current);
    if (parent === current) {
      throw new Error("Could not find static-to-variable workspace root.");
    }
    current = parent;
  }
}

export function getJobsRoot(): string {
  return path.join(getRepoRoot(), "apps", "studio", JOBS_DIR_NAME);
}

export function getJobDir(jobId: string): string {
  assertJobId(jobId);
  return path.join(getJobsRoot(), jobId);
}

export function assertJobId(jobId: string): void {
  if (!/^[a-z0-9][a-z0-9._-]{3,80}$/i.test(jobId)) {
    throw new Error("Invalid generation job id.");
  }
}

export async function createGenerationJob({
  files,
  useWorkspaceSources,
}: CreateGenerationJobOptions): Promise<GenerationJob> {
  const releaseLock = await acquireCreationLock();
  try {
    validateUploadSet(files, useWorkspaceSources);

    const active = await hasActiveGenerationJob();
    if (active) {
      throw new Error(
        `Generation job ${active.id} is already ${active.status}.`
      );
    }

    const now = new Date().toISOString();
    const id = `${compactTimestamp(now)}-${randomUUID().slice(0, 8)}`;
    const jobDir = getJobDir(id);
    const uploadsDir = path.join(jobDir, "uploads");
    await mkdir(uploadsDir, { recursive: true });

    const inputs: GenerationInput[] = [];
    const warnings: string[] = [];
    for (const file of files) {
      if (file.size <= 0) {
        warnings.push(
          `${file.name || "unnamed file"} was empty and was ignored.`
        );
        continue;
      }

      const buffer = Buffer.from(await file.arrayBuffer());
      const originalName = sanitizeOriginalName(file.name || "upload.bin");
      const sha256 = createHash("sha256").update(buffer).digest("hex");
      const extension = path.extname(originalName).slice(0, 16);
      const storedName = `${inputs.length + 1}-${sha256.slice(0, 12)}${extension}`;
      await writeFile(path.join(uploadsDir, storedName), buffer);

      const target = getDonorTargets()[path.basename(originalName)];
      if (!target) {
        warnings.push(
          `${originalName} is not a known Circular source target; kept as an auxiliary upload.`
        );
      }

      inputs.push({
        family: target?.family,
        id: randomUUID(),
        originalName,
        role: target?.role ?? "other",
        sha256,
        size: file.size,
        storedName,
        targetPath: target?.targetPath,
        weight: target?.weight,
      });
    }

    if (!useWorkspaceSources) {
      const missing = missingRequiredTargets(inputs);
      if (missing.length > 0) {
        throw new Error(formatMissingRequiredTargets(missing));
      }
    }

    const job: GenerationJob = {
      artifacts: [],
      createdAt: now,
      id,
      inputs,
      stages: createInitialGenerationStages(),
      status: "queued",
      updatedAt: now,
      useWorkspaceSources,
      warnings,
    };
    await writeJob(job);
    await writeFile(path.join(jobDir, JOB_LOG_FILE), "", "utf-8");
    return job;
  } finally {
    await releaseLock();
  }
}

export function startGenerationJob(jobId: string): void {
  assertJobId(jobId);
  const command = process.platform === "win32" ? "npm.cmd" : "npm";
  const child = spawn(
    command,
    [
      "--workspace",
      "@static-to-variable/studio",
      "run",
      "generation:run",
      "--",
      jobId,
    ],
    {
      cwd: getRepoRoot(),
      detached: true,
      env: process.env,
      stdio: "ignore",
    }
  );
  child.unref();
}

export async function readGenerationJob(jobId: string): Promise<GenerationJob> {
  const job = JSON.parse(
    await readFile(path.join(getJobDir(jobId), JOB_STATE_FILE), "utf-8")
  ) as GenerationJob;
  return job;
}

export async function writeJob(job: GenerationJob): Promise<void> {
  const jobDir = getJobDir(job.id);
  await mkdir(jobDir, { recursive: true });
  const statePath = path.join(jobDir, JOB_STATE_FILE);
  const tempPath = `${statePath}.${process.pid}.tmp`;
  await writeFile(tempPath, JSON.stringify(job, null, 2), "utf-8");
  await rename(tempPath, statePath);
}

export async function appendGenerationLog(
  jobId: string,
  text: string
): Promise<void> {
  const { appendFile } = await import("node:fs/promises");
  await appendFile(path.join(getJobDir(jobId), JOB_LOG_FILE), text, "utf-8");
}

export async function readGenerationLog(jobId: string): Promise<string> {
  try {
    return await readFile(path.join(getJobDir(jobId), JOB_LOG_FILE), "utf-8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return "";
    }
    throw error;
  }
}

export async function listGenerationJobs(): Promise<GenerationJob[]> {
  const root = getJobsRoot();
  await mkdir(root, { recursive: true });
  const entries = await readdir(root, { withFileTypes: true });
  const jobs: GenerationJob[] = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) {
      continue;
    }
    try {
      jobs.push(await readGenerationJob(entry.name));
    } catch {
      // Ignore partially-created or manually-edited job directories.
    }
  }
  return jobs
    .toSorted((a, b) => b.createdAt.localeCompare(a.createdAt))
    .slice(0, 30);
}

export async function hasActiveGenerationJob(): Promise<GenerationJob | null> {
  const jobs = await listGenerationJobs();
  return jobs.find((job) => isActiveGenerationStatus(job.status)) ?? null;
}

export async function resolveArtifactPath(
  jobId: string,
  artifactId: string
): Promise<{ artifact: GenerationArtifact; path: string }> {
  const job = await readGenerationJob(jobId);
  const artifact = job.artifacts.find(
    (candidate) => candidate.id === artifactId
  );
  if (!artifact) {
    throw new Error("Unknown generation artifact.");
  }

  const outputsRoot = path.join(getJobDir(jobId), "outputs");
  const resolved = path.resolve(outputsRoot, artifact.relativePath);
  const outputPrefix = `${path.resolve(outputsRoot)}${path.sep}`;
  if (!resolved.startsWith(outputPrefix)) {
    throw new Error("Invalid generation artifact path.");
  }
  await stat(resolved);
  return { artifact, path: resolved };
}

export function getRegisteredTargetInputs(
  job: GenerationJob
): (GenerationInput & { sourcePath: string; targetPath: string })[] {
  const uploadsDir = path.join(getJobDir(job.id), "uploads");
  return job.inputs
    .filter((input): input is GenerationInput & { targetPath: string } =>
      Boolean(input.targetPath)
    )
    .map((input) => ({
      ...input,
      sourcePath: path.join(uploadsDir, input.storedName),
    }));
}

export function missingRequiredTargets(
  jobOrInputs: GenerationJob | GenerationInput[]
): string[] {
  const inputs = Array.isArray(jobOrInputs) ? jobOrInputs : jobOrInputs.inputs;
  const uploadedTargets = new Set(
    inputs
      .map((input) => input.targetPath)
      .filter((targetPath): targetPath is string => Boolean(targetPath))
  );
  return getRequiredSourceTargets()
    .map((target) => target.targetPath)
    .filter((targetPath) => !uploadedTargets.has(targetPath));
}

export function formatMissingRequiredTargets(missing: string[]): string {
  return [
    "Workspace source fallback is disabled, but required source targets are missing.",
    `Missing ${missing.length}: ${missing.slice(0, 8).join(", ")}${missing.length > 8 ? ", ..." : ""}`,
  ].join(" ");
}

export function requiredGenerationSourcePaths(): string[] {
  return getRequiredSourceTargets().map((target) => target.targetPath);
}

function validateUploadSet(files: File[], useWorkspaceSources: boolean): void {
  if (!useWorkspaceSources && files.length === 0) {
    throw new Error(
      "Upload Circular source files or enable workspace sources."
    );
  }
  if (files.length > MAX_GENERATION_UPLOAD_FILES) {
    throw new Error(`Upload at most ${MAX_GENERATION_UPLOAD_FILES} files.`);
  }
  const totalBytes = files.reduce((total, file) => total + file.size, 0);
  if (totalBytes > MAX_GENERATION_UPLOAD_BYTES) {
    throw new Error(
      `Upload payload is too large (${formatBytes(totalBytes)} > ${formatBytes(MAX_GENERATION_UPLOAD_BYTES)}).`
    );
  }
  for (const file of files) {
    const extension = path.extname(file.name || "").toLowerCase();
    if (file.size > 0 && !ALLOWED_UPLOAD_EXTENSIONS.has(extension)) {
      throw new Error(
        `Unsupported upload type for ${file.name || "unnamed file"}.`
      );
    }
  }
}

async function acquireCreationLock(): Promise<() => Promise<void>> {
  const root = getJobsRoot();
  await mkdir(root, { recursive: true });
  const lockDir = path.join(root, ".create.lock");
  try {
    await mkdir(lockDir);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      throw new Error("Another generation job is being created.", {
        cause: error,
      });
    }
    throw error;
  }
  return async () => {
    await rm(lockDir, { force: true, recursive: true });
  };
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function sanitizeOriginalName(name: string): string {
  const base = path.basename(name).replaceAll(/[^\w .@()+,-]/g, "_");
  return base || "upload.bin";
}

function compactTimestamp(iso: string): string {
  return iso.replaceAll(/\D/g, "").slice(0, 14);
}
