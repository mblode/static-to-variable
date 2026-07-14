import "server-only";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";

import type {
  AuditVerdict,
  Family,
  PendingTriageEdit,
  SolverCandidateName,
  StrategyName,
} from "@static-to-variable/glyph-forge-engine";

import { glyphKey } from "@/lib/data";
import {
  loadGlyphScores,
  loadManifest,
  loadSolverResults,
  loadSuggestions,
} from "@/lib/data.server";
import { keyOf, readPending } from "@/lib/pending.server";

const PIPELINE_STATUS_PATH = path.join(
  process.cwd(),
  "public",
  "pipeline-status.json"
);
const RESIDUAL_REPORT_PATH = path.join(
  process.cwd(),
  "public",
  "blocker-residual-validation.md"
);
const CACHE_ARTIFACTS = [
  ["pipeline status", PIPELINE_STATUS_PATH],
  ["broken glyphs", path.join(process.cwd(), "public", "broken-glyphs.json")],
  ["glyph scores", path.join(process.cwd(), "public", "glyph-scores.json")],
  ["solver results", path.join(process.cwd(), "public", "solver-results.json")],
] as const;

const VERDICT_RANK: Record<AuditVerdict, number> = {
  blocker: 0,
  high: 2,
  low: 5,
  medium: 4,
  tracked: 3,
  unknown: 1,
};

export type InterventionState =
  | "clear"
  | "diagnostic"
  | "needs_human"
  | "ready_to_apply"
  | "needs_rerun";

export interface PipelineStatusStage {
  id: string;
  name: string;
  kind: string;
  status: string;
  blocking: boolean;
  artifact: string;
  summary?: Record<string, unknown>;
  failures?: string[];
  observations?: string[];
}

export interface PipelineStatusReport {
  verdict: string;
  summary: {
    blocking_failure_count?: number;
    diagnostic_failure_count?: number;
    diagnostic_observation_count?: number;
    stage_count?: number;
  };
  stages: PipelineStatusStage[];
}

export type InterventionStage = PipelineStatusStage & {
  state: InterventionState;
  humanLabel: string;
  actionHref?: string;
  command?: string;
};

export interface InterventionGlyph {
  key: string;
  family: Family;
  name: string;
  verdict: AuditVerdict;
  tier: "must_decide" | "candidate" | "backlog";
  worstComposite: number | null;
  worstWght: number | null;
  gain: number | null;
  bestStrategy: SolverCandidateName | null;
  suggestedStrategy: StrategyName | null;
  suggestionReason?: string;
  requiresReconstruction: boolean;
  reconstructionReason?: string;
  currentStrategy?: string;
  pendingStrategy?: StrategyName;
  pendingSource?: PendingTriageEdit["source"];
}

export interface ResidualIssue {
  key: string;
  family: Family;
  glyph: string;
  strategy?: string;
  frozen: boolean;
  riskyWeights: number[];
  maxAreaDrift: number | null;
  failures: string[];
}

export interface ArtifactFreshness {
  stale: boolean;
  message: string;
}

export interface InterventionDashboard {
  status: PipelineStatusReport | null;
  stages: InterventionStage[];
  queue: InterventionGlyph[];
  residualIssues: ResidualIssue[];
  pending: PendingTriageEdit[];
  freshness: ArtifactFreshness;
  counts: {
    blockingFailures: number;
    diagnostics: number;
    mustDecide: number;
    candidates: number;
    pending: number;
    residualIssues: number;
  };
  commands: {
    startApp: string;
    refreshStatus: string;
    runDefault: string;
    applyDryRun: string;
    apply: string;
    resumeAfterApply: string;
  };
}

