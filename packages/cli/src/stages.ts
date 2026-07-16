import { CliError, ExitCode } from "./errors.js";
import type { PipelineStage, StagePlanOptions } from "./types.js";

export const PIPELINE_STAGES: readonly PipelineStage[] = [
  {
    args: [
      "--workspace",
      "@static-to-variable/variable-gen",
      "run",
      "inventory",
    ],
    artifact: "packages/variable-gen/reports/donor-inventory.json",
    command: "npm",
    description:
      "Discover the static donor fonts in the manifest and write the inventory report.",
    id: "inventory",
    kind: "blocking",
    title: "Donor Inventory",
  },
  {
    args: [
      "--workspace",
      "@static-to-variable/variable-gen",
      "run",
      "compatibility:raw",
    ],
    artifact: "packages/variable-gen/reports/compatibility-raw.json",
    command: "npm",
    description:
      "Run fontTools interpolatable checks against raw static donors before repair.",
    id: "raw_compatibility",
    kind: "diagnostic",
    title: "Raw Donor Compatibility",
  },
  {
    args: ["--workspace", "@static-to-variable/variable-gen", "run", "rebuild"],
    artifact: "packages/variable-gen/reports/reconstruction-report.json",
    command: "npm",
    description:
      "Rebuild every master from its donors onto a shared, interpolation-compatible structure.",
    id: "repair_build",
    kind: "blocking",
    mutatesSources: true,
    title: "Compatible Master Rebuild",
  },
  {
    args: [
      "--workspace",
      "@static-to-variable/variable-gen",
      "run",
      "audit:interpolation",
    ],
    artifact:
      "packages/variable-gen/reports/audit/audit-run-summary-interpolation-only.json",
    command: "npm",
    description:
      "Sample interior weights and report interpolation-only risk without donor endpoint checks.",
    id: "audit_interpolation",
    kind: "diagnostic",
    title: "Interior Interpolation Audit",
  },
  {
    args: ["--workspace", "@static-to-variable/variable-gen", "run", "audit"],
    artifact: "packages/variable-gen/reports/audit/audit-run-summary.json",
    command: "npm",
    description:
      "Run the full variable audit, including sampled interiors and exact donor checkpoints.",
    id: "full_audit",
    kind: "diagnostic",
    title: "Full Variable Audit Diagnostics",
  },
  {
    args: [
      "--workspace",
      "@static-to-variable/variable-gen",
      "run",
      "residual:blockers",
    ],
    artifact:
      "packages/variable-gen/reports/repair/blocker-residual-validation.md",
    command: "npm",
    description:
      "Validate manifest-tracked blocker glyphs for source structure, area drift, and short segments.",
    id: "blocker_residuals",
    kind: "blocking",
    title: "Blocker Residual Validation",
  },
  {
    args: [
      "--workspace",
      "@static-to-variable/glyph-forge-engine",
      "run",
      "qa:build",
    ],
    artifact: "packages/glyph-forge-engine/manifests/broken-glyphs.json",
    command: "npm",
    description:
      "Rebuild visual QA manifests, scores, recommendations, and solver outputs from variable-gen reports.",
    id: "glyph_forge",
    kind: "blocking",
    title: "Glyph QA",
  },
  {
    args: ["--workspace", "@static-to-variable/studio", "run", "predev"],
    artifact: "apps/studio/public",
    command: "npm",
    defaultEnabled: false,
    description:
      "Sync the rebuilt visual QA cache into the Next.js studio app.",
    id: "glyph_forge_sync",
    kind: "sync",
    title: "Studio Cache Sync",
  },
  {
    args: [
      "--workspace",
      "@static-to-variable/variable-gen",
      "run",
      "pipeline:status",
    ],
    artifact: "packages/variable-gen/reports/pipeline-status.json",
    command: "npm",
    description:
      "Aggregate stage artifacts into the promotion status JSON and Markdown report.",
    id: "pipeline_status",
    kind: "reporting",
    title: "Pipeline Status",
  },
];

const STAGE_ALIASES = new Map<string, string>([
  ["all", "all"],
  ["audit", "full_audit"],
  ["blockers", "blocker_residuals"],
  ["compatibility", "raw_compatibility"],
  ["forge", "glyph_forge"],
  ["glyph-forge", "glyph_forge"],
  ["interpolation", "audit_interpolation"],
  ["raw", "raw_compatibility"],
  ["rebuild", "repair_build"],
  ["repair", "repair_build"],
  ["residuals", "blocker_residuals"],
  ["status", "pipeline_status"],
]);

export function defaultStages(): PipelineStage[] {
  return PIPELINE_STAGES.filter((stage) => stage.defaultEnabled !== false);
}

export function normalizeStageId(value: string): string {
  const normalized = value.trim().toLowerCase().replaceAll("-", "_");
  return STAGE_ALIASES.get(normalized) ?? normalized;
}

export function resolveStage(value: string): PipelineStage {
  const id = normalizeStageId(value);
  const stage = PIPELINE_STAGES.find((candidate) => candidate.id === id);
  if (!stage) {
    throw new CliError("STV_UNKNOWN_STAGE", `Unknown stage "${value}".`, {
      fix: "Run `static-to-variable list` to see valid stages.",
      exitCode: ExitCode.Usage,
    });
  }
  return stage;
}

export function buildStagePlan(
  options: StagePlanOptions = {}
): PipelineStage[] {
  const fullPlan = defaultStages();
  const fromIndex = options.from ? stageIndex(fullPlan, options.from) : 0;
  const toIndex = options.to
    ? stageIndex(fullPlan, options.to)
    : fullPlan.length - 1;

  if (fromIndex > toIndex) {
    throw new CliError(
      "STV_STAGE_RANGE_EMPTY",
      `Stage range is empty: ${options.from} comes after ${options.to}.`,
      {
        fix: "Swap --from and --to, or widen the range.",
        exitCode: ExitCode.Usage,
      }
    );
  }

  let plan = fullPlan.slice(fromIndex, toIndex + 1);

  if (options.blockingOnly) {
    plan = plan.filter(
      (stage) => stage.kind === "blocking" || stage.kind === "reporting"
    );
  } else if (options.skipDiagnostics) {
    plan = plan.filter((stage) => stage.kind !== "diagnostic");
  }

  return plan;
}

export function formatCommand(stage: PipelineStage): string {
  return [stage.command, ...stage.args].map(quoteArg).join(" ");
}

export function stageChoices(): {
  label: string;
  value: string;
  hint: string;
}[] {
  return PIPELINE_STAGES.map((stage) => ({
    hint: `${stage.kind}: ${stage.title}`,
    label: stage.id,
    value: stage.id,
  }));
}

function stageIndex(stages: PipelineStage[], value: string): number {
  const id = normalizeStageId(value);
  const index = stages.findIndex((stage) => stage.id === id);
  if (index === -1) {
    resolveStage(value);
    throw new Error(
      `Stage "${value}" is not part of the default pipeline plan.`
    );
  }
  return index;
}

function quoteArg(arg: string): string {
  return /^[A-Za-z0-9_./:@=-]+$/.test(arg) ? arg : JSON.stringify(arg);
}
