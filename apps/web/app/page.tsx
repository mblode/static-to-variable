import { ArrowUpRightIcon, GithubIcon } from "blode-icons-react";

import { BuildTool } from "@/components/build-tool";
import { GlyphViewer } from "@/components/glyph-viewer";
import { Button } from "@/components/ui/button";

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
          Upload thin, regular, and bold. Get one file with every weight in
          between.
        </p>
      </header>

      <BuildTool />

      <section className="mt-16 border-t pt-12">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <h2 className="font-semibold text-xl">
            Variable fonts that didn&apos;t exist
          </h2>
          <p className="text-muted-foreground text-sm">
            Google Fonts doesn&apos;t have these
          </p>
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
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <h2 className="font-semibold text-xl">Try it on your fonts</h2>
            <p className="mt-3 max-w-[56ch] text-pretty text-muted-foreground">
              Run it in a folder with your font files. It finds them and does
              the rest.
            </p>
          </div>
          <Button asChild variant="outline">
            <a href="https://github.com/mblode/static-to-variable">
              View on GitHub
              <ArrowUpRightIcon />
            </a>
          </Button>
        </div>
        <pre className="mt-6 overflow-x-auto rounded-xl bg-card px-5 py-4 font-mono text-muted-foreground text-sm leading-6 ring-1 ring-foreground/10">
          <code>{`npm install -g static-to-variable
static-to-variable init
static-to-variable build`}</code>
        </pre>
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
            href="https://matthewblode.com"
            rel="author noreferrer"
            target="_blank"
          >
            {/* oxlint-disable-next-line nextjs/no-img-element -- tiny static 20px avatar, next/image adds no value */}
            <img
              alt="Avatar of Matthew Blode"
              className="rounded-full"
              height={20}
              src="/avatar-sm.png"
              width={20}
            />
            Matthew Blode
          </a>
        </div>
      </footer>
    </main>
  );
}
