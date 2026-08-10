"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { FONTS, weightLabel } from "@/lib/fonts";
import { cn } from "@/lib/utils";

const [FONT] = FONTS;
const FONT_FAMILY = "stvfilestack";
const MERGED_FILENAME = `${FONT.name}-VF.woff2`;

/** Illustrative merge — rare, so a little longer than routine UI. */
const MERGE_MS = 520;
/** Brief hold on the fused file before the specimen reveals. */
const HOLD_MS = 220;
/** Demo entrance after the files layer exits. */
const REVEAL_MS = 280;

const EASE_ENTER = "cubic-bezier(0.22, 1, 0.36, 1)";
const EASE_MOVE = "cubic-bezier(0.25, 1, 0.5, 1)";

const CHIPS = [
  { label: "Thin", weight: 100 },
  { label: "Regular", weight: 400 },
  { label: "Bold", weight: 700 },
] as const;

async function activateFont(
  file: string,
  stillCurrent: () => boolean
): Promise<void> {
  const buf = await fetch(file).then((r) => r.arrayBuffer());
  const face = new FontFace(FONT_FAMILY, buf);
  await face.load();
  if (!stillCurrent()) {
    return;
  }
  const stale: FontFace[] = [];
  for (const f of document.fonts) {
    if (f.family === FONT_FAMILY) {
      stale.push(f);
    }
  }
  for (const f of stale) {
    document.fonts.delete(f);
  }
  document.fonts.add(face);
}

type Phase = "stack" | "merging" | "merged";
type LoadStatus = "loading" | "ready" | "error";

function statusCopy(
  status: LoadStatus,
  phase: Phase,
  showDemo: boolean
): string {
  if (status === "error") {
    return "Could not load the preview font. Try refreshing.";
  }
  if (status === "loading") {
    return "Loading preview font…";
  }
  if (showDemo) {
    return "1 file · every weight";
  }
  if (phase === "stack") {
    return "3 files · one weight each";
  }
  return "Combining…";
}

function layerMotion(visible: boolean, reducedMotion: boolean, exitY: number) {
  return {
    opacity: visible ? 1 : 0,
    pointerEvents: visible ? ("auto" as const) : ("none" as const),
    transform: visible ? "translateY(0)" : `translateY(${exitY}px)`,
    transition: reducedMotion
      ? "none"
      : `opacity ${REVEAL_MS}ms ${EASE_ENTER}, transform ${REVEAL_MS}ms ${EASE_MOVE}`,
  };
}

function chipMotion(index: number, phase: Phase) {
  const consolidating = phase === "merging" || phase === "merged";
  const isSide = index !== 1;
  const towardCenter = index === 0 ? "42%" : index === 2 ? "-42%" : "0";

  let transform = "translateX(0) scale(1)";
  if (consolidating && isSide) {
    transform = `translateX(${towardCenter}) scale(0.86)`;
  } else if (phase === "merging" && !isSide) {
    transform = "translateX(0) scale(1.05)";
  }

  return {
    opacity: consolidating && isSide ? 0 : 1,
    transform,
    transition: `opacity ${MERGE_MS}ms ${EASE_ENTER}, transform ${MERGE_MS}ms ${EASE_MOVE}`,
    transitionDelay: consolidating ? `${index * 40}ms` : "0ms",
    zIndex: index === 1 ? 2 : 1,
  } as const;
}

/**
 * Hero visualization: three static-weight chips collapse into one variable
 * font, then a weight slider morphs the live specimen.
 *
 * Motion is transform/opacity only (continuity + delight). Layout properties
 * stay fixed so the stage never jumps.
 */
interface WeightChipProps {
  chip: (typeof CHIPS)[number];
  index: number;
  phase: Phase;
  reducedMotion: boolean;
}

function WeightChip({ chip, index, phase, reducedMotion }: WeightChipProps) {
  const isCenter = index === 1;
  const fused = isCenter && phase === "merged";

  return (
    <div
      className="flex flex-col items-center gap-3 rounded-xl bg-background px-2 py-5 ring-1 ring-foreground/10 sm:px-4 sm:py-6"
      style={
        reducedMotion
          ? { opacity: phase !== "stack" && !isCenter ? 0 : 1 }
          : chipMotion(index, phase)
      }
    >
      <span
        className={cn(
          "font-mono text-[10px] text-muted-foreground tracking-wide sm:text-[11px]",
          fused && "text-foreground"
        )}
      >
        {fused ? MERGED_FILENAME : chip.label}
      </span>
      <span
        aria-hidden
        className="select-none text-[clamp(2rem,8vw,3.25rem)] leading-none tracking-tight"
        style={{
          fontFamily: FONT_FAMILY,
          fontVariationSettings: `'wght' ${chip.weight}`,
        }}
      >
        Aa
      </span>
    </div>
  );
}

