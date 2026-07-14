import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { styleText } from "node:util";

import { CliError, ExitCode } from "./errors.js";
import { formatCommand } from "./stages.js";
import type {
  HandoffMode,
  PipelineStage,
  PipelineStatusReport,
  RunOptions,
  StageRunResult,
  StatusPrintOptions,
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
  console.log(styleText("cyan", `\n[stage] ${label}`));
  console.log(`$ ${formatCommand(stage)}`);

  if (stage.artifact) {
    console.log(`artifact: ${stage.artifact}`);
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
      ? styleText("green", "passed")
      : styleText("red", `failed (${code})`);
  console.log(`[stage] ${stage.id} ${status} in ${formatDuration(durationMs)}`);
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
    throw new Error(
      "Pipeline status report is missing. Run static-to-variable status first."
    );
  }
  return JSON.parse(readFileSync(reportPath, "utf-8")) as PipelineStatusReport;
}

export function printPipelineStatus(
  report: PipelineStatusReport,
  options: StatusPrintOptions = {},
  repoRoot = findRepoRoot()
): void {
  const verdict =
    report.verdict === "pass"
      ? styleText("green", "pass")
      : styleText("red", "fail");
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
        ? styleText("green", stage.status)
        : styleText("red", stage.status);
    const gate = stage.blocking ? "blocking" : "diagnostic";
    console.log(`- ${stage.id}: ${status} (${gate})`);
    for (const failure of stage.failures ?? []) {
      console.log(`  failure: ${failure}`);
    }
    for (const observation of stage.observations ?? []) {
      console.log(`  observation: ${observation}`);
    }
  }

  if (report.verdict !== "pass") {
    printHandoff(report, options, repoRoot);
  }
}

export function formatDuration(durationMs: number): string {
  if (durationMs < 1000) {
    return `${durationMs}ms`;
  }
  return `${(durationMs / 1000).toFixed(1)}s`;
}

function findWorkspaceRoot(start: string): string | null {
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
  return new Promise((resolve, reject) => {
    const child = spawn(command, stage.args, {
      cwd,
      env: process.env,
      stdio: "inherit",
    });
    child.on("error", reject);
    child.on("close", (code) => resolve(code ?? 1));
  });
}

function printHandoff(
  report: PipelineStatusReport,
  options: StatusPrintOptions,
  repoRoot: string
): void {
  const mode: HandoffMode = options.handoff ?? "prompt";
  if (mode === "off") {
    return;
  }

  const top = options.top ?? 5;
  const targets = loadHandoffTargets(repoRoot, top);
  const automaticCount = glyphForgeSummaryNumber(
    report,
    "automatic_decision_candidate_count"
  );
  if (targets.length === 0) {
    if (automaticCount > 0) {
      console.log("\nautomatic glyph decisions pending:");
      console.log(
        `- ${automaticCount} non-reconstruction glyphs can be staged automatically`
      );
      console.log(
        "- run: npm --workspace @static-to-variable/glyph-forge-engine run auto-stage"
      );
      console.log(
        "- then: npm --workspace @static-to-variable/glyph-forge-engine run apply"
      );
      console.log(
        "- then rerun from repair: npm run pipeline -- run all --from repair_build"
      );
    } else {
      console.log(
        "\nno reconstruction handoff targets found; fix the failing pipeline stage and rerun status."
      );
    }
    return;
  }

  const workspaceUrl = "https://static-to-variable.localhost/interventions";
  const fallbackUrl = "http://localhost:3333/interventions";

  console.log("\nhuman intervention workspace:");
  console.log(`- ${workspaceUrl}`);
  console.log(`- ${fallbackUrl}`);
  console.log("start it with: npm run pipeline:app");

  console.log(
    `\ntop ${targets.length} reconstruction target${targets.length === 1 ? "" : "s"}:`
  );
  for (const target of targets) {
    const pathPart = `/g/${target.family}/${encodeURIComponent(target.name)}`;
    const worst =
      target.worstComposite === null
        ? "worst unknown"
        : `worst ${Math.round(target.worstComposite * 100)}@${target.worstWght ?? "?"}`;
    const gain =
      target.gain === null
        ? "gain unknown"
        : `gain +${Math.round(target.gain * 100)}`;
    const best = target.best ? `best ${target.best}` : "best unknown";
    console.log(
      `- ${pathPart} (${target.verdict}, ${worst}, ${gain}, ${best})`
    );
  }

  if (mode === "auto") {
    openUrl(workspaceUrl);
  }
}

function glyphForgeSummaryNumber(
  report: PipelineStatusReport,
  key: string
): number {
  const glyphForge = report.stages?.find((stage) => stage.id === "glyph_forge");
  const value = glyphForge?.summary?.[key];
  return typeof value === "number" ? value : 0;
}

interface HandoffTarget {
  family: string;
  name: string;
  verdict: string;
  worstComposite: number | null;
  worstWght: number | null;
  gain: number | null;
  best: string | null;
}

function loadHandoffTargets(repoRoot: string, limit: number): HandoffTarget[] {
  const manifest = readJson<Record<string, unknown>[]>(
    path.join(
      repoRoot,
      "packages/glyph-forge-engine/manifests/broken-glyphs.json"
    ),
    []
  );
  const scores = readJson<Record<string, Record<string, unknown>>>(
    path.join(
      repoRoot,
      "packages/glyph-forge-engine/manifests/glyph-scores.json"
    ),
    {}
  );
  const solver = readJson<Record<string, Record<string, unknown>>>(
    path.join(
      repoRoot,
      "packages/glyph-forge-engine/manifests/solver-results.json"
    ),
    {}
  );

  return manifest
    .map((glyph): HandoffTarget | null => {
      const family = asString(glyph.family);
      const name = asString(glyph.name);
      const verdict = asString(glyph.auditVerdict);
      if (!family || !name || !verdict) {
        return null;
      }
      if (!["blocker", "unknown", "high"].includes(verdict)) {
        return null;
      }

      const key = `${family}/${name}`;
      const score = scores[key] ?? {};
      const solve = solver[key] ?? {};
      if (solve.requiresReconstruction !== true) {
        return null;
      }
      const gain = asNumber(solve.gain);

      return {
        best: asString(solve.best),
        family,
        gain,
        name,
        verdict,
        worstComposite: asNumber(score.worstComposite),
        worstWght: asNumber(score.worstWght),
      };
    })
    .filter((target): target is HandoffTarget => target !== null)
    .toSorted(compareHandoffTargets)
    .slice(0, limit);
}

function compareHandoffTargets(a: HandoffTarget, b: HandoffTarget): number {
  return (
    verdictRank(a.verdict) - verdictRank(b.verdict) ||
    (a.worstComposite ?? Number.POSITIVE_INFINITY) -
      (b.worstComposite ?? Number.POSITIVE_INFINITY) ||
    (b.gain ?? Number.NEGATIVE_INFINITY) -
      (a.gain ?? Number.NEGATIVE_INFINITY) ||
    `${a.family}/${a.name}`.localeCompare(`${b.family}/${b.name}`)
  );
}

function verdictRank(verdict: string): number {
  if (verdict === "blocker") {
    return 0;
  }
  if (verdict === "unknown") {
    return 1;
  }
  if (verdict === "high") {
    return 2;
  }
  return 3;
}

function readJson<T>(filePath: string, fallback: T): T {
  try {
    return JSON.parse(readFileSync(filePath, "utf-8")) as T;
  } catch {
    return fallback;
  }
}

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function openUrl(url: string): void {
  if (process.platform !== "darwin") {
    return;
  }
  spawnSync("open", [url], { stdio: "ignore" });
}
