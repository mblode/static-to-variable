"use client";

import { useEffect, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";

interface FontPreviewProps {
  src: string;
  axis: { min: number; def: number; max: number };
  instances: { name: string; wght: number }[];
}

const SAMPLE = "The quick brown fox jumps over the lazy dog";
const GLYPHS = [..."AaBbEeGgQqRr0123456789&?"];

export function FontPreview({ src, axis, instances }: FontPreviewProps) {
  const uid = useId();
  const family = `stvpreview-${uid.replaceAll(/[^a-zA-Z0-9]/g, "")}`;
  const [weight, setWeight] = useState(axis.def);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading"
  );

  useEffect(() => {
    setWeight(axis.def);
  }, [axis.def]);

  useEffect(() => {
    let cancelled = false;
    const face = new FontFace(family, `url(${src})`);
    setStatus("loading");
    face
      .load()
      .then((loaded) => {
        if (!cancelled) {
          document.fonts.add(loaded);
          setStatus("ready");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
      document.fonts.delete(face);
    };
  }, [family, src]);

  const previewStyle = {
    fontFamily: family,
    fontVariationSettings: `'wght' ${weight}`,
  } as const;

  return (
    <div className="overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b px-4 py-3 sm:px-6">
        <div className="flex flex-1 items-center gap-3 text-muted-foreground text-sm">
          Weight
          <Slider
            className="min-w-[180px] max-w-[420px]"
            max={axis.max}
            min={axis.min}
            onValueChange={(next) => setWeight(next[0])}
            step={1}
            value={[weight]}
          />
          <span className="w-11 text-right font-mono text-foreground tabular-nums">
            {Math.round(weight)}
          </span>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {instances.map((ins) => (
            <Button
              key={ins.name}
              onClick={() => setWeight(ins.wght)}
              size="xs"
              variant="outline"
            >
              {ins.name} {ins.wght}
            </Button>
          ))}
        </div>
      </div>

      <div
        className="truncate border-b px-4 py-4 text-[40px] leading-tight sm:px-6"
        style={previewStyle}
      >
        {SAMPLE}
      </div>

      <div
        className="grid gap-px bg-border p-px [grid-template-columns:repeat(auto-fill,minmax(64px,1fr))]"
        style={previewStyle}
      >
        {GLYPHS.map((glyph) => (
          <div
            className="flex aspect-square items-center justify-center bg-background p-2 text-[24px] leading-none"
            key={glyph}
          >
            {glyph}
          </div>
        ))}
      </div>

      <div className="px-4 py-3 text-muted-foreground text-xs sm:px-6">
        {status === "error" ? (
          "We couldn't load the preview. Try refreshing."
        ) : (
          <>
            {status === "ready" ? "" : "loading… "}
            Weight {axis.min}–{axis.max} · default {axis.def}
          </>
        )}
      </div>
    </div>
  );
}
