"use client";

import { ReplayIcon } from "blode-icons-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { FONTS } from "@/lib/fonts";
import { cn } from "@/lib/utils";

const [FONT] = FONTS;
const FONT_FAMILY = "stvfilestack";
const MERGED_FILE = `${FONT.name}-VF.woff2`;

/**
 * The three static masters the hero story merges. The axis is read off these,
 * not off `FONT.axis`: the demo may only claim the range it visibly built.
 */
const MASTERS = [
  { file: "Thin.ttf", name: "Thin", weight: 100 },
  { file: "Regular.ttf", name: "Regular", weight: 400 },
  { file: "Bold.ttf", name: "Bold", weight: 700 },
] as const;

const AXIS: { min: number; def: number; max: number } = {
  min: MASTERS[0].weight,
  def: MASTERS[1].weight,
  max: MASTERS[2].weight,
};

/* Beats. Motion inside each is quick; the holds between are what make the
   sequence readable. Total run is ~6s, which suits a rare, illustrative moment. */
const BEAT_MS = 700; // hold on three files before anything moves
const GATHER_MS = 900; // outer files travel into the middle one
const FUSE_MS = 900; // absorb pulse, filename swap, hold on the fused file
const REVEAL_MS = 850; // card dissolves, specimen grows, slider arrives
const SWEEP_MS = 2800; // the font demonstrates its own axis
const REPLAY_LEAD_MS = 950; // long enough for the rewind to land before act two

const EASE_ENTER = "cubic-bezier(0.22, 1, 0.36, 1)";
const EASE_MOVE = "cubic-bezier(0.25, 1, 0.5, 1)";

const PHASES = ["stack", "gather", "fused", "reveal", "sweep", "done"] as const;
type Phase = (typeof PHASES)[number];
type LoadStatus = "loading" | "ready" | "error";

const rank = (phase: Phase) => PHASES.indexOf(phase);

/** Cues after the opening beat: phase to enter, and how long it then holds. */
const SCRIPT: { phase: Phase; hold: number }[] = [
  { phase: "gather", hold: GATHER_MS },
  { phase: "fused", hold: FUSE_MS },
  { phase: "reveal", hold: REVEAL_MS },
  { phase: "sweep", hold: 0 },
];

/** Fraction of the top rail filled once each phase finishes. */
const PROGRESS: Record<Phase, number> = {
  stack: 0,
  gather: 0.17,
  fused: 0.33,
  reveal: 0.49,
  sweep: 1,
  done: 1,
};

const PHASE_MS: Record<Phase, number> = {
  stack: 0,
  gather: GATHER_MS,
  fused: FUSE_MS,
  reveal: REVEAL_MS,
  sweep: SWEEP_MS,
  done: 240,
};

/** Weight stops for the self-playing sweep, with a beat held at each extreme. */
const SWEEP_STOPS = [
  { at: 0, wght: AXIS.def },
  { at: 750, wght: AXIS.max },
  { at: 950, wght: AXIS.max },
  { at: 2050, wght: AXIS.min },
  { at: 2250, wght: AXIS.min },
  { at: SWEEP_MS, wght: AXIS.def },
];

/** Smoothstep between stops, so each turnaround arrives at zero velocity. */
function sweepWeight(elapsed: number): number {
  for (let i = 1; i < SWEEP_STOPS.length; i += 1) {
    const from = SWEEP_STOPS[i - 1];
    const to = SWEEP_STOPS[i];
    if (elapsed > to.at) {
      continue;
    }
    const span = to.at - from.at;
    const p = span === 0 ? 1 : (elapsed - from.at) / span;
    return Math.round(from.wght + (to.wght - from.wght) * p * p * (3 - 2 * p));
  }
  return AXIS.def;
}

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

function statusCopy(status: LoadStatus, phase: Phase): string {
  if (status === "error") {
    return "Could not load the preview font. Try refreshing.";
  }
  if (status === "loading") {
    return "Loading preview font…";
  }
  if (phase === "stack") {
    return "3 files · one weight each";
  }
  if (phase === "gather") {
    return "Combining outlines…";
  }
  if (phase === "fused") {
    return "1 file";
  }
  return "1 file · every weight in between";
}

const LABEL_CLASS =
  "absolute whitespace-nowrap font-mono text-[10px] tracking-wide sm:text-[11px]";

/**
 * The static filename and the merged one crossfade in a fixed-height slot, so
 * the card's contents never shift when the name changes.
 */
