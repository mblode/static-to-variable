import { ArrowUpRightIcon, GithubIcon } from "blode-icons-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { CopyInstall } from "@/components/copy-install";
import { FileStackCollapse } from "@/components/file-stack-collapse";
import { GlyphViewer } from "@/components/glyph-viewer";
import { Section, SectionHeading } from "@/components/section";
import { Button } from "@/components/ui/button";
import { ZoneBreadcrumb } from "@/components/zone-breadcrumb";
import {
  asset,
  docsUrl,
  githubUrl,
  npmUrl,
  productName,
  siteUrl,
} from "@/lib/config";
import { FONTS } from "@/lib/fonts";

const INSTALL = `npm install -g static-to-variable
cd ~/Downloads/Inter/static
static-to-variable init
static-to-variable build`;

const STEPS = [
  {
    title: "Lines the files up",
    body: "Every weight is redrawn the same way, so they blend smoothly.",
  },
  {
    title: "Checks every letter",
    body: "Each weight has to match the original, and the in-betweens can't go wonky.",
  },
  {
    title: "Skips what it can't",
    body: "Anything it can't merge cleanly stays fixed at one weight, and you get a list.",
  },
] as const;

const NEEDS: { title: string; body: ReactNode }[] = [
  {
    title: "Install Node 24.11+",
    body: (
      <>
        Runs the CLI.{" "}
        <a
          className="text-foreground underline decoration-foreground/30 underline-offset-4 transition-colors hover:decoration-foreground"
          href="https://nodejs.org/en"
        >
          nodejs.org
        </a>
      </>
    ),
  },
  {
    title: "Install Python 3.11+ and uv",
    body: (
      <>
        Powers the font engine.{" "}
        <a
          className="text-foreground underline decoration-foreground/30 underline-offset-4 transition-colors hover:decoration-foreground"
          href="https://docs.astral.sh/uv/"
        >
          docs.astral.sh/uv
        </a>
      </>
    ),
  },
  {
    title: "Set aside a few minutes",
    body: "A small family with three weights finishes under a minute. A big family with thousands of glyphs takes longer.",
  },
];

/**
 * One script holding one `@graph`. Separate blocks are disconnected nodes, and
 * disconnected nodes cannot be merged into one entity. See
 * blode-co/apps/web/.claude/knowledge/zone-conventions.md Rule 3.
 *
 * `SoftwareSourceCode` because that is what this is: an open-source pipeline
 * with a CLI, a repo and a published npm package, matching allmd and
 * blode-icons. It is the type the page can actually back up.
 *
 * `#person`, `#website` and `#organization` are referenced by `@id` and never
 * redefined; a zone-scoped copy would publish a second Matthew Blode on this
 * domain.
 */
