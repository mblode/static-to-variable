"use client";

import { CopyCommand } from "@/components/copy-command";

const APPLY_DRY_RUN =
  "npm --workspace @static-to-variable/glyph-forge-engine run apply -- --dry-run";
const APPLY =
  "npm --workspace @static-to-variable/glyph-forge-engine run apply";

export function ApplyPendingPanel({ pendingCount }: { pendingCount: number }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground/70">
            Pending decisions
          </h2>
          <p className="mt-1 font-mono text-2xl tabular-nums">{pendingCount}</p>
        </div>
        <div className="flex gap-2">
          <CopyCommand command={APPLY_DRY_RUN} label="copy dry-run" />
          <CopyCommand command={APPLY} label="copy apply" />
        </div>
      </div>

      <div className="mt-4 grid gap-2">
        <code className="block break-words rounded-md bg-muted p-2 font-mono text-[11px] text-foreground">
          {APPLY_DRY_RUN}
        </code>
        <code className="block break-words rounded-md bg-muted p-2 font-mono text-[11px] text-foreground">
          {APPLY}
        </code>
      </div>
    </section>
  );
}