export function FileStackCollapse({ className }: { className?: string }) {
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [phase, setPhase] = useState<Phase>("stack");
  const [showDemo, setShowDemo] = useState(false);
  const [weight, setWeight] = useState(FONT.axis.def);
  const [reducedMotion, setReducedMotion] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const token = useRef(0);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const hasAutoplayed = useRef(false);

  const clearTimers = useCallback(() => {
    for (const t of timers.current) {
      clearTimeout(t);
    }
    timers.current = [];
  }, []);

  const after = useCallback((ms: number, fn: () => void) => {
    const id = setTimeout(fn, ms);
    timers.current.push(id);
  }, []);

  const triggerMerge = useCallback(
    (instant = false) => {
      clearTimers();
      setShowDemo(false);
      setWeight(FONT.axis.def);

      if (instant || reducedMotion) {
        setPhase("merged");
        setShowDemo(true);
        return;
      }

      setPhase("merging");
      after(MERGE_MS + 80, () => {
        setPhase("merged");
        after(HOLD_MS, () => setShowDemo(true));
      });
    },
    [after, clearTimers, reducedMotion]
  );

  const handleCombine = useCallback(() => {
    if (status !== "ready" || phase === "merging") {
      return;
    }
    if (phase === "merged") {
      clearTimers();
      setShowDemo(false);
      setPhase("stack");
      setWeight(FONT.axis.def);
      after(reducedMotion ? 0 : 40, () => triggerMerge(reducedMotion));
      return;
    }
    triggerMerge(reducedMotion);
  }, [after, clearTimers, phase, reducedMotion, status, triggerMerge]);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    token.current += 1;
    const id = token.current;
    setStatus("loading");
    activateFont(FONT.file, () => token.current === id)
      .then(() => {
        if (token.current === id) {
          setStatus("ready");
        }
      })
      .catch(() => {
        if (token.current === id) {
          setStatus("error");
        }
      });
  }, []);

  useEffect(() => {
    if (status !== "ready") {
      return;
    }

    if (reducedMotion) {
      hasAutoplayed.current = true;
      triggerMerge(true);
      return;
    }

    if (hasAutoplayed.current) {
      return;
    }

    const node = rootRef.current;
    if (!node) {
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting || hasAutoplayed.current) {
          return;
        }
        hasAutoplayed.current = true;
        observer.disconnect();
        triggerMerge(false);
      },
      { threshold: 0.4 }
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [reducedMotion, status, triggerMerge]);

  useEffect(() => clearTimers, [clearTimers]);

  const previewStyle = {
    fontFamily: FONT_FAMILY,
    fontVariationSettings: `'wght' ${weight}`,
  } as const;

  const filesVisible = !showDemo;
  const demoVisible = showDemo;
  const combineLabel =
    phase === "merged"
      ? "Replay the combine animation"
      : "Combine into one file";

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10",
        className
      )}
      ref={rootRef}
    >
      {/* Fixed stage height: no layout animation. */}
      <div className="relative flex min-h-[280px] items-center justify-center px-5 py-10 sm:min-h-[320px] sm:px-8">
        {/* Files layer */}
        <div
          aria-hidden={!filesVisible}
          className="absolute inset-0 flex items-center justify-center px-5 sm:px-8"
          style={layerMotion(filesVisible, reducedMotion, -6)}
        >
          <div className="grid w-full max-w-lg grid-cols-3 gap-2 sm:gap-3">
            {CHIPS.map((chip, index) => (
              <WeightChip
                chip={chip}
                index={index}
                key={chip.label}
                phase={phase}
                reducedMotion={reducedMotion}
              />
            ))}
          </div>
        </div>

        {/* Variable-font layer */}
        <div
          className="absolute inset-0 flex flex-col items-center justify-center gap-8 px-5 sm:px-8"
          style={layerMotion(demoVisible, reducedMotion, 10)}
        >
          <div
            aria-hidden
            className="select-none text-[clamp(4rem,16vw,7rem)] leading-none tracking-tight"
            style={previewStyle}
          >
            Aa
          </div>

          <div className="flex w-full max-w-md items-center gap-3 text-muted-foreground text-sm">
            <span className="shrink-0">Weight</span>
            <Slider
              aria-label="Font weight"
              className="min-w-0 flex-1"
              max={FONT.axis.max}
              min={FONT.axis.min}
              onValueChange={(next) => setWeight(next[0])}
              step={1}
              value={[weight]}
            />
            <span className="flex shrink-0 items-baseline gap-1.5 text-foreground">
              <span>{weightLabel(Math.round(weight))}</span>
              <span className="font-mono text-muted-foreground text-xs tabular-nums">
                {Math.round(weight)}
              </span>
            </span>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 border-t px-4 py-3 sm:px-6">
        <p aria-live="polite" className="text-muted-foreground text-xs">
          {statusCopy(status, phase, showDemo)}
        </p>

        <Button
          aria-label={combineLabel}
          disabled={status !== "ready" || phase === "merging"}
          onClick={handleCombine}
          size="sm"
          type="button"
          variant={showDemo ? "outline" : "default"}
        >
          {showDemo ? "Replay" : "Combine"}
        </Button>
      </div>
    </div>
  );
}
