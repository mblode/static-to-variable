"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { FONTS, weightLabel } from "@/lib/fonts";
import { cn } from "@/lib/utils";

const [FONT] = FONTS;
const FONT_FAMILY = "stvfilestack";
const MERGED_FILENAME = `${FONT.name}-VF.woff2`;
const MERGE_MS = 700;

const CHIPS = [
  { label: "Thin", weight: 100, file: `${FONT.name}-Thin.woff2` },
  { label: "Regular", weight: 400, file: `${FONT.name}-Regular.woff2` },
  { label: "Bold", weight: 700, file: `${FONT.name}-Bold.woff2` },
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

function chipPreviewStyle(weight: number) {
  return {
    fontFamily: FONT_FAMILY,
    fontVariationSettings: `'wght' ${weight}`,
  } as const;
}

function fileChipClassName(index: number, phase: Phase, showDemo: boolean) {
  const isCenter = index === 1;
  const hideSide = phase === "merging" || phase === "merged";

  return cn(
    "flex w-full max-w-[220px] items-center gap-3 rounded-lg bg-background px-4 py-3 ring-1 ring-foreground/10 transition-all duration-700 ease-in-out sm:w-auto",
    phase === "stack" && "translate-x-0 translate-y-0 scale-100 opacity-100",
    phase === "merging" &&
      (isCenter
        ? "z-10 scale-105 opacity-100"
        : "pointer-events-none scale-90 opacity-0"),
    phase === "merged" &&
      !showDemo &&
      (isCenter
        ? "z-10 w-full max-w-[260px] scale-100 opacity-100"
        : "absolute scale-75 opacity-0"),
    hideSide && !isCenter && "absolute inset-x-0 mx-auto",
    phase === "merging" &&
      !isCenter &&
      (index === 0
        ? "-translate-x-6 -translate-y-2"
        : "translate-x-6 translate-y-2")
  );
}

function fileChipTransitionStyle(
  index: number,
  phase: Phase,
  showDemo: boolean
) {
  const isCenter = index === 1;
  if (phase !== "merged" || showDemo || !isCenter) {
    return { transitionDelay: `${index * 40}ms` };
  }
}

function fileChipFilename(
  chip: (typeof CHIPS)[number],
  index: number,
  phase: Phase,
  showDemo: boolean
) {
  const isCenter = index === 1;
  return phase === "merged" && !showDemo && isCenter
    ? MERGED_FILENAME
    : chip.file;
}

interface FileChipProps {
  chip: (typeof CHIPS)[number];
  index: number;
  phase: Phase;
  showDemo: boolean;
}

function FileChip({ chip, index, phase, showDemo }: FileChipProps) {
  const isCenter = index === 1;

  return (
    <div
      className={fileChipClassName(index, phase, showDemo)}
      style={fileChipTransitionStyle(index, phase, showDemo)}
    >
      <span
        className={cn(
          "min-w-0 truncate font-mono text-[11px] text-muted-foreground sm:text-xs",
          phase === "merged" && !showDemo && isCenter && "text-foreground"
        )}
      >
        {fileChipFilename(chip, index, phase, showDemo)}
      </span>
      <span
        aria-hidden
        className="ml-auto shrink-0 text-2xl leading-none"
        style={chipPreviewStyle(chip.weight)}
      >
        Aa
      </span>
    </div>
  );
}

/**
 * Hero visualization: three static-weight file chips collapse into one
 * variable font, then a weight slider morphs the live specimen.
 */
export function FileStackCollapse({ className }: { className?: string }) {
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading"
  );
  const [phase, setPhase] = useState<Phase>("stack");
  const [showDemo, setShowDemo] = useState(false);
  const [weight, setWeight] = useState(FONT.axis.def);
  const [reducedMotion, setReducedMotion] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const token = useRef(0);
  const mergeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const demoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasAutoplayed = useRef(false);

  const clearTimers = useCallback(() => {
    if (mergeTimer.current) {
      clearTimeout(mergeTimer.current);
      mergeTimer.current = null;
    }
    if (demoTimer.current) {
      clearTimeout(demoTimer.current);
      demoTimer.current = null;
    }
  }, []);

  const finishMerge = useCallback(() => {
    setPhase("merged");
    demoTimer.current = setTimeout(() => setShowDemo(true), 180);
  }, []);

  const triggerMerge = useCallback(
    (instant = false) => {
      clearTimers();
      setShowDemo(false);

      if (instant || reducedMotion) {
        setPhase("merged");
        setShowDemo(true);
        return;
      }

      setPhase("merging");
      mergeTimer.current = setTimeout(finishMerge, MERGE_MS);
    },
    [clearTimers, finishMerge, reducedMotion]
  );

  const reset = useCallback(() => {
    clearTimers();
    setPhase("stack");
    setShowDemo(false);
    setWeight(FONT.axis.def);
  }, [clearTimers]);

  const handleCombine = useCallback(() => {
    if (status !== "ready") {
      return;
    }
    if (phase === "merged") {
      reset();
      requestAnimationFrame(() => triggerMerge(reducedMotion));
      return;
    }
    if (phase === "stack") {
      triggerMerge(reducedMotion);
    }
  }, [phase, reducedMotion, reset, status, triggerMerge]);

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
      { threshold: 0.35 }
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [reducedMotion, status, triggerMerge]);

  useEffect(() => clearTimers, [clearTimers]);

  const previewStyle = {
    fontFamily: FONT_FAMILY,
    fontVariationSettings: `'wght' ${weight}`,
  } as const;

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
      <div className="flex flex-col items-center px-5 py-8 sm:px-8 sm:py-10">
        <div
          aria-hidden={phase === "merged" && showDemo}
          className={cn(
            "relative flex w-full max-w-md flex-col items-center justify-center gap-3 sm:flex-row sm:gap-4",
            phase === "merged" &&
              showDemo &&
              "pointer-events-none h-0 overflow-hidden opacity-0"
          )}
        >
          {CHIPS.map((chip, index) => (
            <FileChip
              chip={chip}
              index={index}
              key={chip.label}
              phase={phase}
              showDemo={showDemo}
            />
          ))}
        </div>

        {phase === "merged" && showDemo ? (
          <div className="flex w-full max-w-lg flex-col items-center gap-6 animate-in fade-in duration-500">
            <div
              className="select-none text-[clamp(3.5rem,14vw,6rem)] leading-none tracking-tight"
              style={previewStyle}
            >
              Aa
            </div>

            <div className="flex w-full items-center gap-3 text-muted-foreground text-sm">
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
        ) : null}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 border-t px-4 py-3 sm:px-6">
        <p aria-live="polite" className="text-muted-foreground text-xs">
          {status === "error" &&
            "Could not load the preview font. Try refreshing."}
          {status === "loading" && "Loading preview font…"}
          {status === "ready" &&
            phase === "merged" &&
            showDemo &&
            "1 file · every weight"}
          {status === "ready" &&
            phase !== "merged" &&
            "3 files · one weight each"}
          {status === "ready" &&
            phase === "merged" &&
            !showDemo &&
            "Combining…"}
        </p>

        <Button
          aria-label={combineLabel}
          disabled={status !== "ready" || phase === "merging"}
          onClick={handleCombine}
          size="sm"
          type="button"
          variant={phase === "merged" ? "outline" : "default"}
        >
          {phase === "merged" ? "Replay" : "Combine"}
        </Button>
      </div>
    </div>
  );
}
