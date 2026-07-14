export type Family = "roman" | "italic";

export type GlyphSource = "audit" | "user_seed";

export type AuditVerdict =
  | "blocker"
  | "high"
  | "medium"
  | "low"
  | "tracked"
  | "unknown";

export interface BrokenGlyph {
  name: string;
  family: Family;
  unicode?: string;
  features: string[];
  sources: GlyphSource[];
  auditVerdict: AuditVerdict;
  severityScore?: number;
  existingStrategy?: string;
  priority?: string;
  notes?: string;
}

export interface CircularWeight {
  name:
    | "Thin"
    | "Light"
    | "Regular"
    | "Book"
    | "Medium"
    | "Bold"
    | "Black"
    | "ExtraBlack";
  wght: number;
}

export const CIRCULAR_WEIGHTS: readonly CircularWeight[] = [
  { name: "Thin", wght: 250 },
  { name: "Light", wght: 300 },
  { name: "Regular", wght: 400 },
  { name: "Book", wght: 450 },
  { name: "Medium", wght: 500 },
  { name: "Bold", wght: 700 },
  { name: "Black", wght: 900 },
  { name: "ExtraBlack", wght: 950 },
] as const;

export type GlyphCellSource = "donor" | "glide";

export type SvgCellPath =
  `${Family}/${string}/${number}-${GlyphCellSource}.svg`;

export interface CellScores {
  void: number;
  irregularity: number;
  drift: number;
  composite: number;
}

export interface GlyphScores {
  worstWght: number | null;
  worstComposite: number | null;
  avgComposite: number | null;
  missingCells: number;
}

// Keyed strings matching the Python output
export type CellScoreKey = `${Family}/${string}/${number}`;
export type GlyphScoreKey = `${Family}/${string}`;

export type ScoreBand = "red" | "amber" | "green" | "unknown";

export function scoreBand(composite: number | null | undefined): ScoreBand {
  if (composite === null || composite === undefined) {
    return "unknown";
  }
  if (composite < 0.3) {
    return "red";
  }
  if (composite < 0.7) {
    return "amber";
  }
  return "green";
}

export type StrategyName =
  | "donor_copy"
  | "structural_fallback"
  | "weighted_fallback"
  | "inherit_base_contours"
  | "reference_fallback"
  | "rebuild_notdef"
  | "manual_review";

export interface StrategySuggestion {
  strategy: StrategyName;
  confidence: number;
  reason: string;
  matchesExisting?: boolean | null;
}

export interface PendingManifestPatch {
  repair_bucket?: string;
  base_glyph?: string;
  brace_weights?: number[];
  priority?: string;
  deferred?: boolean;
  defer_reason?: string;
}

export interface PendingTriageEdit {
  family: Family;
  glyph: string;
  strategy: StrategyName;
  source: "suggestion" | "manual";
  notes?: string;
  manifestPatch?: PendingManifestPatch;
  stagedAt: string; // ISO 8601
  previousStrategy?: string | null;
}

export const STRATEGY_NAMES: readonly StrategyName[] = [
  "donor_copy",
  "structural_fallback",
  "weighted_fallback",
  "inherit_base_contours",
  "reference_fallback",
  "rebuild_notdef",
  "manual_review",
] as const;

export type SolverCandidateName =
  | "donor_copy"
  | "reference_fallback"
  | "weighted_fallback";

export interface SolverCandidate {
  strategy: SolverCandidateName;
  projectedWorst: number;
  projectedAvg: number;
  worstWght: number | null;
  perWeight: Record<string, number>;
  params?: Record<string, number>;
}

export interface SolverVerdict {
  family: Family;
  glyph: string;
  currentWorst: number | null;
  currentWorstWght: number | null;
  best: SolverCandidateName | null;
  bestProjected: number | null;
  bestWorstWght: number | null;
  gain: number | null;
  requiresReconstruction?: boolean;
  reconstructionReason?: string | null;
  reconstructionSignals?: Record<string, number | string | null>;
  candidates: SolverCandidate[];
}
