import { ArrowUpRightIcon, GithubIcon } from "blode-icons-react";
import Link from "next/link";

import { CopyInstall } from "@/components/copy-install";
import { FileStackCollapse } from "@/components/file-stack-collapse";
import { GlyphViewer } from "@/components/glyph-viewer";
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
    <main className="mx-auto max-w-5xl px-5 py-16 sm:py-24">
      {/* Static object literal, no user input. */}
      <script
        dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }}
        type="application/ld+json"
      />

      <div className="mb-10 flex items-center justify-between gap-4">
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

      <header className="mb-8">
        <h1 className="max-w-[24ch] text-balance font-semibold text-4xl tracking-tight sm:text-5xl">
          Turn static fonts into one variable font.
        </h1>
        <p className="mt-5 max-w-[48ch] text-pretty text-lg text-muted-foreground">
          Point it at a folder of thin, regular, and bold. Get one file with
          every weight in between.
        </p>
        <p className="mt-3 max-w-[48ch] text-pretty text-muted-foreground text-sm">
          A variable font is one file instead of a stack of separate weights.
        </p>
      </header>

      <section aria-label="How static weights become one variable font">
        <FileStackCollapse />
      </section>

      <section className="mt-10">
        <CopyInstall code={INSTALL} />
        <p className="mt-4 max-w-[56ch] text-pretty text-muted-foreground">
          <code className="font-mono text-sm">init</code>
          {
            " finds the .ttf and .otf files in the folder, reads each one's weight, and writes a config you can edit. "
          }
          <code className="font-mono text-sm">build</code>
          {" produces the variable font."}
        </p>
        <div className="mt-6">
          <Button asChild>
            <a href={docsUrl}>
              Read the docs
              <ArrowUpRightIcon />
            </a>
          </Button>
        </div>
      </section>

      <section className="mt-16 border-t pt-12">
        <h2 className="font-semibold text-xl">How it works</h2>
        <p className="mt-3 max-w-[56ch] text-pretty text-muted-foreground">
          Normally you can&apos;t just merge the files because they don&apos;t
          line up. This handles that, and skips anything it can&apos;t do
          cleanly instead of breaking it.
        </p>
        <dl className="mt-8 grid gap-8 sm:grid-cols-3">
          <div>
            <dt className="font-medium">Lines the files up</dt>
            <dd className="mt-1.5 text-base text-muted-foreground sm:text-sm">
              Every weight is redrawn the same way, so they blend smoothly.
            </dd>
          </div>
          <div>
            <dt className="font-medium">Checks every letter</dt>
            <dd className="mt-1.5 text-base text-muted-foreground sm:text-sm">
              Each weight has to match the original, and the in-betweens
              can&apos;t go wonky.
            </dd>
          </div>
          <div>
            <dt className="font-medium">Skips what it can&apos;t</dt>
            <dd className="mt-1.5 text-base text-muted-foreground sm:text-sm">
              Anything it can&apos;t merge cleanly stays fixed at one weight,
              and you get a list.
            </dd>
          </div>
        </dl>
      </section>

      <section className="mt-16 border-t pt-12">
        <h2 className="font-semibold text-xl">What you need</h2>
        <p className="mt-3 max-w-[56ch] text-pretty text-muted-foreground">
          It runs on your machine, so nothing is uploaded anywhere and a big
          family can take as long as it needs.
        </p>
        <dl className="mt-8 grid gap-8 sm:grid-cols-3">
          <div>
            <dt className="font-medium">Node 24.11+</dt>
            <dd className="mt-1.5 text-base text-muted-foreground sm:text-sm">
              Runs the CLI itself.{" "}
              <a
                className="underline underline-offset-4 hover:text-foreground"
                href="https://nodejs.org/en"
              >
                nodejs.org
              </a>
            </dd>
          </div>
          <div>
            <dt className="font-medium">Python 3.11+ and uv</dt>
            <dd className="mt-1.5 text-base text-muted-foreground sm:text-sm">
              The font engine.{" "}
              <a
                className="underline underline-offset-4 hover:text-foreground"
                href="https://docs.astral.sh/uv/"
              >
                docs.astral.sh/uv
              </a>
            </dd>
          </div>
          <div>
            <dt className="font-medium">A few minutes</dt>
            <dd className="mt-1.5 text-base text-muted-foreground sm:text-sm">
              Three weights of a small family take under a minute; nine weights
              of a 3,000-glyph family take several.
            </dd>
          </div>
        </dl>
      </section>

      <section className="mt-16 border-t pt-12">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <h2 className="font-semibold text-xl">
            Try a font from the pipeline
          </h2>
          <Link
            className="text-muted-foreground text-sm hover:text-foreground"
            href="/showcase"
          >
            See all {FONTS.length} fonts
          </Link>
        </div>
        <p className="mb-6 max-w-[56ch] text-pretty text-muted-foreground">
          These started as separate weight files. Drag the slider — that&apos;s
          one file.
        </p>
        <GlyphViewer />
      </section>

      <footer className="mt-16 flex flex-col items-center gap-3 border-t pt-8 text-muted-foreground text-sm">
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
