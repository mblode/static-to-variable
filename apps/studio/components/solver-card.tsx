"use client";

import type {
  SolverCandidate,
  SolverCandidateName,
  SolverVerdict,
} from "@static-to-variable/glyph-forge-engine";
import { useCallback, useState, useTransition } from "react";

import { scoreBand } from "@/lib/data";
import type { Family } from "@/lib/data";
import { cn } from "@/lib/utils";

const CAND_LABEL: Record<SolverCandidateName, string> = {
  donor_copy: "Donor copy",
  reference_fallback: "Reference fallback",
  weighted_fallback: "Weighted fallback",
};

function pct(x: number | null | undefined): string {
  if (x === null || x === undefined) {
    return "—";
  }
  return Math.round(x * 100).toString();
}

function Tile({
  candidate,
  winner,
}: {
  candidate: SolverCandidate;
  winner: boolean;
}) {
  const band = scoreBand(candidate.projectedWorst);
  const bandCls =
    band === "green"
      ? "text-[--color-band-green]"
      : band === "amber"
        ? "text-[--color-band-amber]"
        : "text-[--color-band-red]";
  const params = candidate.params
    ? Object.entries(candidate.params)
        .filter(
          ([k]) =>
            k !== "referenceWght" || candidate.strategy === "reference_fallback"
        )
        .map(([k, v]) => `${k} ${v}`)
        .join(" · ")
    : "";
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-2 rounded border border-border p-2",
        winner && "bg-[--color-band-green]/10 border-[--color-band-green]/40"
      )}
    >
      <div className="flex flex-col">
        <span
          className={cn(
            "font-mono text-[11px]",
            winner ? "text-[--color-band-green] font-medium" : "text-foreground"
          )}
        >
          {winner && "✓ "}
          {CAND_LABEL[candidate.strategy]}
        </span>
        {params && (
          <span className="font-mono text-[9px] text-muted-foreground/70">
            {params}
          </span>
        )}
      </div>
      <div className="flex flex-col items-end">
        <span className={cn("font-mono text-xs tabular-nums", bandCls)}>
          {pct(candidate.projectedWorst)}
        </span>
        <span className="font-mono text-[9px] text-muted-foreground/70">
          avg {pct(candidate.projectedAvg)}
          {candidate.worstWght !== null && ` · ⤓ ${candidate.worstWght}`}
        </span>
      </div>
    </div>
  );
}

export function SolverCard({
  verdict,
  family,
  glyph,
  staged,
}: {
  verdict: SolverVerdict;
  family: Family;
  glyph: string;
  staged: boolean;
}) {
  const [isPending, startTransition] = useTransition();
  const [stagedLocal, setStagedLocal] = useState(staged);
  const [error, setError] = useState<string | null>(null);

  const stageBest = useCallback(() => {
    if (!verdict.best) {
      return;
    }
    setError(null);
    startTransition(async () => {
      const res = await fetch("/api/triage/stage", {
        body: JSON.stringify({
          family,
          glyph,
          strategy: verdict.best,
          source: "manual", // solver is a machine author
          notes: `Solver verdict: projected worst ${pct(verdict.bestProjected)} @ wght ${verdict.bestWorstWght}${
            verdict.currentWorst !== null
              ? ` (was ${pct(verdict.currentWorst)}, gain ${pct(verdict.gain)})`
              : ""
          }`,
        }),
        headers: { "content-type": "application/json" },
        method: "POST",
      });
      if (!res.ok) {
        setError(`stage failed (${res.status})`);
        return;
      }
      setStagedLocal(true);
    });
  }, [family, glyph, verdict]);

  const gainDisplay =
    verdict.gain === null
      ? "—"
      : `${verdict.gain > 0 ? "+" : ""}${Math.round(verdict.gain * 100)}`;

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-background p-3">
      <div className="flex items-center justify-between">
        <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground/70">
          Solver verdict
        </h2>
        {verdict.gain !== null && (
          <span
            className={cn(
              "rounded px-2 py-0.5 font-mono text-[10px] font-medium tabular-nums",
              verdict.gain > 0.2
                ? "bg-[--color-band-green]/15 text-[--color-band-green]"
                : verdict.gain > 0
                  ? "bg-[--color-band-amber]/15 text-[--color-band-amber]"
                  : "bg-[--color-band-unknown]/15 text-muted-foreground/70"
            )}
            title={`projected ${pct(verdict.bestProjected)} vs current ${pct(verdict.currentWorst)}`}
          >
            gain {gainDisplay}
          </span>
        )}
      </div>

      {verdict.best ? (
        <>
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "font-mono text-sm font-medium",
                scoreBand(verdict.bestProjected) === "green"
                  ? "text-[--color-band-green]"
                  : scoreBand(verdict.bestProjected) === "amber"
                    ? "text-[--color-band-amber]"
                    : "text-[--color-band-red]"
              )}
            >
              {CAND_LABEL[verdict.best]}
            </span>
            <span className="font-mono text-xs text-muted-foreground">
              projected {pct(verdict.bestProjected)}
              {verdict.bestWorstWght !== null &&
                ` · worst @ ${verdict.bestWorstWght}`}
            </span>
          </div>

          <div className="flex flex-col gap-1.5">
            {verdict.candidates.map((c) => (
              <Tile
                key={c.strategy}
                candidate={c}
                winner={c.strategy === verdict.best}
              />
            ))}
          </div>

          {stagedLocal ? (
            <p className="rounded border border-[--color-band-amber]/30 bg-[--color-band-amber]/10 px-2 py-1.5 font-mono text-[11px] text-[--color-band-amber]">
              ✓ Staged — review on{" "}
              <a href="/triage" className="underline">
                /triage
              </a>
            </p>
          ) : (
            <button
              type="button"
              onClick={stageBest}
              disabled={isPending}
              className="rounded-md border border-[--color-band-green]/40 bg-[--color-band-green]/10 px-3 py-1.5 font-mono text-xs text-[--color-band-green] transition-colors hover:bg-[--color-band-green]/20 disabled:opacity-50"
            >
              {isPending
                ? "Staging…"
                : `↗ Stage solver verdict (${CAND_LABEL[verdict.best]})`}
            </button>
          )}
        </>
      ) : (
        <p className="text-xs text-muted-foreground/70">
          No candidate produced a scorable projection — likely missing from
          donor or glide at all weights.
        </p>
      )}

      {error && (
        <p className="font-mono text-[11px] text-[--color-band-red]">{error}</p>
      )}
    </section>
  );
}
