import type { CellScores } from "@static-to-variable/glyph-forge-engine";

import { svgPath } from "@/lib/data";
import type { Family } from "@/lib/data";
import { cn } from "@/lib/utils";

import { ScoreBadge } from "./score-badge";

export type CellStyle = "donor" | "glide" | "overlay";

export function WeightCell({
  family,
  glyph,
  wght,
  weightName,
  style,
  scores,
}: {
  family: Family;
  glyph: string;
  wght: number;
  weightName: string;
  style: CellStyle;
  scores?: CellScores;
}) {
  const donorSrc = svgPath(family, glyph, wght, "donor");
  const glideSrc = svgPath(family, glyph, wght, "glide");
  const boxCls = "relative w-full aspect-square rounded bg-muted/60 p-3";

  const overlay = (
    <div className={boxCls}>
      {/* biome-ignore lint/a11y/useAltText: cell is decorative, weight in label below */}
      <img
        src={donorSrc}
        alt=""
        loading="lazy"
        decoding="async"
        data-glyph-cell
        className="absolute inset-0 m-auto h-[calc(100%-1.5rem)] w-[calc(100%-1.5rem)] text-[--color-donor] opacity-60 mix-blend-multiply"
      />
      {/* biome-ignore lint/a11y/useAltText: cell is decorative, weight in label below */}
      <img
        src={glideSrc}
        alt=""
        loading="lazy"
        decoding="async"
        data-glyph-cell
        className="absolute inset-0 m-auto h-[calc(100%-1.5rem)] w-[calc(100%-1.5rem)] text-[--color-glide] opacity-80 mix-blend-multiply"
      />
      {style === "overlay" && scores && (
        <div className="absolute right-1.5 top-1.5">
          <ScoreBadge composite={scores.composite} compact />
        </div>
      )}
    </div>
  );

  if (style === "overlay") {
    return (
      <div className="flex flex-col gap-1.5">
        {overlay}
        <CellFooter wght={wght} weightName={weightName} scores={scores} />
      </div>
    );
  }

  const src = style === "donor" ? donorSrc : glideSrc;
  const color =
    style === "donor" ? "text-[--color-donor]" : "text-[--color-glide]";

  return (
    <div className="flex flex-col gap-1.5">
      <div className={boxCls}>
        {/* biome-ignore lint/a11y/useAltText: cell is decorative, weight in label below */}
        <img
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          data-glyph-cell
          className={cn("h-full w-full", color)}
        />
      </div>
      <span className="text-center font-mono text-[10px] text-muted-foreground/70">
        {wght}
      </span>
    </div>
  );
}

function CellFooter({
  wght,
  weightName,
  scores,
}: {
  wght: number;
  weightName: string;
  scores?: CellScores;
}) {
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="font-mono text-[10px] text-muted-foreground/70">
        {weightName} · {wght}
      </span>
      {scores && (
        <div
          className="flex items-center gap-1 font-mono text-[9px] text-muted-foreground/70"
          title={`void ${scores.void.toFixed(2)} · irr ${scores.irregularity.toFixed(2)} · drift ${scores.drift.toFixed(2)}`}
        >
          <span>v {scores.void.toFixed(2)}</span>
          <span>·</span>
          <span>d {scores.drift.toFixed(2)}</span>
        </div>
      )}
    </div>
  );
}
