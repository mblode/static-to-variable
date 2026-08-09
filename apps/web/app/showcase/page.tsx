import type { Metadata } from "next";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { ogSiteName } from "@/lib/config";
import { FONTS } from "@/lib/fonts";

/**
 * Index for `/showcase/<family>`.
 *
 * Without this every family page was orphaned. The homepage links only to the
 * font currently chosen in `GlyphViewer`'s client-side `<Select>`, so exactly
 * one of the 15 showcase URLs is ever present in the served HTML — a crawler
 * (or a reader with JS off) can't reach the other 14, even though they are all
 * in the sitemap.
 */
const description = `Every family rebuilt as a variable font: ${FONTS.length} typefaces Google Fonts ships only as static styles, each with a live weight axis and WOFF2 and TTF downloads.`;

export const metadata: Metadata = {
  title: "Variable font showcase",
  description,
  alternates: { canonical: "/showcase" },
  openGraph: {
    title: "Variable font showcase",
    description,
    type: "website",
    url: "/showcase",
    // This block replaces the root layout's openGraph rather than merging
    // into it, so the site name has to be repeated here.
    siteName: ogSiteName,
  },
  twitter: {
    card: "summary_large_image",
    title: "Variable font showcase",
    description,
  },
};

export default function ShowcaseIndexPage() {
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
          Variable font showcase
        </h1>
        <p className="mt-5 text-pretty text-lg text-muted-foreground">
          {FONTS.length} families that Google Fonts ships only as separate
          static weights, each rebuilt into a single variable font. Open one to
          drag through its weight axis and download the result.
        </p>
      </header>

      <ul className="grid gap-4 sm:grid-cols-2">
        {FONTS.map((font) => (
          <li key={font.id}>
            <Link
              className="block rounded-xl bg-card p-5 ring-1 ring-foreground/10 transition-colors hover:ring-foreground/25 focus-visible:outline-2 focus-visible:outline-offset-2"
              href={`/showcase/${font.id}`}
            >
              <h2 className="font-medium text-lg">{font.name}</h2>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Badge variant="outline">{font.category}</Badge>
                <Badge variant="outline">
                  wght {font.axis.min} to {font.axis.max}
                </Badge>
              </div>
              <p className="mt-3 text-muted-foreground text-sm">
                Rebuilt from {font.builtFrom}.
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
