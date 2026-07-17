"use client";

import { useEffect, useRef, useState } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { FONTS } from "@/lib/fonts";

const range = (a: number, b: number): number[] =>
  Array.from({ length: b - a + 1 }, (_, i) => a + i);

// Basic Latin (printable) + Latin-1 Supplement, minus the soft hyphen. Covers
// the glyphs these families ship without parsing the font at runtime.
const CODEPOINTS = [...range(0x21, 0x7e), ...range(0xa1, 0xff)].filter(
  (cp) => cp !== 0xad
);

async function activateFont(
  file: string,
  stillCurrent: () => boolean
): Promise<void> {
  const buf = await fetch(file).then((r) => r.arrayBuffer());
  const face = new FontFace("stvpreview", buf);
  await face.load();
  if (!stillCurrent()) {
    return;
  }
  // Snapshot then delete: dropping the previous preview face while iterating the
  // live FontFaceSet would mutate it mid-iteration.
  const stale: FontFace[] = [];
  for (const f of document.fonts) {
    if (f.family === "stvpreview") {
      stale.push(f);
    }
  }
  for (const f of stale) {
    document.fonts.delete(f);
  }
  document.fonts.add(face);
}

export function GlyphViewer() {
  const [index, setIndex] = useState(0);
  const font = FONTS[index];
  const [weight, setWeight] = useState(font.axis.def);
  const [ready, setReady] = useState(false);
  const token = useRef(0);

  useEffect(() => {
    token.current += 1;
    const id = token.current;
    setReady(false);
    setWeight(font.axis.def);
    activateFont(font.file, () => token.current === id)
      .then(() => {
        if (token.current === id) {
          setReady(true);
        }
      })
      .catch(() => {
        /* leave prior font showing */
      });
  }, [font]);

  const previewStyle = {
    fontFamily: "stvpreview",
    fontVariationSettings: `'wght' ${weight}`,
  } as const;

  return (
    <div className="overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          Font
          <Select
            items={FONTS.map((f, i) => ({
              label: `${f.name} (${f.category})`,
              value: String(i),
            }))}
            onValueChange={(value) => setIndex(Number(value))}
            value={String(index)}
          >
            <SelectTrigger className="w-56" size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FONTS.map((f, i) => (
                <SelectItem key={f.id} value={String(i)}>
                  {f.name} ({f.category})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-1 items-center gap-3 text-muted-foreground text-sm">
          Weight
          <Slider
            className="min-w-[180px] max-w-[420px]"
            max={font.axis.max}
            min={font.axis.min}
            onValueChange={(next) => setWeight(next[0])}
            step={1}
            value={[weight]}
          />
          <span className="w-11 text-right font-mono text-foreground tabular-nums">
            {Math.round(weight)}
          </span>
        </div>
      </div>

      <div
        className="grid gap-px bg-border p-px [grid-template-columns:repeat(auto-fill,minmax(72px,1fr))]"
        style={previewStyle}
      >
        {CODEPOINTS.map((cp) => (
          <div
            className="group relative flex aspect-square items-center justify-center overflow-hidden bg-background hover:bg-muted/60"
            key={cp}
            title={`U+${cp.toString(16).toUpperCase().padStart(4, "0")}`}
          >
            <span className="text-[32px] leading-none">
              {String.fromCodePoint(cp)}
            </span>
            <span className="absolute inset-x-0 bottom-1 text-center font-mono text-[10px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
              {cp.toString(16).toUpperCase().padStart(4, "0")}
            </span>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-muted-foreground text-xs sm:px-6">
        <span>
          {ready ? "" : "loading… "}
          Weight {font.axis.min}–{font.axis.max} · {CODEPOINTS.length} glyphs
        </span>
      </div>
    </div>
  );
}
