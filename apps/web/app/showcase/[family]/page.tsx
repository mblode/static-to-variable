import { ArrowUpRightIcon } from "blode-icons-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { SingleGlyphViewer } from "@/components/glyph-viewer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FONTS } from "@/lib/fonts";

interface Params {
  family: string;
}

export function generateStaticParams(): Params[] {
  return FONTS.map((font) => ({ family: font.id }));
}

export function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  return params.then(({ family }) => {
    const font = FONTS.find((f) => f.id === family);
    if (!font) {
      return {};
    }
    const styles = font.staticStyles
      ? `${font.staticStyles} static styles`
      : "static styles";
    const description = `${font.name} rebuilt as a single variable font. Google Fonts only ships ${font.name} as ${styles} with no variable version, so we redrew every weight onto one shared structure. Scrub the wght axis from ${font.axis.min} to ${font.axis.max} and download the WOFF2 or TTF.`;
    return {
      title: `${font.name} variable font`,
      description,
      alternates: { canonical: `/showcase/${font.id}` },
      openGraph: {
        title: `${font.name} variable font`,
        description,
        type: "website",
      },
      twitter: {
        card: "summary_large_image",
        title: `${font.name} variable font`,
        description,
      },
    };
  });
}

export default async function FamilyPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { family } = await params;
  const font = FONTS.find((f) => f.id === family);
  if (!font) {
    notFound();
  }

  return (
    <main className="mx-auto max-w-5xl px-5 py-16 sm:py-24">
      <header className="mb-10 max-w-2xl">
        <p className="mb-3 font-mono text-muted-foreground text-sm">
          <Link className="hover:text-foreground" href="/">
            static-to-variable
          </Link>{" "}
          / showcase / {font.id}
        </p>
        <h1 className="text-balance font-semibold text-4xl leading-[1.1] tracking-tight sm:text-5xl">
          {font.name} variable font
        </h1>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Badge variant="outline">{font.category}</Badge>
          <Badge variant="outline">
            wght {font.axis.min} to {font.axis.max}
          </Badge>
        </div>
        <p className="mt-5 text-pretty text-lg text-muted-foreground">
          Google Fonts ships {font.name} as
          {font.staticStyles ? ` ${font.staticStyles}` : ""} static styles with
          no variable version. This one was rebuilt from {font.builtFrom}, every
          weight redrawn onto a shared outline structure so it interpolates.
          Drag the slider to move through the weight axis.
        </p>
      </header>

      <SingleGlyphViewer font={font} />

      <section className="mt-10 grid gap-6 sm:grid-cols-2">
        <div className="rounded-xl bg-card p-5 ring-1 ring-foreground/10">
          <h2 className="font-medium">Built from</h2>
          <p className="mt-2 text-muted-foreground text-sm">
            {font.builtFrom}. The weights above and below are interpolated, and
            any glyph that could not be matched cleanly is frozen at a single
            weight rather than allowed to drift.
          </p>
        </div>
        <div className="rounded-xl bg-card p-5 ring-1 ring-foreground/10">
          <h2 className="font-medium">Attribution</h2>
          <p className="mt-2 text-muted-foreground text-sm">{font.credit}.</p>
          <p className="mt-3 text-muted-foreground text-xs">
            Unofficial community build. Not affiliated with the foundry or
            Google Fonts.
          </p>
        </div>
      </section>

      <section className="mt-10 flex flex-wrap items-end justify-between gap-6 border-t pt-10">
        <div>
          <h2 className="font-semibold text-xl">Do this to your own fonts</h2>
          <p className="mt-2 text-pretty text-muted-foreground">
            Drop a family of static weights into the build tool and get one
            variable font back.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href="/">
            Open the build tool
            <ArrowUpRightIcon />
          </Link>
        </Button>
      </section>
    </main>
  );
}
