import { cn } from "@/lib/utils";

export function FeatureTag({
  feature,
  className,
}: {
  feature: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wide text-muted-foreground ring-1 ring-inset ring-border",
        className
      )}
    >
      {feature}
    </span>
  );
}