const JSON_LD = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@id": `${siteUrl}/#webpage`,
      "@type": "WebPage",
      about: { "@id": `${siteUrl}/#software` },
      author: { "@id": "https://blode.co/#person" },
      breadcrumb: { "@id": `${siteUrl}/#breadcrumb` },
      description:
        "Turn static font files into one variable font with every weight in between.",
      inLanguage: "en",
      isPartOf: { "@id": "https://blode.co/#website" },
      name: "Static to Variable: static fonts into one variable font",
      // `publisher` is the Organization and `author` is the Person: a Person
      // publisher shows up as a Search Console enhancement warning.
      publisher: { "@id": "https://blode.co/#organization" },
      url: siteUrl,
    },
    {
      "@id": `${siteUrl}/#software`,
      "@type": "SoftwareSourceCode",
      author: { "@id": "https://blode.co/#person" },
      codeRepository: githubUrl,
      description:
        "A command-line pipeline that redraws a folder of static weights onto compatible outlines and interpolates them into one variable TTF and WOFF2, checking every glyph and leaving anything it cannot merge cleanly at a fixed weight.",
      name: productName,
      programmingLanguage: ["TypeScript", "Python"],
      publisher: { "@id": "https://blode.co/#organization" },
      runtimePlatform: ["Node.js", "Python"],
      url: siteUrl,
    },
    {
      "@id": `${siteUrl}/#breadcrumb`,
      "@type": "BreadcrumbList",
      // Word for word what <ZoneBreadcrumb> renders: Google reads a mismatch
      // between the two as a markup error.
      itemListElement: [
        {
          "@type": "ListItem",
          item: "https://blode.co",
          name: "Matthew Blode",
          position: 1,
        },
        {
          "@type": "ListItem",
          item: "https://blode.co/projects",
          name: "Projects",
          position: 2,
        },
        {
          "@type": "ListItem",
          item: siteUrl,
          name: productName,
          position: 3,
        },
      ],
    },
  ],
};

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-5xl px-4 pt-10 pb-16 sm:px-6 sm:pt-14 sm:pb-24">
      {/* Static object literal, no user input. */}
      <script
        dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }}
        type="application/ld+json"
      />

      <div className="mb-10 flex items-center justify-between gap-4 sm:mb-12">
        <ZoneBreadcrumb product={productName} />
        <Button
          aria-label="View on GitHub"
          asChild
          className="-mr-2 text-muted-foreground"
          size="icon-sm"
          variant="ghost"
        >
          <a href={githubUrl}>
            <GithubIcon />
            <span
              aria-hidden="true"
              className="-translate-1/2 pointer-fine:hidden absolute top-1/2 left-1/2 size-[max(100%,3rem)]"
            />
          </a>
        </Button>
      </div>

      {/* Hero: promise, lede, proof */}
      <header className="pb-12 sm:pb-16">
        <h1 className="max-w-[19ch] text-balance font-semibold text-5xl leading-[1.05] tracking-tight sm:text-6xl sm:tracking-[-0.03em]">
          Turn static fonts into one variable font.
        </h1>
        <p className="mt-6 max-w-[50ch] text-pretty text-lg text-muted-foreground leading-relaxed sm:text-xl">
          Point it at a folder of thin, regular, and bold. Get one file with
          every weight in between. Nothing leaves your machine.
        </p>
      </header>

      <section
        aria-label="How static weights become one variable font"
        className="pb-16 sm:pb-24"
      >
        <FileStackCollapse />
      </section>

      <Section id="how">
        <SectionHeading
          eyebrow="How it works"
          lede="You can't just glue the files together. The outlines usually don't line up. This redraws them so they blend, and skips anything it can't do cleanly."
        >
          Merge without breaking letters
        </SectionHeading>
        <dl className="mt-12 grid gap-10 sm:grid-cols-3 sm:gap-10">
          {STEPS.map((step, index) => (
            <div key={step.title}>
              <dt>
                <span
                  aria-hidden="true"
                  className="font-mono text-muted-foreground text-xs tabular-nums"
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="mt-3 block font-medium text-lg tracking-tight">
                  {step.title}
                </span>
              </dt>
              <dd className="mt-2 text-muted-foreground leading-relaxed">
                {step.body}
              </dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section id="showcase">
        <SectionHeading
          action={
            <Link
              className="shrink-0 text-muted-foreground text-sm transition-colors hover:text-foreground"
              href="/showcase"
            >
              See all {FONTS.length} fonts
              <span aria-hidden="true"> →</span>
            </Link>
          }
          eyebrow="Showcase"
          lede="These started as separate weight files. Drag the slider. That's one file."
        >
          Try a finished font
        </SectionHeading>
        <div className="mt-10">
          <GlyphViewer />
        </div>
      </Section>

      <Section id="needs">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)] lg:gap-16">
          <SectionHeading
            eyebrow="Setup"
            lede="No account. No upload. You only need tools installed on your machine."
          >
            Two minutes, once.
          </SectionHeading>

          <ol className="space-y-7">
            {NEEDS.map((item, index) => (
              <li className="flex gap-4" key={item.title}>
                <span
                  aria-hidden="true"
                  className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 font-semibold text-primary text-sm tabular-nums"
                >
                  {index + 1}
                </span>
                <div className="min-w-0 pt-1">
                  <h3 className="font-medium tracking-tight">{item.title}</h3>
                  <p className="mt-1.5 text-muted-foreground leading-relaxed">
                    {item.body}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </Section>

      <Section id="install">
        <SectionHeading
          eyebrow="Install"
          lede="Install once. Point it at a folder of weights. init writes a config you can edit. build makes the variable font."
        >
          Run it on your machine
        </SectionHeading>
        <div className="mt-10">
          <CopyInstall code={INSTALL} />
        </div>
        <div className="mt-8 flex flex-wrap gap-3">
          <Button asChild size="lg">
            <a href={docsUrl}>
              Read the docs
              <ArrowUpRightIcon />
            </a>
          </Button>
          <Button asChild size="lg" variant="secondary">
            <a href={githubUrl}>
              View on GitHub
              <ArrowUpRightIcon />
            </a>
          </Button>
        </div>
      </Section>

      <footer className="flex flex-col items-center gap-4 border-border/60 border-t pt-10 text-muted-foreground text-sm">
        <div className="flex items-center gap-5">
          <a className="hover:text-foreground" href={docsUrl}>
            Docs
          </a>
          <a className="hover:text-foreground" href={githubUrl}>
            GitHub
          </a>
          <a className="hover:text-foreground" href={npmUrl}>
            NPM
          </a>
        </div>
        <div className="flex items-center gap-1">
          Crafted by
          <a
            className="flex items-center gap-2 rounded-full py-1.5 pr-2.5 pl-1.5 hover:text-foreground"
            href="https://blode.co"
            rel="author"
          >
            {/* Decorative: the link's own text already reads "Matthew Blode",
                so any alt makes the accessible name say it twice. */}
            {/* oxlint-disable-next-line nextjs/no-img-element -- tiny static 20px avatar, next/image adds no value */}
            <img
              alt=""
              className="rounded-full"
              height={20}
              src={asset("/avatar-sm.png")}
              width={20}
            />
            Matthew Blode
          </a>
          <span aria-hidden="true">·</span>
          <a className="hover:text-foreground" href="https://blode.co/projects">
            All projects
          </a>
        </div>
      </footer>
    </main>
  );
}
