import { ArrowUpRightIcon, GithubIcon } from "blode-icons-react";
import Link from "next/link";

import { GlyphViewer } from "@/components/glyph-viewer";
import { Button } from "@/components/ui/button";
import { asset } from "@/lib/config";
import { FONTS } from "@/lib/fonts";

export default function Home() {
  return (
    <main className="mx-auto max-w-5xl px-5 py-16 sm:py-24">
      <header className="mb-10">
        <div className="-mt-2 mb-1 flex items-center justify-between gap-4">
          <p className="font-mono text-muted-foreground text-sm">
            static-to-variable
          </p>
          <Button
            aria-label="View on GitHub"
            asChild
            className="-mr-2 text-muted-foreground"
            size="icon-sm"
            variant="ghost"
          >
            <a href="https://github.com/mblode/static-to-variable">
              <GithubIcon />
              <span
                aria-hidden="true"
                className="-translate-1/2 pointer-fine:hidden absolute top-1/2 left-1/2 size-[max(100%,3rem)]"
              />
            </a>
          </Button>
        </div>
        <h1 className="max-w-[24ch] text-balance font-semibold text-4xl tracking-tight sm:text-5xl">
          Turn static fonts into one variable font.
        </h1>
        <p className="mt-5 max-w-[48ch] text-pretty text-lg text-muted-foreground">
          Point it at a folder of thin, regular, and bold. Get one file with
          every weight in between.
        </p>
      </header>

      <section>
        <pre className="overflow-x-auto rounded-xl bg-card px-5 py-4 font-mono text-muted-foreground text-sm leading-6 ring-1 ring-foreground/10">
          <code>{`npm install -g static-to-variable
cd ~/Downloads/Inter/static
static-to-variable init
static-to-variable build`}</code>
        </pre>
        <p className="mt-4 max-w-[56ch] text-pretty text-muted-foreground">
          {/* Explicit string literals: JSX trims whitespace around elements
              inconsistently, which ate the space after the first <code>. */}
          <code className="font-mono text-sm">init</code>
          {
            " finds the .ttf and .otf files in the folder, reads each one's weight, and writes a config you can edit. "
          }
          <code className="font-mono text-sm">build</code>
          {" produces the variable TTF and WOFF2."}
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Button asChild variant="outline">
            <a href="https://static-to-variable.blode.md">
              Read the docs
              <ArrowUpRightIcon />
            </a>
          </Button>
          <Button asChild variant="ghost">
            <a href="https://github.com/mblode/static-to-variable">
              View on GitHub
              <ArrowUpRightIcon />
            </a>
          </Button>
        </div>
      </section>

      <section className="mt-16 border-t pt-12">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <h2 className="font-semibold text-xl">
            Variable fonts that didn&apos;t exist
          </h2>
          {/* The viewer below only ever links to the family currently selected
              in its client-side switcher, so this is the crawl path — and the
              JS-off path — to all of them. */}
          <Link
            className="text-muted-foreground text-sm hover:text-foreground"
            href="/showcase"
          >
            See all {FONTS.length} families
          </Link>
        </div>
        <GlyphViewer />
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

      <footer className="mt-16 flex flex-col items-center gap-3 border-t pt-8 text-muted-foreground text-sm">
        <div className="flex items-center gap-5">
          <a
            className="hover:text-foreground"
            href="https://static-to-variable.blode.md"
          >
            Docs
          </a>
          <a
            className="hover:text-foreground"
            href="https://github.com/mblode/static-to-variable"
          >
            GitHub
          </a>
          <a
            className="hover:text-foreground"
            href="https://www.npmjs.com/package/static-to-variable"
          >
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
            {/* oxlint-disable-next-line nextjs/no-img-element -- tiny static 20px avatar, next/image adds no value */}
            <img
              alt="Avatar of Matthew Blode"
              className="rounded-full"
              height={20}
              src={asset("/avatar-sm.png")}
              width={20}
            />
            Matthew Blode
          </a>
          {/* The edge back to the hub: same origin behind a rewrite, so same tab
              and no rel. See
              blode-co/apps/web/.claude/knowledge/zone-conventions.md. */}
          <span aria-hidden="true">·</span>
          <a className="hover:text-foreground" href="https://blode.co/projects">
            All projects
          </a>
        </div>
      </footer>
    </main>
  );
}