export async function buildInterventionDashboard(): Promise<InterventionDashboard> {
  const [
    status,
    manifest,
    scores,
    solver,
    suggestions,
    pending,
    residualText,
    freshness,
  ] = await Promise.all([
    readPipelineStatus(),
    loadManifest(),
    loadGlyphScores(),
    loadSolverResults(),
    loadSuggestions(),
    readPending(),
    readText(RESIDUAL_REPORT_PATH),
    checkArtifactFreshness(),
  ]);

  const pendingByKey = new Map(pending.map((edit) => [keyOf(edit), edit]));
  const queue = manifest
    .map((glyph): InterventionGlyph => {
      const key = glyphKey(glyph.family, glyph.name);
      const score = scores?.[key];
      const verdict = solver?.[key];
      const suggestion = suggestions?.[key];
      const staged = pendingByKey.get(key);
      const requiresReconstruction = verdict?.requiresReconstruction === true;
      return {
        bestStrategy: verdict?.best ?? null,
        currentStrategy: glyph.existingStrategy,
        family: glyph.family,
        gain: verdict?.gain ?? null,
        key,
        name: glyph.name,
        pendingSource: staged?.source,
        pendingStrategy: staged?.strategy,
        reconstructionReason: verdict?.reconstructionReason ?? undefined,
        requiresReconstruction,
        suggestedStrategy: suggestion?.strategy ?? null,
        suggestionReason: suggestion?.reason,
        tier: reviewTier(Boolean(staged), requiresReconstruction),
        verdict: glyph.auditVerdict,
        worstComposite: score?.worstComposite ?? null,
        worstWght: score?.worstWght ?? null,
      };
    })
    .filter((glyph) => glyph.tier !== "backlog" || glyph.pendingStrategy)
    .toSorted(compareInterventionGlyphs);

  const residualIssues = parseResidualIssues(residualText ?? "");
  const stages = (status?.stages ?? []).map((stage) =>
    decorateStage(stage, pending.length)
  );

  return {
    commands: {
      apply: "npm --workspace @static-to-variable/glyph-forge-engine run apply",
      applyDryRun:
        "npm --workspace @static-to-variable/glyph-forge-engine run apply -- --dry-run",
      refreshStatus: "npm run pipeline:status",
      resumeAfterApply:
        "npm run pipeline -- run all --from repair_build --continue-on-fail",
      runDefault: "npm run pipeline -- run all",
      startApp: "turbo dev --filter=@static-to-variable/studio",
    },
    counts: {
      blockingFailures: status?.summary.blocking_failure_count ?? 0,
      candidates: queue.filter((glyph) => glyph.tier === "candidate").length,
      diagnostics:
        status?.summary.diagnostic_observation_count ??
        status?.summary.diagnostic_failure_count ??
        0,
      mustDecide: queue.filter((glyph) => glyph.tier === "must_decide").length,
      pending: pending.length,
      residualIssues: residualIssues.length,
    },
    freshness,
    pending,
    queue,
    residualIssues,
    stages,
    status,
  };
}

function decorateStage(
  stage: PipelineStatusStage,
  pendingCount: number
): InterventionStage {
  if (stage.id === "glyph_forge" && pendingCount > 0) {
    return {
      ...stage,
      actionHref: "/triage",
      command:
        "npm --workspace @static-to-variable/glyph-forge-engine run apply -- --dry-run",
      humanLabel: `${pendingCount} staged decision${pendingCount === 1 ? "" : "s"} ready`,
      state: "ready_to_apply",
    };
  }

  if (stage.status === "pass") {
    return { ...stage, humanLabel: "Clear", state: "clear" };
  }

  if (!stage.blocking) {
    return {
      ...stage,
      actionHref:
        stage.id === "raw_compatibility"
          ? undefined
          : "/interventions?stage=full_audit",
      humanLabel: "Diagnostic evidence",
      state: "diagnostic",
    };
  }

  if (stage.id === "repair_build") {
    return {
      ...stage,
      actionHref: "/interventions?stage=repair_build",
      command: "npm run pipeline -- run isolate-blockers",
      humanLabel: "Fix strict build mismatches",
      state: "needs_rerun",
    };
  }

  if (stage.id === "blocker_residuals") {
    return {
      ...stage,
      actionHref: "/interventions?stage=blocker_residuals",
      command: "npm run pipeline -- run blocker_residuals",
      humanLabel: "Fix tracked blocker residuals",
      state: "needs_rerun",
    };
  }

  if (stage.id === "glyph_forge") {
    return {
      ...stage,
      actionHref: "/interventions?stage=glyph_forge",
      command: "npm run pipeline -- run glyph_forge",
      humanLabel: "Reconstruct flagged whole glyphs",
      state: "needs_human",
    };
  }

  return {
    ...stage,
    command: `npm run pipeline -- run ${stage.id}`,
    humanLabel: "Rerun stage",
    state: "needs_rerun",
  };
}

function reviewTier(
  hasPending: boolean,
  requiresReconstruction: boolean
): InterventionGlyph["tier"] {
  if (requiresReconstruction) {
    return "must_decide";
  }
  if (hasPending) {
    return "candidate";
  }
  return "backlog";
}

