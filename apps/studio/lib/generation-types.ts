export type GenerationJobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "needs_review"
  | "failed"
  | "cancelled";

export type GenerationStageStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped";

export type GenerationInputRole =
  | "donor"
  | "glyphs_source"
  | "triage_manifest"
  | "pending_triage"
  | "other";

export type GenerationStageId =
  | "prepare_workspace"
  | "install_inputs"
  | "inventory"
  | "raw_compatibility"
  | "repair_build"
  | "audit_interpolation"
  | "full_audit"
  | "glyph_forge"
  | "auto_convergence"
  | "blocker_residuals"
  | "pipeline_status"
  | "collect_outputs";

export interface GenerationStageDefinition {
  id: GenerationStageId;
  title: string;
  phase: string;
  blocking: boolean;
}

export const GENERATION_STAGES: readonly GenerationStageDefinition[] = [
  {
    blocking: true,
    id: "prepare_workspace",
    phase: "Intake",
    title: "Prepare isolated repo",
  },
  {
    blocking: true,
    id: "install_inputs",
    phase: "Intake",
    title: "Install uploaded sources",
  },
  {
    blocking: true,
    id: "inventory",
    phase: "Raw analysis",
    title: "Donor inventory",
  },
  {
    blocking: false,
    id: "raw_compatibility",
    phase: "Raw analysis",
    title: "Raw compatibility",
  },
  {
    blocking: true,
    id: "repair_build",
    phase: "Generation",
    title: "Repair and build",
  },
  {
    blocking: false,
    id: "audit_interpolation",
    phase: "Verification",
    title: "Interior audit",
  },
  {
    blocking: false,
    id: "full_audit",
    phase: "Verification",
    title: "Full audit",
  },
  {
    blocking: true,
    id: "glyph_forge",
    phase: "Verification",
    title: "Visual QA solve",
  },
  {
    blocking: true,
    id: "auto_convergence",
    phase: "Automation",
    title: "Auto-converge decisions",
  },
  {
    blocking: true,
    id: "blocker_residuals",
    phase: "Verification",
    title: "Residual validation",
  },
  {
    blocking: true,
    id: "pipeline_status",
    phase: "Gate",
    title: "Promotion status",
  },
  {
    blocking: true,
    id: "collect_outputs",
    phase: "Output",
    title: "Collect artifacts",
  },
];

export interface GenerationInput {
  id: string;
  originalName: string;
  storedName: string;
  size: number;
  sha256: string;
  role: GenerationInputRole;
  family?: string;
  weight?: number;
  targetPath?: string;
}

export interface GenerationStageRun {
  id: GenerationStageId;
  title: string;
  phase: string;
  blocking: boolean;
  status: GenerationStageStatus;
  startedAt?: string;
  finishedAt?: string;
  durationMs?: number;
  command?: string;
  error?: string;
  summary?: string;
}

export interface GenerationArtifact {
  id: string;
  label: string;
  fileName: string;
  relativePath: string;
  size: number;
  sha256?: string;
  contentType: string;
}

export interface GenerationJob {
  id: string;
  status: GenerationJobStatus;
  createdAt: string;
  updatedAt: string;
  startedAt?: string;
  finishedAt?: string;
  useWorkspaceSources: boolean;
  inputs: GenerationInput[];
  stages: GenerationStageRun[];
  artifacts: GenerationArtifact[];
  warnings: string[];
  error?: string;
  isolatedRepoPath?: string;
  pipelineVerdict?: "pass" | "fail";
}

export function createInitialGenerationStages(): GenerationStageRun[] {
  return GENERATION_STAGES.map((stage) => ({
    ...stage,
    status: "pending",
  }));
}

export function isActiveGenerationStatus(status: GenerationJobStatus): boolean {
  return status === "queued" || status === "running";
}
