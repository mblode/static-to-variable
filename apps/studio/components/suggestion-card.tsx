import type { StrategySuggestion } from "@static-to-variable/glyph-forge-engine";

import { cn } from "@/lib/utils";

const STRATEGY_LABEL: Record<StrategySuggestion["strategy"], string> = {
  donor_copy: "Donor copy",
  inherit_base_contours: "Inherit base contours",
  manual_review: "Manual review",
  rebuild_notdef: "Rebuild .notdef",
  reference_fallback: "Reference fallback",
  structural_fallback: "Structural fallback",
  weighted_fallback: "Weighted fallback",
};

const STRATEGY_COLOR: Record<StrategySuggestion["strategy"], string> = {
  donor_copy: "text-[--color-band-green]",
  inherit_base_contours: "text-[--color-band-amber]",
  manual_review: "text-[--color-band-red]",
  rebuild_notdef: "text-muted-foreground",
  reference_fallback: "text-muted-foreground",
  structural_fallback: "text-[--color-band-amber]",
  weighted_fallback: "text-[--color-band-green]",
};

export function SuggestionCard({
  suggestion,
  currentStrategy,
}: {
  suggestion: StrategySuggestion;
  currentStrategy?: string;
}) {
  const differsFromCurrent =
    currentStrategy !== undefined &&
    currentStrategy !== null &&
    currentStrategy !== suggestion.strategy;
  const pct = Math.round(suggestion.confidence * 100);
  return (
    <section className="flex flex-col gap-2 rounded-lg border border-border bg-background p-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground/70">
          Suggested strategy
        </h2>
        <span
          title={`confidence ${suggestion.confidence.toFixed(2)}`}
          className="font-mono text-[10px] text-muted-foreground/70"
        >
          {pct}%
        </span>
      </div>
      <p
        className={cn(
          "font-mono text-sm font-medium",
          STRATEGY_COLOR[suggestion.strategy]
        )}
      >
        {STRATEGY_LABEL[suggestion.strategy]}
      </p>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {suggestion.reason}
      </p>
      {differsFromCurrent && (
        <div className="mt-1 rounded border border-[--color-band-amber]/30 bg-[--color-band-amber]/10 px-2 py-1.5 text-[11px] text-[--color-band-amber]">
          Triage manifest currently specifies{" "}
          <code className="font-mono">{currentStrategy}</code>. Consider
          updating or confirming the recommendation.
        </div>
      )}
      {currentStrategy && !differsFromCurrent && (
        <p className="text-[11px] text-[--color-band-green]/80">
          ✓ Matches triage manifest.
        </p>
      )}
    </section>
  );
}
