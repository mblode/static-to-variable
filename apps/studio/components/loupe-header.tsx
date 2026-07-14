import type { ScoredGlyph } from "@/lib/data";
import { VERDICT_LABEL } from "@/lib/data";

import { ExportButton } from "./export-button";
import { FeatureTag } from "./feature-tag";
import { ScoreBadge } from "./score-badge";
import { VerdictDot } from "./verdict-dot";

export function LoupeHeader({
  glyph,
  stagedStrategy,
}: {
  glyph: ScoredGlyph;
  stagedStrategy?: string;
}) {
  const { scores } = glyph;
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-4 px-6 py-4">
        <h1 className="font-mono text-xl tracking-tight">
          <span className="text-muted-foreground/70">{glyph.family}/</span>
          <span>{glyph.name}</span>
        </h1>
        {glyph.unicode && (
          <span className="rounded-md bg-background px-2 py-0.5 font-mono text-xs text-muted-foreground">
            {glyph.unicode}
          </span>
        )}
        {glyph.features.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {glyph.features.map((f) => (
              <FeatureTag key={f} feature={f} />
            ))}
          </div>
        )}
        <div className="ml-auto flex items-center gap-4">
          {stagedStrategy && (
            <span className="rounded-md border border-[--color-band-amber]/40 bg-[--color-band-amber]/10 px-2 py-1 font-mono text-[11px] text-[--color-band-amber]">
              staged → {stagedStrategy}
            </span>
          )}
          <ExportButton family={glyph.family} name={glyph.name} />
          <div className="flex items-center gap-2">
            <VerdictDot verdict={glyph.auditVerdict} />
            <span className="font-mono text-xs text-muted-foreground">
              {VERDICT_LABEL[glyph.auditVerdict]}
              {glyph.severityScore !== undefined && ` · ${glyph.severityScore}`}
            </span>
          </div>
          {scores && (
            <div className="flex items-center gap-2">
              <ScoreBadge composite={scores.worstComposite} />
              <span className="font-mono text-xs text-muted-foreground">
                worst
                {scores.worstWght !== null && ` @ ${scores.worstWght}`}
              </span>
              {scores.avgComposite !== null && (
                <span className="font-mono text-xs text-muted-foreground/70">
                  · avg {Math.round(scores.avgComposite * 100)}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
