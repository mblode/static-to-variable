"use client";

import type { ScoreBand } from "@static-to-variable/glyph-forge-engine";

import { VERDICT_LABEL, VERDICT_ORDER } from "@/lib/data";
import type { AuditVerdict, Family } from "@/lib/data";
import { cn } from "@/lib/utils";

export type SortKey =
  | "score-asc"
  | "score-desc"
  | "gain-desc"
  | "severity"
  | "name";

export interface GridFilters {
  family: Family | "all";
  verdicts: Set<AuditVerdict>;
  features: Set<string>;
  bands: Set<ScoreBand>;
  search: string;
  sort: SortKey;
}

const BAND_LABEL: Record<ScoreBand, string> = {
  amber: "Amber 30-70",
  green: "Green 70+",
  red: "Red <30",
  unknown: "No score",
};

const BAND_COLOR: Record<ScoreBand, string> = {
  amber: "bg-[--color-band-amber]",
  green: "bg-[--color-band-green]",
  red: "bg-[--color-band-red]",
  unknown: "bg-[--color-band-unknown]",
};

function toggle<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) {
    next.delete(value);
  } else {
    next.add(value);
  }
  return next;
}

export function FilterBar({
  filters,
  setFilters,
  allFeatures,
  familyCounts,
  totalVisible,
  totalAll,
  hasScores,
  hasSolver,
}: {
  filters: GridFilters;
  setFilters: (f: GridFilters) => void;
  allFeatures: string[];
  familyCounts: Record<"roman" | "italic", number>;
  totalVisible: number;
  totalAll: number;
  hasScores: boolean;
  hasSolver: boolean;
}) {
  return (
    <div className="sticky top-0 z-10 border-b border-border bg-background/90 backdrop-blur">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3 px-6 py-3 text-sm">
        <div className="flex items-center gap-1">
          <FilterChip
            active={filters.family === "all"}
            onClick={() => setFilters({ ...filters, family: "all" })}
          >
            All <span className="text-muted-foreground/70">{totalAll}</span>
          </FilterChip>
          <FilterChip
            active={filters.family === "italic"}
            onClick={() => setFilters({ ...filters, family: "italic" })}
          >
            Italic{" "}
            <span className="text-muted-foreground/70">
              {familyCounts.italic}
            </span>
          </FilterChip>
          <FilterChip
            active={filters.family === "roman"}
            onClick={() => setFilters({ ...filters, family: "roman" })}
          >
            Roman{" "}
            <span className="text-muted-foreground/70">
              {familyCounts.roman}
            </span>
          </FilterChip>
        </div>

        <Divider />

        <div className="flex flex-wrap items-center gap-1">
          {VERDICT_ORDER.map((v) => (
            <FilterChip
              key={v}
              active={filters.verdicts.has(v)}
              onClick={() =>
                setFilters({
                  ...filters,
                  verdicts: toggle(filters.verdicts, v),
                })
              }
            >
              {VERDICT_LABEL[v]}
            </FilterChip>
          ))}
        </div>

        {hasScores && (
          <>
            <Divider />
            <div className="flex flex-wrap items-center gap-1">
              {(["red", "amber", "green", "unknown"] as ScoreBand[]).map(
                (b) => (
                  <FilterChip
                    key={b}
                    active={filters.bands.has(b)}
                    onClick={() =>
                      setFilters({
                        ...filters,
                        bands: toggle(filters.bands, b),
                      })
                    }
                  >
                    <span
                      className={cn("h-1.5 w-1.5 rounded-full", BAND_COLOR[b])}
                    />
                    {BAND_LABEL[b]}
                  </FilterChip>
                )
              )}
            </div>
          </>
        )}

        <Divider />

        <select
          value={filters.sort}
          onChange={(e) =>
            setFilters({ ...filters, sort: e.target.value as SortKey })
          }
          className="h-8 rounded-md border border-border bg-card px-2 text-xs text-foreground focus:border-ring focus:outline-none"
        >
          {hasScores && (
            <option value="score-asc">Sort: worst score first</option>
          )}
          {hasScores && (
            <option value="score-desc">Sort: best score first</option>
          )}
          {hasSolver && (
            <option value="gain-desc">Sort: biggest solver gain</option>
          )}
          <option value="severity">Sort: audit severity</option>
          <option value="name">Sort: name</option>
        </select>

        <input
          value={filters.search}
          onChange={(e) => setFilters({ ...filters, search: e.target.value })}
          placeholder="Search glyph name"
          className="h-8 w-48 rounded-md border border-border bg-card px-2 text-xs text-foreground placeholder:text-muted-foreground/70 focus:border-ring focus:outline-none"
        />

        <div className="ml-auto font-mono text-xs text-muted-foreground/70">
          {totalVisible} / {totalAll}
        </div>
      </div>

      {allFeatures.length > 0 && (
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-1 px-6 pb-3 text-xs">
          <span className="text-muted-foreground/70">Features:</span>
          {allFeatures.map((f) => (
            <FilterChip
              key={f}
              active={filters.features.has(f)}
              onClick={() =>
                setFilters({
                  ...filters,
                  features: toggle(filters.features, f),
                })
              }
              compact
            >
              {f}
            </FilterChip>
          ))}
          {filters.features.size > 0 && (
            <button
              type="button"
              onClick={() => setFilters({ ...filters, features: new Set() })}
              className="ml-1 rounded px-2 py-0.5 text-muted-foreground/70 hover:text-foreground"
            >
              clear
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Divider() {
  return <div className="h-6 w-px bg-border" />;
}

function FilterChip({
  active,
  compact,
  children,
  onClick,
}: {
  active: boolean;
  compact?: boolean;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-md font-mono text-xs transition-colors",
        compact ? "px-1.5 py-0.5" : "px-2.5 py-1",
        active
          ? "bg-foreground text-background"
          : "border border-border text-muted-foreground hover:border-muted-foreground hover:text-foreground"
      )}
    >
      {children}
    </button>
  );
}