function FileLabel({
  name,
  isCenter,
  merged,
  reducedMotion,
}: {
  name: string;
  isCenter: boolean;
  merged: boolean;
  reducedMotion: boolean;
}) {
  const ease = (spec: string) => (reducedMotion ? "none" : spec);
  const lift = (px: number) => (reducedMotion ? "none" : `translateY(${px}px)`);

  return (
    <span className="relative flex h-4 w-full items-center justify-center">
      <span
        className={cn(LABEL_CLASS, "text-muted-foreground")}
        style={{
          opacity: merged ? 0 : 1,
          transform: merged ? lift(-5) : "translateY(0)",
          transition: ease(
            `opacity 240ms linear, transform 240ms ${EASE_MOVE}`
          ),
        }}
      >
        {name}
      </span>
      {isCenter && (
        <span
          className={cn(LABEL_CLASS, "text-foreground")}
          style={{
            opacity: merged ? 1 : 0,
            transform: merged ? "translateY(0)" : lift(5),
            transition: ease(
              `opacity 300ms linear 120ms, transform 300ms ${EASE_ENTER} 120ms`
            ),
          }}
        >
          {MERGED_FILE}
        </span>
      )}
    </span>
  );
}

interface MasterCardProps {
  master: (typeof MASTERS)[number];
  index: number;
  phase: Phase;
  weight: number;
  ready: boolean;
  reducedMotion: boolean;
}

/**
 * One static master. The middle card is the survivor: it is never swapped for
 * another element, so the file the outer two are absorbed into is literally the
 * one that grows into the specimen.
 */
function MasterCard({
  master,
  index,
  phase,
  weight,
  ready,
  reducedMotion,
}: MasterCardProps) {
  const isCenter = index === 1;
  const at = rank(phase);
  const absorbed = !isCenter && at >= rank("gather");
  const merged = isCenter && at >= rank("fused");
  const opened = at >= rank("reveal");

  const ease = (spec: string) => (reducedMotion ? "none" : spec);

  // Exactly one column plus the grid gap: the card lands on the middle one.
  const travel = index === 0 ? "calc(100% + 0.75rem)" : "calc(-100% - 0.75rem)";
  const delay = index === 0 ? 0 : 90;

  return (
    <div
      className={cn(
        "relative flex h-32 flex-col items-center justify-center gap-3 sm:h-40",
        !reducedMotion && phase === "fused" && isCenter && "animate-stv-fuse"
      )}
      style={{
        opacity: absorbed ? 0 : 1,
        transform: absorbed
          ? `translateX(${travel}) scale(0.88)`
          : undefined /* the fuse keyframe owns the middle card's transform */,
        transition: ease(
          `transform ${GATHER_MS}ms ${EASE_MOVE} ${absorbed ? delay : 0}ms, opacity 420ms linear ${absorbed ? delay + 400 : 0}ms`
        ),
        zIndex: isCenter ? 2 : 1,
      }}
    >
      {/* Chrome sits in its own layer so the file can dissolve while its
          contents stay put. */}
      <span
        aria-hidden
        className="absolute inset-0 rounded-xl bg-background ring-1 ring-foreground/10"
        style={{
          opacity: opened ? 0 : 1,
          transition: ease(`opacity 520ms ${EASE_ENTER}`),
        }}
      />

      <FileLabel
        isCenter={isCenter}
        merged={merged}
        name={master.file}
        reducedMotion={reducedMotion}
      />

      {/* font-size, not scale: transformed type stays raster-blurred for the
          whole tween, and this is a page about letterforms. One text node in a
          fixed-height box, so the reflow is free. */}
      <span
        aria-hidden
        className="relative select-none leading-none tracking-tight"
        style={{
          fontFamily: FONT_FAMILY,
          fontSize:
            opened && isCenter
              ? "clamp(4rem, 15vw, 6.5rem)"
              : "clamp(2rem, 8vw, 3.25rem)",
          fontVariationSettings: `'wght' ${isCenter ? weight : master.weight}`,
          // Held back until the real face is live: the fallback renders all
          // three cards identically, which is the opposite of the point.
          opacity: ready ? 1 : 0,
          transition: ease(
            `font-size ${REVEAL_MS}ms ${EASE_ENTER}, opacity 420ms linear`
          ),
        }}
      >
        Aa
      </span>
    </div>
  );
}

/**
 * Hero visualization in three readable beats: three static files, the two outer
 * ones absorbed into the middle, then that single file playing its own weight
 * axis before handing the slider over.
 */
