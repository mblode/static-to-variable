"use client";

import type {
  SolverCandidate,
  SolverCandidateName,
  SolverVerdict,
} from "@static-to-variable/glyph-forge-engine";
import { useState } from "react";

import { CIRCULAR_WEIGHTS } from "@/lib/data";
import type { Family } from "@/lib/data";
import { cn } from "@/lib/utils";

import { ProjectionCell } from "./projection-cell";
import { ScoreBadge } from "./score-badge";

const STRATEGY_LABEL: Record<SolverCandidateName, string> = {
  donor_copy: "Donor copy",
  reference_fallback: "Reference fallback",
  weighted_fallback: "Weighted fallback",
};

export function ProjectionRow({
  family,
  glyph,
  verdict,
}: {
  family: Family;
  glyph: string;
  verdict: SolverVerdict;
}) {
  const [selected, setSelected] = useState<SolverCandidateName | null>(
    verdict.best
  );

  if (!selected) {
    return null;
  }
  const candidate = verdict.candidates.find((c) => c.strategy === selected);
  if (!candidate) {
    return null;
  }

  const alpha =
    candidate.strategy === "weighted_fallback" &&
    candidate.params?.alpha !== undefined
      ? Number(candidate.params.alpha)
      : 0.5;

  return (
    <section className="flex flex-col gap-2">
      <header className="flex flex-wrap items-center gap-2">
        <span className="inline-block h-2 w-2 rounded-full bg-[--color-band-green]" />
        <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
          Projected
        </h2>
        <div className="flex items-center gap-1">
          {verdict.candidates.map((c) => (
            <CandidateChip
              key={c.strategy}
              candidate={c}
              active={c.strategy === selected}
              isWinner={c.strategy === verdict.best}
              onClick={() => setSelected(c.strategy)}
            />
          ))}
        </div>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground/70">
          approximate · CSS composition of existing cells
        </span>
      </header>
      <div className="grid grid-cols-4 gap-3 md:grid-cols-8">
        {CIRCULAR_WEIGHTS.map((w) => {
          const voidScore = candidate.perWeight[String(w.wght)];
          return (
            <ProjectionCell
              key={w.wght}
              family={family}
              glyph={glyph}
              wght={w.wght}
              strategy={candidate.strategy}
              alpha={alpha}
              score={
                voidScore === undefined
                  ? undefined
                  : {
                      void: voidScore,
                      irregularity: 1,
                      drift: 1,
                      composite: voidScore,
                    }
              }
            />
          );
        })}
      </div>
    </section>
  );
}

function CandidateChip({
  candidate,
  active,
  isWinner,
  onClick,
}: {
  candidate: SolverCandidate;
  active: boolean;
  isWinner: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-[11px] transition-colors",
        active
          ? "bg-foreground text-background"
          : "border border-border text-muted-foreground hover:border-muted-foreground hover:text-foreground"
      )}
    >
      {isWinner && <span className="text-[--color-band-green]">✓</span>}
      <span>{STRATEGY_LABEL[candidate.strategy]}</span>
      <ScoreBadge composite={candidate.projectedWorst} compact />
    </button>
  );
}
