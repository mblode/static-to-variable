import "server-only";
import { readFile } from "node:fs/promises";
import path from "node:path";

import type {
  BrokenGlyph,
  CellScores,
  GlyphScores,
  SolverVerdict,
  StrategySuggestion,
} from "@static-to-variable/glyph-forge-engine";

let manifestCache: BrokenGlyph[] | null = null;
let glyphScoresCache: Record<string, GlyphScores> | null | undefined;
let cellScoresCache: Record<string, CellScores> | null | undefined;
let suggestionsCache: Record<string, StrategySuggestion> | null | undefined;
let solverResultsCache: Record<string, SolverVerdict> | null | undefined;

const BROKEN_GLYPHS_PATH = path.join(
  process.cwd(),
  "public",
  "broken-glyphs.json"
);
const GLYPH_SCORES_PATH = path.join(
  process.cwd(),
  "public",
  "glyph-scores.json"
);
const CELL_SCORES_PATH = path.join(process.cwd(), "public", "cell-scores.json");
const STRATEGY_SUGGESTIONS_PATH = path.join(
  process.cwd(),
  "public",
  "strategy-suggestions.json"
);
const SOLVER_RESULTS_PATH = path.join(
  process.cwd(),
  "public",
  "solver-results.json"
);

export async function loadManifest(): Promise<BrokenGlyph[]> {
  if (manifestCache) {
    return manifestCache;
  }
  const raw = await readFile(BROKEN_GLYPHS_PATH, "utf-8");
  manifestCache = JSON.parse(raw) as BrokenGlyph[];
  return manifestCache;
}

export async function loadGlyphScores(): Promise<Record<
  string,
  GlyphScores
> | null> {
  if (glyphScoresCache !== undefined) {
    return glyphScoresCache;
  }
  try {
    const raw = await readFile(GLYPH_SCORES_PATH, "utf-8");
    glyphScoresCache = JSON.parse(raw) as Record<string, GlyphScores>;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      glyphScoresCache = null;
    } else {
      throw error;
    }
  }
  return glyphScoresCache;
}

export async function loadCellScores(): Promise<Record<
  string,
  CellScores
> | null> {
  if (cellScoresCache !== undefined) {
    return cellScoresCache;
  }
  try {
    const raw = await readFile(CELL_SCORES_PATH, "utf-8");
    cellScoresCache = JSON.parse(raw) as Record<string, CellScores>;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      cellScoresCache = null;
    } else {
      throw error;
    }
  }
  return cellScoresCache;
}

export async function loadSuggestions(): Promise<Record<
  string,
  StrategySuggestion
> | null> {
  if (suggestionsCache !== undefined) {
    return suggestionsCache;
  }
  try {
    const raw = await readFile(STRATEGY_SUGGESTIONS_PATH, "utf-8");
    suggestionsCache = JSON.parse(raw) as Record<string, StrategySuggestion>;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      suggestionsCache = null;
    } else {
      throw error;
    }
  }
  return suggestionsCache;
}

export async function loadSolverResults(): Promise<Record<
  string,
  SolverVerdict
> | null> {
  if (solverResultsCache !== undefined) {
    return solverResultsCache;
  }
  try {
    const raw = await readFile(SOLVER_RESULTS_PATH, "utf-8");
    solverResultsCache = JSON.parse(raw) as Record<string, SolverVerdict>;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      solverResultsCache = null;
    } else {
      throw error;
    }
  }
  return solverResultsCache;
}