export function FileStackCollapse({ className }: { className?: string }) {
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [phase, setPhase] = useState<Phase>("stack");
  const [weight, setWeight] = useState(AXIS.def);
  const [reducedMotion, setReducedMotion] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const token = useRef(0);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const frame = useRef<number | null>(null);
  const hasAutoplayed = useRef(false);

  const stop = useCallback(() => {
    for (const t of timers.current) {
      clearTimeout(t);
    }
    timers.current = [];
    if (frame.current !== null) {
      cancelAnimationFrame(frame.current);
      frame.current = null;
    }
  }, []);

  const sweep = useCallback(() => {
    const start = performance.now();
    const tick = (now: number) => {
      const elapsed = now - start;
      if (elapsed >= SWEEP_MS) {
        frame.current = null;
        setWeight(AXIS.def);
        setPhase("done");
        return;
      }
      setWeight(sweepWeight(elapsed));
      frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
  }, []);

  const play = useCallback(
    (lead: number) => {
      stop();
      setWeight(AXIS.def);

      if (reducedMotion) {
        setPhase("done");
        return;
      }

      setPhase("stack");
      let at = lead;
      for (const cue of SCRIPT) {
        const ms = at;
        timers.current.push(
          setTimeout(() => {
            setPhase(cue.phase);
            if (cue.phase === "sweep") {
              sweep();
            }
          }, ms)
        );
        at += cue.hold;
      }
    },
    [reducedMotion, stop, sweep]
  );

  const handleReplay = useCallback(() => {
    hasAutoplayed.current = true;
    play(REPLAY_LEAD_MS);
  }, [play]);

  // Taking hold of the slider ends the demo immediately; a control that keeps
  // moving under the pointer feels broken.
  const handleWeight = useCallback(
    (next: number[]) => {
      stop();
      setPhase("done");
      setWeight(next[0]);
    },
    [stop]
  );

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
    if (status !== "ready" || hasAutoplayed.current) {
      return;
    }

    if (reducedMotion) {
      hasAutoplayed.current = true;
      setPhase("done");
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
        play(BEAT_MS);
      },
      { threshold: 0.4 }
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [play, reducedMotion, status]);

  useEffect(() => stop, [stop]);

  const opened = rank(phase) >= rank("reveal");
  const finished = status === "ready" && phase === "done";

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10",
        className
      )}
      ref={rootRef}
    >
      {/* Pace made visible: the rail advances with each beat, so the length of
          the sequence is legible rather than merely endured. Once it is spent
          it fades, rather than sitting there as a full bar forever. */}
      <div
        aria-hidden
        className="absolute inset-x-0 top-0 h-[2px]"
        style={{
          opacity: finished ? 0 : 1,
          transition: reducedMotion ? "none" : "opacity 600ms linear 200ms",
        }}
      >
        <div
          className="h-full origin-left bg-primary"
          style={{
            transform: `scaleX(${PROGRESS[phase]})`,
            transition: reducedMotion
              ? "none"
              : `transform ${PHASE_MS[phase]}ms linear`,
          }}
        />
      </div>

      <div className="flex flex-col items-center gap-6 px-5 pt-12 pb-10 sm:gap-8 sm:px-8 sm:pt-14 sm:pb-12">
        <div className="grid w-full max-w-2xl grid-cols-3 gap-3">
          {MASTERS.map((master, index) => (
            <MasterCard
              index={index}
              key={master.file}
              master={master}
              phase={phase}
              ready={status === "ready"}
              reducedMotion={reducedMotion}
              weight={weight}
            />
          ))}
        </div>

        <div
          className="w-full max-w-md"
          inert={!opened}
          style={{
            opacity: opened ? 1 : 0,
            transform: opened ? "translateY(0)" : "translateY(10px)",
            transition: reducedMotion
              ? "none"
              : `opacity 460ms ${EASE_ENTER} 260ms, transform 460ms ${EASE_MOVE} 260ms`,
          }}
        >
          <Slider
            aria-label="Font weight"
            max={AXIS.max}
            min={AXIS.min}
            onValueChange={handleWeight}
            step={1}
            value={[weight]}
          />
          <div className="-mt-1 flex justify-between font-mono text-[11px] text-muted-foreground">
            <span>{MASTERS[0].name}</span>
            <span>{MASTERS[2].name}</span>
          </div>
        </div>
      </div>

      {/* The sequence plays itself, so the only control it ever needs is a way
          to watch it again. It stays mounted, invisible, so the bar keeps its
          height while the demo runs. */}
      <div className="flex min-h-13 items-center justify-between gap-x-4 border-t px-4 sm:px-6">
        <p aria-live="polite" className="text-muted-foreground text-xs">
          {statusCopy(status, phase)}
        </p>

        <Button
          aria-hidden={!finished}
          aria-label="Watch it again"
          className="-mr-2 text-muted-foreground"
          disabled={!finished}
          onClick={handleReplay}
          size="sm"
          style={{
            opacity: finished ? 1 : 0,
            pointerEvents: finished ? "auto" : "none",
            transition: reducedMotion
              ? "none"
              : `opacity 320ms ${EASE_ENTER} 160ms`,
          }}
          type="button"
          variant="ghost"
        >
          <ReplayIcon />
          Watch again
        </Button>
      </div>
    </div>
  );
}
