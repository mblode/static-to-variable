import { ArrowUpRightIcon } from "blode-icons-react";

import { BuildTool } from "@/components/build-tool";
import { GlyphViewer } from "@/components/glyph-viewer";
import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <main className="mx-auto max-w-5xl px-5 py-16 sm:py-24">
      <header className="mb-10 max-w-2xl">
        <p className="mb-3 font-mono text-muted-foreground text-sm">
          static-to-variable
        </p>
        <h1 className="text-balance font-semibold text-4xl leading-[1.1] tracking-tight sm:text-5xl">
          Turn separate font files into one variable font.
        </h1>
        <p className="mt-5 text-pretty text-lg text-muted-foreground">
          Drop in thin, regular, and bold. Get back one file you can slide
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
        <p className="mt-3 max-w-2xl text-pretty text-muted-foreground">
          Normally you can&apos;t just merge the files because they don&apos;t
          line up. This handles that, and skips anything it can&apos;t do
          cleanly instead of breaking it.
        </p>
        <div className="mt-8 grid gap-8 sm:grid-cols-3">
          <div>
            <p className="font-medium">Lines the files up</p>
            <p className="mt-1.5 text-muted-foreground text-sm">
              Every weight is redrawn the same way, so they blend smoothly.
            </p>
          </div>
          <div>
            <p className="font-medium">Checks every letter</p>
            <p className="mt-1.5 text-muted-foreground text-sm">
              Each weight has to match the original, and the in-betweens
              can&apos;t go wonky.
            </p>
          </div>
          <div>
            <p className="font-medium">Skips what it can&apos;t</p>
            <p className="mt-1.5 text-muted-foreground text-sm">
              Anything it can&apos;t merge cleanly stays fixed at one weight,
              and you get a list.
            </p>
          </div>
        </div>
      </section>

      <section className="mt-16 border-t pt-12">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <h2 className="font-semibold text-xl">Try it on your fonts</h2>
            <p className="mt-3 text-pretty text-muted-foreground">
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
        <pre className="mt-6 overflow-x-auto rounded-xl bg-card px-5 py-4 font-mono text-muted-foreground text-sm leading-relaxed ring-1 ring-foreground/10">
          <code>{`npm install -g static-to-variable
static-to-variable init
static-to-variable build`}</code>
        </pre>
      </section>

      <footer className="mt-16 flex flex-col items-center gap-3 border-t pt-8 text-muted-foreground text-sm">
        <div className="flex items-center gap-5">
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
            npm
          </a>
        </div>
        <div className="flex items-center gap-1">
          Crafted by
          <a
            className="flex items-center gap-2 rounded-full py-1.5 pr-2.5 pl-1.5 transition-colors hover:text-foreground"
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
