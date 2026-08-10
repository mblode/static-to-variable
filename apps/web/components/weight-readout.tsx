import { weightLabel } from "@/lib/fonts";
import { cn } from "@/lib/utils";

/**
 * Stable-width weight display for sliders. Named labels differ a lot
 * ("Thin" vs "ExtraLight"), so without a fixed box the track reflows every
 * notch — the classic "wiggy" scrubber.
 */
export function WeightReadout({
  weight,
  className,
}: {
  weight: number;
  className?: string;
}) {
  const rounded = Math.round(weight);

  return (
    <span
      className={cn(
        "inline-grid w-[10.5rem] shrink-0 grid-cols-[1fr_2.75rem] items-baseline gap-x-1.5 text-foreground",
        className
      )}
    >
      <span className="truncate text-right">{weightLabel(rounded)}</span>
      <span className="text-right font-mono text-muted-foreground text-xs tabular-nums">
        {rounded}
      </span>
    </span>
  );
}
