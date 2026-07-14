"use client";

import type { ScoreBand } from "@static-to-variable/glyph-forge-engine";
import { useMemo, useState } from "react";

import type { ScoredGlyph } from "@/lib/data";
import { scoreBand } from "@/lib/data";

import { FilterBar } from "./filter-bar";
import type { GridFilters, SortKey } from "./filter-bar";
import { GlyphCard } from "./glyph-card";

export function Grid({ glyphs }: { glyphs: ScoredGlyph[] }) {
  const allFeatures = useMemo(() => {
    const s = new Set<string>();
    for (const g of glyphs) {
      for (const f of g.features) {
        s.add(f);
      }
    }
    return [...s].toSorted();
  }, [glyphs]);

  const familyCounts = useMemo(() => {
    const c = { italic: 0, roman: 0 };
    for (const g of glyphs) {
      c[g.family] += 1;
    }
    return c;
  }, [glyphs]);

  const hasScores = useMemo(() => glyphs.some((g) => g.scores), [glyphs]);
  const hasSolver = useMemo(() => glyphs.some((g) => g.solver), [glyphs]);

  const [filters, setFilters] = useState<GridFilters>({
    bands: new Set<ScoreBand>(),
    family: "italic",
    features: new Set(),
    search: "",
    sort: hasSolver ? "gain-desc" : hasScores ? "score-asc" : "name",
    verdicts: new Set(["blocker", "high", "tracked"]),
  });

  const visible = useMemo(() => {
    const search = filters.search.trim().toLowerCase();
    const filtered = glyphs.filter((g) => {
      if (filters.family !== "all" && g.family !== filters.family) {
        return false;
      }
      if (filters.verdicts.size > 0 && !filters.verdicts.has(g.auditVerdict)) {
        return false;
      }
      if (filters.features.size > 0) {
        const has = g.features.some((f) => filters.features.has(f));
        if (!has) {
          return false;
        }
      }
      if (filters.bands.size > 0) {
        const band = scoreBand(g.scores?.worstComposite ?? null);
        if (!filters.bands.has(band)) {
          return false;
        }
      }
      if (search && !g.name.toLowerCase().includes(search)) {
        return false;
      }
      return true;
    });
    return sortGlyphs(filtered, filters.sort);
  }, [glyphs, filters]);

  return (
    <>
      <FilterBar
        filters={filters}
        setFilters={setFilters}
        allFeatures={allFeatures}
        familyCounts={familyCounts}
        totalVisible={visible.length}
        totalAll={glyphs.length}
        hasScores={hasScores}
        hasSolver={hasSolver}
      />
      <div className="mx-auto max-w-[1600px] px-6 py-6">
        {visible.length === 0 ? (
          <p className="py-20 text-center text-sm text-muted-foreground/70">
            No glyphs match the current filters.
          </p>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(128px,1fr))] gap-3">
            {visible.map((g) => (
              <GlyphCard key={`${g.family}/${g.name}`} glyph={g} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function sortGlyphs(glyphs: ScoredGlyph[], sort: SortKey): ScoredGlyph[] {
  const arr = [...glyphs];
  switch (sort) {
    case "score-asc": {
      return arr.toSorted(
        (a, b) =>
          (a.scores?.worstComposite ?? Number.POSITIVE_INFINITY) -
          (b.scores?.worstComposite ?? Number.POSITIVE_INFINITY)
      );
    }
    case "score-desc": {
      return arr.toSorted(
        (a, b) =>
          (b.scores?.worstComposite ?? Number.NEGATIVE_INFINITY) -
          (a.scores?.worstComposite ?? Number.NEGATIVE_INFINITY)
      );
    }
    case "gain-desc": {
      return arr.toSorted(
        (a, b) =>
          (b.solver?.gain ?? Number.NEGATIVE_INFINITY) -
          (a.solver?.gain ?? Number.NEGATIVE_INFINITY)
      );
    }
    case "severity": {
      return arr.toSorted(
        (a, b) => (b.severityScore ?? 0) - (a.severityScore ?? 0)
      );
    }
    default: {
      return arr.toSorted((a, b) => a.name.localeCompare(b.name));
    }
  }
}
