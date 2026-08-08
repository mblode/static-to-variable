/**
 * Reads the engine's per-style `built (...)` line back into structured data for
 * `build --json`. The engine prints one such line per style; everything the CLI
 * reports about layout and hinting comes from it.
 */

export type LayoutMode = "variable" | "variable-kern" | "static" | "none";

export interface ParsedBuildStyle {
  style?: string;
  frozen: string[];
  layout: {
    mode: LayoutMode;
    tables: string[];
    note?: string;
    summary: string;
  };
  hinting?: string;
  summary: string;
}

const BUILT_LINE =
  /^(?:\[([^\]]+)\]\s+)?built\s+\(frozen:\s*(.*?);\s*(layout:\s*(variable-kern|variable|static|none)(?:\s*\(([^)]*)\))?)(?:;\s*(hinting:.*?))?\s*\)\s*$/;

/**
 * Parse engine lines like
 * `[roman] built (frozen: ['a']; layout: variable (GDEF, GSUB, GPOS); hinting: smooth (gasp, prep))`.
 */
export function parseBuildEngineOutput(stdout: string): ParsedBuildStyle[] {
  const results: ParsedBuildStyle[] = [];
  for (const line of stdout.split(/\r?\n/)) {
    const built = line.match(BUILT_LINE);
    if (!built) {
      continue;
    }
    const [
      ,
      style,
      frozenRawMatch,
      layoutSummaryRaw,
      modeRaw,
      parenRaw,
      hintingRaw,
    ] = built;
    const frozenRaw = frozenRawMatch ?? "";
    const layoutSummary = (layoutSummaryRaw ?? "").trim();
    const mode = (modeRaw ?? "none") as LayoutMode;
    const paren = (parenRaw ?? "").trim();
    const tables: string[] = [];
    let layoutNote: string | undefined;
    if (paren) {
      for (const part of paren.split(",")) {
        const token = part.trim();
        if (!token) {
          continue;
        }
        if (/^[A-Z0-9]{4}$/.test(token)) {
          tables.push(token);
        } else if (layoutNote) {
          layoutNote = `${layoutNote}, ${token}`;
        } else {
          layoutNote = token;
        }
      }
    }
    const frozen = [...frozenRaw.matchAll(/'([^']+)'/g)].flatMap((m) => {
      const [, name] = m;
      return name ? [name] : [];
    });
    results.push({
      frozen,
      hinting: hintingRaw?.trim(),
      layout: {
        mode,
        note: layoutNote,
        summary: layoutSummary,
        tables,
      },
      style,
      summary: layoutSummary,
    });
  }
  return results;
}
