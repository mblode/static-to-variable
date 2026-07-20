import { ArrowUpRightIcon } from "blode-icons-react";
import type { Metadata } from "next";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { FONTS } from "@/lib/fonts";

export const metadata: Metadata = {
  title: "Variable font showcase",
  description:
    "Popular Google Fonts families that ship as static weights only, rebuilt into single variable fonts. Scrub the weight axis on each one and download the WOFF2 or TTF.",
  alternates: { canonical: "/showcase" },
};

export default function ShowcaseIndex() {
  return (
    <main className="mx-auto max-w-5xl px-5 py-16 sm:py-24">
      <header className="mb-10 max-w-2xl">
        <p className="mb-3 font-mono text-muted-foreground text-sm">
          <Link className="hover:text-foreground" href="/">
            static-to-variable
          </Link>{" "}
          / showcase
        </p>
        <h1 className="text-balance font-semibold text-4xl leading-[1.1] tracking-tight sm:text-5xl">
          Variable fonts that didn&apos;t exist
        </h1>
        <p className="mt-5 text-pretty text-lg text-muted-foreground">
          Each of these families ships on Google Fonts as separate static
          weights, with no variable version. We rebuilt every weight onto one
          shared outline structure, so it interpolates into a single variable
          font. Pick one to scrub its weight axis and download it.
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2">
        {FONTS.map((font) => (
          <Link
            className="group flex flex-col justify-between gap-6 rounded-xl bg-card p-5 ring-1 ring-foreground/10 transition-colors hover:ring-foreground/25"
            href={`/showcase/${font.id}`}
            key={font.id}
          >
            <div>
              <div className="flex items-start justify-between gap-3">
                <h2 className="font-semibold text-xl tracking-tight">
                  {font.name}
                </h2>
                <ArrowUpRightIcon className="mt-1 size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground" />
              </div>
              <Badge className="mt-2" variant="outline">
                {font.category}
              </Badge>
              <p className="mt-3 text-pretty text-muted-foreground text-sm">
                Static-only on Google Fonts
                {font.staticStyles ? `, ${font.staticStyles} styles` : ""}.
                Rebuilt from {font.builtFrom}.
              </p>
            </div>
            <p className="font-mono text-muted-foreground text-xs">
              wght {font.axis.min} to {font.axis.max}
            </p>
          </Link>
        ))}
      </div>
    </main>
  );
}
