import type { AuditVerdict } from "@/lib/data";
import { cn } from "@/lib/utils";

const VERDICT_CLASS: Record<AuditVerdict, string> = {
  blocker: "bg-[--color-verdict-blocker]",
  high: "bg-[--color-verdict-high]",
  low: "bg-[--color-verdict-low]",
  medium: "bg-[--color-verdict-medium]",
  tracked: "bg-[--color-verdict-tracked]",
  unknown: "bg-[--color-verdict-unknown]",
};

export function VerdictDot({
  verdict,
  className,
}: {
  verdict: AuditVerdict;
  className?: string;
}) {
  return (
    <span
      aria-label={verdict}
      title={verdict}
      className={cn(
        "inline-block h-2 w-2 shrink-0 rounded-full",
        VERDICT_CLASS[verdict],
        className
      )}
    />
  );
}