function compareInterventionGlyphs(
  a: InterventionGlyph,
  b: InterventionGlyph
): number {
  const tierOrder = { backlog: 2, candidate: 1, must_decide: 0 };
  return (
    tierOrder[a.tier] - tierOrder[b.tier] ||
    VERDICT_RANK[a.verdict] - VERDICT_RANK[b.verdict] ||
    (a.worstComposite ?? Number.POSITIVE_INFINITY) -
      (b.worstComposite ?? Number.POSITIVE_INFINITY) ||
    (b.gain ?? Number.NEGATIVE_INFINITY) -
      (a.gain ?? Number.NEGATIVE_INFINITY) ||
    a.key.localeCompare(b.key)
  );
}

function parseResidualIssues(text: string): ResidualIssue[] {
  const issues: ResidualIssue[] = [];
  let family: Family | null = null;
  for (const line of text.split("\n")) {
    if (line === "## Roman") {
      family = "roman";
    } else if (line === "## Italic") {
      family = "italic";
    } else if (family && line.startsWith("- `")) {
      const issue = parseResidualLine(family, line);
      if (issue.failures.length > 0) {
        issues.push(issue);
      }
    }
  }
  return issues;
}

function parseResidualLine(family: Family, line: string): ResidualIssue {
  const glyph = line.match(/^- `([^`]+)`/)?.[1] ?? "unknown";
  const strategy = line.match(/ strategy=([^ ]+)/)?.[1];
  const frozen = line.includes(" frozen=True ");
  const riskyWeights = parseWeights(
    line.match(/riskyWeights=\[([^\]]*)\]/)?.[1]
  );
  const maxAreaDrift = parseDrift(line.match(/maxAreaDrift=([^ ]+)/)?.[1]);
  const failures: string[] = [];
  if (maxAreaDrift !== null && maxAreaDrift > 25) {
    failures.push(`area drift ${maxAreaDrift.toFixed(2)}%`);
  }
  if (riskyWeights.length > 0) {
    failures.push(`short segments at ${riskyWeights.join(", ")}`);
  }
  if (/interpolatable=([1-9][0-9]*)/.test(line)) {
    failures.push("interpolatable issue remains");
  }
  if (/sourceAudit=(?!0\/0\/0\/0)([^ ]+)/.test(line)) {
    failures.push("source structure issue remains");
  }

  return {
    failures,
    family,
    frozen,
    glyph,
    key: `${family}/${glyph}`,
    maxAreaDrift,
    riskyWeights,
    strategy,
  };
}

function parseWeights(raw: string | undefined): number[] {
  if (!raw?.trim()) {
    return [];
  }
  return raw
    .split(",")
    .map((value) => Number(value.trim()))
    .filter(Number.isFinite);
}

function parseDrift(raw: string | undefined): number | null {
  if (!raw || raw === "None") {
    return null;
  }
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

async function readPipelineStatus(): Promise<PipelineStatusReport | null> {
  const raw = await readText(PIPELINE_STATUS_PATH);
  return raw ? (JSON.parse(raw) as PipelineStatusReport) : null;
}

async function checkArtifactFreshness(): Promise<ArtifactFreshness> {
  const entries = await Promise.all(
    CACHE_ARTIFACTS.map(async ([label, filePath]) => ({
      label,
      mtimeMs: await mtimeMs(filePath),
    }))
  );
  const missing = entries.filter((entry) => entry.mtimeMs === null);
  if (missing.length > 0) {
    return {
      message: `Missing app artifact${missing.length === 1 ? "" : "s"}: ${missing
        .map((entry) => entry.label)
        .join(", ")}. Run npm run pipeline:app to resync the workspace.`,
      stale: true,
    };
  }

  const statusTime = entries.find(
    (entry) => entry.label === "pipeline status"
  )?.mtimeMs;
  if (statusTime === null || statusTime === undefined) {
    return {
      message: "Pipeline status is missing. Run npm run pipeline:status.",
      stale: true,
    };
  }

  const newer = entries.filter(
    (entry) =>
      entry.label !== "pipeline status" &&
      (entry.mtimeMs ?? 0) > statusTime + 1000
  );
  if (newer.length > 0) {
    return {
      message: `Pipeline status is older than ${newer
        .map((entry) => entry.label)
        .join(", ")}. Run npm run pipeline:status before applying decisions.`,
      stale: true,
    };
  }

  return {
    message: "Pipeline artifacts are current.",
    stale: false,
  };
}

async function mtimeMs(filePath: string): Promise<number | null> {
  try {
    const stats = await stat(filePath);
    return stats.mtimeMs;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return null;
    }
    throw error;
  }
}

async function readText(filePath: string): Promise<string | null> {
  try {
    return await readFile(filePath, "utf-8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return null;
    }
    throw error;
  }
}
