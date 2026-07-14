import { scoreBand } from "@/lib/data";
import type { ScoreBand } from "@/lib/data";
import { cn } from "@/lib/utils";

const BAND_CLASS: Record<ScoreBand, string> = {
  amber:
    "bg-[--color-band-amber]/15 text-[--color-band-amber] ring-[--color-band-amber]/40",
  green:
    "bg-[--color-band-green]/15 text-[--color-band-green] ring-[--color-band-green]/40",
  red: "bg-[--color-band-red]/15 text-[--color-band-red] ring-[--color-band-red]/40",
  unknown: "bg-[--color-band-unknown]/15 text-muted-foreground/70 ring-border",
};

export function ScoreBadge({
  composite,
  className,
  compact,
}: {
  composite: number | null | undefined;
  className?: string;
  compact?: boolean;
}) {
  const band = scoreBand(composite);
  const label =
    composite === null || composite === undefined
      ? "—"
      : Math.round(composite * 100).toString();
  return (
    <span
      title={
        composite === null || composite === undefined
          ? "no score"
          : `composite ${composite.toFixed(3)}`
      }
      className={cn(
        "inline-flex items-center justify-center rounded font-mono font-medium ring-1 ring-inset tabular-nums",
        compact
          ? "h-4 min-w-[1.9rem] text-[10px]"
          : "h-5 min-w-[2.2rem] text-xs",
        BAND_CLASS[band],
        className
      )}
    >
      {label}
    </span>
  );
}
