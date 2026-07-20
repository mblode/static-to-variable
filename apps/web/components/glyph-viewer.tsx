"use client";

import { ArrowDownIcon } from "blode-icons-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import type { DemoFont } from "@/lib/fonts";
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

/**
 * An editable type specimen + weight-axis scrubber + download row for a single
 * family, with an optional every-glyph grid below the specimen (showcase
 * pages). `selector` renders in the top bar ahead of the weight control,
 * letting the multi-family <GlyphViewer /> slot its family <Select> in without
 * this having to know about switching. Reset-on-change is keyed off the `font`
 * prop, so it works whether `font` is fixed (a showcase page) or swapped (the
 * selector).
 */
export function SingleGlyphViewer({
  font,
  selector,
  pageHref,
  showGlyphs = false,
}: {
  font: DemoFont;
  selector?: ReactNode;
  pageHref?: string;
  showGlyphs?: boolean;
}) {
  const [weight, setWeight] = useState(font.axis.def);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading"
  );
  const token = useRef(0);

  useEffect(() => {
    token.current += 1;
    const id = token.current;
    setStatus("loading");
    setWeight(font.axis.def);
    activateFont(font.file, () => token.current === id)
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
  }, [font]);

  const previewStyle = {
    fontFamily: "stvpreview",
    fontVariationSettings: `'wght' ${weight}`,
  } as const;

  return (
    <div className="overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b px-4 py-3 sm:px-6">
        {selector}

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
        aria-label="Type to preview the font"
        className="min-h-[200px] cursor-text overflow-hidden text-balance px-5 py-12 text-[clamp(2.25rem,6.5vw,4.5rem)] leading-[1.08] tracking-tight outline-none sm:px-8 sm:py-16"
        contentEditable
        role="textbox"
        spellCheck={false}
        style={previewStyle}
        suppressContentEditableWarning
      >
        One file, every weight in between.
      </div>

      {showGlyphs ? (
        <div
          className="grid gap-px border-t bg-border p-px [grid-template-columns:repeat(auto-fill,minmax(84px,1fr))]"
          style={previewStyle}
        >
          {CODEPOINTS.map((cp) => (
            <div
              className="group relative flex aspect-square items-center justify-center overflow-hidden bg-background p-3 hover:bg-muted/60"
              key={cp}
              title={`U+${cp.toString(16).toUpperCase().padStart(4, "0")}`}
            >
              <span className="text-[26px] leading-none">
                {String.fromCodePoint(cp)}
              </span>
              <span className="absolute inset-x-0 bottom-1 text-center font-mono text-[10px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                {cp.toString(16).toUpperCase().padStart(4, "0")}
              </span>
            </div>
          ))}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t px-4 py-3 text-muted-foreground text-xs sm:px-6">
        <span className="flex items-center gap-1.5">
          {status === "error" && "We couldn't load this font. Try refreshing."}
          {status === "loading" && "loading…"}
          {status === "ready" &&
            font.instances.map((inst) => (
              <Button
                key={inst.name}
                onClick={() => setWeight(inst.wght)}
                size="xs"
                variant={
                  Math.round(weight) === inst.wght ? "secondary" : "ghost"
                }
              >
                {inst.name} {inst.wght}
              </Button>
            ))}
        </span>
        <span className="flex gap-1.5">
          {pageHref ? (
            <Button asChild size="xs" variant="ghost">
              <Link href={pageHref}>View the {font.name} page</Link>
            </Button>
          ) : null}
          <Button asChild size="xs" variant="outline">
            <a download={`${font.id}-variable.ttf`} href={font.ttf}>
              <ArrowDownIcon />
              Download TTF
            </a>
          </Button>
          <Button asChild size="xs" variant="outline">
            <a download={`${font.id}-variable.woff2`} href={font.file}>
              <ArrowDownIcon />
              Download WOFF2
            </a>
          </Button>
        </span>
      </div>
    </div>
  );
}

/** The homepage viewer: the single-family grid plus a family switcher. */
export function GlyphViewer() {
  const [index, setIndex] = useState(0);
  const font = FONTS[index];

  return (
    <SingleGlyphViewer
      font={font}
      pageHref={`/showcase/${font.id}`}
      selector={
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          Font
          <Select
            items={FONTS.map((f, i) => ({
              label: f.name,
              value: String(i),
            }))}
            onValueChange={(value) => setIndex(Number(value))}
            value={String(index)}
          >
            <SelectTrigger className="w-fit" size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FONTS.map((f, i) => (
                <SelectItem key={f.id} value={String(i)}>
                  {f.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      }
    />
  );
}
