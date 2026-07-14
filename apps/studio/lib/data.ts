import type {
  BrokenGlyph,
  CellScores,
  GlyphScores,
  SolverVerdict,
} from "@static-to-variable/glyph-forge-engine";

export { scoreBand } from "@static-to-variable/glyph-forge-engine";
export type {
  CellScores,
  GlyphScores,
  ScoreBand,
  SolverVerdict,
} from "@static-to-variable/glyph-forge-engine";

export type Family = "roman" | "italic";
export type AuditVerdict = BrokenGlyph["auditVerdict"];

export const VERDICT_LABEL: Record<AuditVerdict, string> = {
  blocker: "Blocker",
  high: "High",
  low: "Low",
  medium: "Medium",
  tracked: "Tracked",
  unknown: "Unknown",
};

export const VERDICT_ORDER: AuditVerdict[] = [
  "blocker",
  "high",
  "tracked",
  "medium",
  "low",
  "unknown",
];

export const CIRCULAR_WEIGHTS = [
  { name: "Thin", wght: 250 },
  { name: "Light", wght: 300 },
  { name: "Regular", wght: 400 },
  { name: "Book", wght: 450 },
  { name: "Medium", wght: 500 },
  { name: "Bold", wght: 700 },
  { name: "Black", wght: 900 },
  { name: "ExtraBlack", wght: 950 },
] as const;

export function svgPath(
  family: Family,
  glyph: string,
  wght: number,
  source: "donor" | "glide"
): string {
  return `/svg/${family}/${encodeURIComponent(glyph)}/${wght}-${source}.svg`;
}

export function glyphKey(family: Family, name: string): string {
  return `${family}/${name}`;
}

export function cellKey(family: Family, name: string, wght: number): string {
  return `${family}/${name}/${wght}`;
}

export function collectFeatures(glyphs: BrokenGlyph[]): string[] {
  const set = new Set<string>();
  for (const g of glyphs) {
    for (const f of g.features) {
      set.add(f);
    }
  }
  return [...set].toSorted();
}

export type ScoredGlyph = BrokenGlyph & {
  scores?: GlyphScores;
  solver?: SolverVerdict;
};

export function attachGlyphScores(
  glyphs: BrokenGlyph[],
  scores: Record<string, GlyphScores> | null,
  solver?: Record<string, SolverVerdict> | null
): ScoredGlyph[] {
  if (!scores && !solver) {
    return glyphs;
  }
  return glyphs.map((g) => {
    const k = glyphKey(g.family, g.name);
    const next: ScoredGlyph = { ...g };
    const s = scores?.[k];
    if (s) {
      next.scores = s;
    }
    const v = solver?.[k];
    if (v) {
      next.solver = v;
    }
    return next;
  });
}

export function cellScoreLookup(
  scores: Record<string, CellScores> | null,
  family: Family,
  name: string
): (wght: number) => CellScores | undefined {
  return (wght) => scores?.[cellKey(family, name, wght)];
}
