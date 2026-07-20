import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { CliError, ExitCode } from "./errors.js";
import { color, colorErr, progress } from "./output.js";
import { spawnInherit } from "./proc.js";
import { formatCommand } from "./stages.js";
import type {
  PipelineStage,
  PipelineStatusReport,
  RunOptions,
  StageRunResult,
} from "./types.js";

/** Repo root if we're inside a static-to-variable checkout, else null. */
export function tryFindRepoRoot(): string | null {
  // fileURLToPath (not import.meta.dirname) so `npm run cli` under tsx works too.
  const moduleDir = path.dirname(fileURLToPath(import.meta.url));
  for (const start of [process.cwd(), moduleDir]) {
    const found = findWorkspaceRoot(start);
    if (found) {
      return found;
    }
  }
  return null;
}

export function findRepoRoot(): string {
  const root = tryFindRepoRoot();
  if (root) {
    return root;
  }
  throw new CliError(
    "STV_WORKSPACE_NOT_FOUND",
    "Could not find the static-to-variable workspace root.",
    {
      fix: "Run this inside a static-to-variable checkout. Standalone (global-install) mode is not wired yet.",
      exitCode: ExitCode.Environment,
    }
  );
}

export async function runStage(
  stage: PipelineStage,
  options: RunOptions = {},
  repoRoot = findRepoRoot()
): Promise<StageRunResult> {
  const startedAt = Date.now();
  const label = `${stage.id} (${stage.kind})`;
  progress(colorErr("cyan", `\n[stage] ${label}`));
  progress(`$ ${formatCommand(stage)}`);

  if (stage.artifact) {
    progress(`artifact: ${stage.artifact}`);
  }

  if (options.dryRun) {
    return {
      code: 0,
      durationMs: Date.now() - startedAt,
      stage,
    };
  }

  const code = await spawnCommand(stage, repoRoot);
  const durationMs = Date.now() - startedAt;
  const status =
    code === 0
      ? colorErr("green", "passed")
      : colorErr("red", `failed (${code})`);
  progress(`[stage] ${stage.id} ${status} in ${formatDuration(durationMs)}`);
  return { code, durationMs, stage };
}

export async function runStages(
  stages: PipelineStage[],
  options: RunOptions = {},
  repoRoot = findRepoRoot()
): Promise<StageRunResult[]> {
  const results: StageRunResult[] = [];

  for (const stage of stages) {
    const result = await runStage(stage, options, repoRoot);
    results.push(result);
    if (result.code !== 0 && !options.continueOnFail) {
      break;
    }
  }

  return results;
}

export function readPipelineStatus(
  repoRoot = findRepoRoot()
): PipelineStatusReport {
  const reportPath = path.join(
    repoRoot,
    "packages/variable-gen/reports/pipeline-status.json"
  );
  if (!existsSync(reportPath)) {
    throw new CliError(
      "STV_STATUS_REPORT_MISSING",
      `Pipeline status report is missing at ${reportPath}.`,
      {
        fix: "Run `static-to-variable status` (without --read) to regenerate it.",
        exitCode: ExitCode.Failure,
      }
    );
  }
  return JSON.parse(readFileSync(reportPath, "utf-8")) as PipelineStatusReport;
}

export function printPipelineStatus(report: PipelineStatusReport): void {
  const verdict =
    report.verdict === "pass" ? color("green", "pass") : color("red", "fail");
  console.log(`\nStatic-to-variable pipeline: ${verdict}`);

  const summary = report.summary ?? {};
  const blockingFailures = String(summary.blocking_failure_count ?? "unknown");
  const diagnosticFailures = String(
    summary.diagnostic_failure_count ?? "unknown"
  );
  const diagnosticObservations = String(
    summary.diagnostic_observation_count ?? 0
  );
  console.log(`blocking failures: ${blockingFailures}`);
  console.log(`diagnostic failures: ${diagnosticFailures}`);
  console.log(`diagnostic observations: ${diagnosticObservations}`);

  for (const stage of report.stages ?? []) {
    const status =
      stage.status === "pass"
        ? color("green", stage.status)
        : color("red", stage.status);
    const gate = stage.blocking ? "blocking" : "diagnostic";
    console.log(`- ${stage.id}: ${status} (${gate})`);
    for (const failure of stage.failures ?? []) {
      console.log(`  failure: ${failure}`);
    }
    for (const observation of stage.observations ?? []) {
      console.log(`  observation: ${observation}`);
    }
  }
}

export function formatDuration(durationMs: number): string {
  if (durationMs < 1000) {
    return `${durationMs}ms`;
  }
  return `${(durationMs / 1000).toFixed(1)}s`;
}

export function findWorkspaceRoot(start: string): string | null {
  let current = path.resolve(start);
  while (true) {
    const packagePath = path.join(current, "package.json");
    if (existsSync(packagePath)) {
      const payload = JSON.parse(readFileSync(packagePath, "utf-8")) as {
        name?: string;
        workspaces?: unknown;
      };
      if (
        payload.name === "static-to-variable-monorepo" &&
        Array.isArray(payload.workspaces)
      ) {
        return current;
      }
    }

    const parent = path.dirname(current);
    if (parent === current) {
      return null;
    }
    current = parent;
  }
}

function spawnCommand(stage: PipelineStage, cwd: string): Promise<number> {
  const command =
    process.platform === "win32" && stage.command === "npm"
      ? "npm.cmd"
      : stage.command;
  return spawnInherit(command, stage.args, cwd);
}
