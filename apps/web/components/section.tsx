import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Vertical rhythm shared with convene: full section padding, soft top rule.
 * Keep breakpoints viewport-based — the page container is already max-w-5xl.
 */
export function Section({
  className,
  children,
  ...props
}: ComponentProps<"section">) {
  return (
    <section
      className={cn(
        "scroll-mt-20 border-border/60 border-t py-16 sm:py-24",
        className
      )}
      {...props}
    >
      {children}
    </section>
  );
}

interface SectionHeadingProps {
  children: ReactNode;
  className?: string;
  eyebrow?: string;
  lede?: ReactNode;
  action?: ReactNode;
}

/** Eyebrow + headline + lede — convene’s SectionHeading, adapted to Glide. */
export function SectionHeading({
  children,
  className,
  eyebrow,
  lede,
  action,
}: SectionHeadingProps) {
  return (
    <div
      className={cn(
        action && "flex flex-wrap items-end justify-between gap-x-6 gap-y-4",
        className
      )}
    >
      <div className="min-w-0">
        {eyebrow ? (
          <p className="mb-3 font-medium text-muted-foreground text-sm tracking-wide">
            {eyebrow}
          </p>
        ) : null}
        <h2 className="max-w-[24ch] text-balance font-semibold text-3xl leading-[1.15] tracking-tight sm:text-4xl sm:tracking-[-0.02em]">
          {children}
        </h2>
        {lede ? (
          <p className="mt-4 max-w-[48ch] text-pretty text-lg text-muted-foreground leading-relaxed">
            {lede}
          </p>
        ) : null}
      </div>
      {action}
    </div>
  );
}
