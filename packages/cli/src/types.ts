export type StageKind = "blocking" | "diagnostic" | "reporting" | "sync";

export interface PipelineStage {
  id: string;
  title: string;
  kind: StageKind;
  description: string;
  command: string;
  args: string[];
  artifact?: string;
  defaultEnabled?: boolean;
  mutatesSources?: boolean;
}

export interface StagePlanOptions {
  blockingOnly?: boolean;
  from?: string;
  skipDiagnostics?: boolean;
  to?: string;
}

export type HandoffMode = "prompt" | "auto" | "off";

export interface RunOptions {
  continueOnFail?: boolean;
  dryRun?: boolean;
  handoff?: HandoffMode;
  top?: number;
}

export interface StatusPrintOptions {
  handoff?: HandoffMode;
  top?: number;
}

export interface StageRunResult {
  code: number;
  durationMs: number;
  stage: PipelineStage;
}

export interface PipelineStatusReport {
  verdict: "pass" | "fail" | string;
  summary?: Record<string, unknown>;
  stages?: {
    id: string;
    name: string;
    kind: string;
    status: string;
    blocking: boolean;
    artifact: string;
    failures?: string[];
    observations?: string[];
    summary?: Record<string, unknown>;
  }[];
}
