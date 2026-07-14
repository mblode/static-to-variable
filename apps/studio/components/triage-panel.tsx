"use client";

import { STRATEGY_NAMES } from "@static-to-variable/glyph-forge-engine";
import type {
  PendingTriageEdit,
  StrategyName,
  StrategySuggestion,
} from "@static-to-variable/glyph-forge-engine";
import Link from "next/link";
import { useCallback, useState, useTransition } from "react";

import type { Family } from "@/lib/data";
import { cn } from "@/lib/utils";

const STRATEGY_LABEL: Record<StrategyName, string> = {
  donor_copy: "Donor copy",
  inherit_base_contours: "Inherit base contours",
  manual_review: "Manual review",
  rebuild_notdef: "Rebuild .notdef",
  reference_fallback: "Reference fallback",
  structural_fallback: "Structural fallback",
  weighted_fallback: "Weighted fallback",
};

export function TriagePanel({
  family,
  glyph,
  currentStrategy,
  suggestion,
  initialPending,
}: {
  family: Family;
  glyph: string;
  currentStrategy?: string;
  suggestion?: StrategySuggestion;
  initialPending: PendingTriageEdit | null;
}) {
  const [pending, setPending] = useState<PendingTriageEdit | null>(
    initialPending
  );
  const [manualStrategy, setManualStrategy] = useState<StrategyName>(
    suggestion?.strategy ?? "manual_review"
  );
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const suggestionMatchesPending =
    suggestion && pending && pending.strategy === suggestion.strategy;

  const stage = useCallback(
    (strategy: StrategyName, source: "suggestion" | "manual") => {
      setError(null);
      startTransition(async () => {
        const res = await fetch("/api/triage/stage", {
          body: JSON.stringify({ family, glyph, strategy, source }),
          headers: { "content-type": "application/json" },
          method: "POST",
        });
        if (!res.ok) {
          setError(`stage failed (${res.status})`);
          return;
        }
        const data = (await res.json()) as { edit: PendingTriageEdit };
        setPending(data.edit);
      });
    },
    [family, glyph]
  );

  const unstage = useCallback(() => {
    setError(null);
    startTransition(async () => {
      const res = await fetch("/api/triage/unstage", {
        body: JSON.stringify({ family, glyph }),
        headers: { "content-type": "application/json" },
        method: "POST",
      });
      if (!res.ok) {
        setError(`unstage failed (${res.status})`);
        return;
      }
      setPending(null);
    });
  }, [family, glyph]);

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-background p-3">
      <div className="flex items-center justify-between">
        <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground/70">
          Triage queue
        </h2>
        {pending && (
          <Link
            href="/triage"
            className="rounded border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground hover:text-foreground"
          >
            review all →
          </Link>
        )}
      </div>

      {pending ? (
        <div className="rounded border border-[--color-band-amber]/30 bg-[--color-band-amber]/10 p-2.5">
          <p className="font-mono text-xs text-[--color-band-amber]">
            Staged: {STRATEGY_LABEL[pending.strategy]}
          </p>
          <p className="mt-0.5 text-[10px] text-muted-foreground/70">
            source: {pending.source} · staged{" "}
            {new Date(pending.stagedAt).toLocaleTimeString()}
            {pending.previousStrategy !== null &&
              pending.previousStrategy !== undefined &&
              ` · previously ${pending.previousStrategy}`}
          </p>
          <button
            type="button"
            onClick={unstage}
            disabled={isPending}
            className="mt-2 rounded border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            {isPending ? "Removing…" : "Unstage"}
          </button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground/70">
          No pending edit. Stage a suggestion or pick a strategy manually.
        </p>
      )}

      {suggestion && !suggestionMatchesPending && (
        <button
          type="button"
          onClick={() => stage(suggestion.strategy, "suggestion")}
          disabled={isPending}
          className={cn(
            "rounded-md border border-[--color-band-green]/40 bg-[--color-band-green]/10 px-3 py-1.5 font-mono text-xs text-[--color-band-green] transition-colors hover:bg-[--color-band-green]/20 disabled:opacity-50"
          )}
        >
          ↗ Stage suggestion: {STRATEGY_LABEL[suggestion.strategy]}
        </button>
      )}

      <div className="flex items-center gap-2">
        <select
          value={manualStrategy}
          onChange={(e) => setManualStrategy(e.target.value as StrategyName)}
          className="h-8 flex-1 rounded-md border border-border bg-card px-2 font-mono text-xs text-foreground focus:border-ring focus:outline-none"
        >
          {STRATEGY_NAMES.map((s) => (
            <option key={s} value={s}>
              {STRATEGY_LABEL[s]}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => stage(manualStrategy, "manual")}
          disabled={isPending}
          className="rounded-md border border-border bg-card px-2.5 py-1.5 font-mono text-xs text-foreground transition-colors hover:border-ring disabled:opacity-50"
        >
          Stage manual
        </button>
      </div>

      {currentStrategy && (
        <p className="font-mono text-[10px] text-muted-foreground/70">
          current: {currentStrategy}
        </p>
      )}

      {error && (
        <p className="font-mono text-[11px] text-[--color-band-red]">{error}</p>
      )}
    </section>
  );
}
