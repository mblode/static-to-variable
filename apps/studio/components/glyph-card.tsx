import Link from "next/link";

import { svgPath } from "@/lib/data";
import type { ScoredGlyph } from "@/lib/data";
import { cn } from "@/lib/utils";

import { FeatureTag } from "./feature-tag";
import { ScoreBadge } from "./score-badge";
import { VerdictDot } from "./verdict-dot";

export function GlyphCard({ glyph }: { glyph: ScoredGlyph }) {
  const thumb = svgPath(glyph.family, glyph.name, 400, "glide");
  const worst = glyph.scores?.worstComposite ?? null;
  const gain = glyph.solver?.gain ?? null;
  return (
    <Link
      href={`/g/${glyph.family}/${encodeURIComponent(glyph.name)}`}
      className="group flex flex-col gap-2 rounded-lg border border-border bg-card p-3 text-foreground transition-colors hover:border-muted-foreground hover:bg-accent focus:outline-none focus-visible:border-ring"
    >
      <div className="relative aspect-square w-full rounded bg-muted p-2">
        {/* biome-ignore lint/a11y/useAltText: glyph name in label below */}
        <img
          loading="lazy"
          decoding="async"
          src={thumb}
          alt=""
          data-glyph-cell
          className="h-full w-full text-foreground"
        />
        <span className="absolute right-1.5 top-1.5">
          <VerdictDot verdict={glyph.auditVerdict} />
        </span>
        {glyph.scores?.worstWght !== null &&
          glyph.scores?.worstWght !== undefined && (
            <span className="absolute bottom-1.5 left-1.5 rounded bg-muted px-1 py-0.5 font-mono text-[9px] text-muted-foreground/70">
              worst @ {glyph.scores.worstWght}
            </span>
          )}
        {gain !== null && gain > 0.1 && (
          <span
            className={cn(
              "absolute bottom-1.5 right-1.5 rounded px-1 py-0.5 font-mono text-[9px] font-medium",
              gain > 0.3
                ? "bg-[--color-band-green]/80 text-black"
                : "bg-[--color-band-amber]/80 text-black"
            )}
            title={`solver: +${Math.round(gain * 100)} projected (${glyph.solver?.best})`}
          >
            +{Math.round(gain * 100)}
          </span>
        )}
      </div>
      <div className="flex items-center justify-between gap-1">
        <span className="truncate font-mono text-xs text-foreground">
          {glyph.name}
        </span>
        <ScoreBadge composite={worst} compact />
      </div>
      {glyph.features.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {glyph.features.map((f) => (
            <FeatureTag key={f} feature={f} />
          ))}
        </div>
      )}
    </Link>
  );
}
