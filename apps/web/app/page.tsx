import { BuildTool } from "@/components/build-tool";
import { GlyphViewer } from "@/components/glyph-viewer";

export default function Home() {
  return (
    <main className="mx-auto max-w-5xl px-5 py-16 sm:py-24">
      <header className="mb-10 max-w-2xl">
        <p className="mb-3 font-mono text-muted-foreground text-sm">
          static-to-variable
        </p>
        <h1 className="text-balance font-semibold text-4xl leading-[1.1] tracking-tight sm:text-5xl">
          Turn a family of static weights into one variable font.
        </h1>
        <p className="mt-5 text-pretty text-lg text-muted-foreground">
          Drop the static weights of one family. Get back one variable font,
          rebuilt and verified so every glyph interpolates.
        </p>
      </header>

      <BuildTool />

      <section className="mt-16 border-t pt-12">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="font-semibold text-xl">Or try an example</h2>
          <p className="text-muted-foreground text-sm">
            real fonts the pipeline built, live
          </p>
        </div>
        <GlyphViewer />
      </section>

      <section className="mt-16 border-t pt-12">
        <h2 className="font-semibold text-xl">How it works</h2>
        <p className="mt-3 max-w-2xl text-pretty text-muted-foreground">
          Static fonts in a family are usually drawn independently, so the same
          glyph has a different number of points and contours in each weight —
          which is exactly why they won&apos;t interpolate. This isn&apos;t a
          magic &ldquo;interpolate anything&rdquo; button: it reconciles what it
          can deterministically, freezes what it can&apos;t, and tells you
          which.
        </p>
        <div className="mt-8 grid gap-8 sm:grid-cols-3">
          <div>
            <p className="font-medium">Rebuilt onto one structure</p>
            <p className="mt-1.5 text-muted-foreground text-sm">
              Each weight is redrawn onto a shared point structure — matched
              contour order, start points, and node counts — so the outlines
              actually interpolate.
            </p>
          </div>
          <div>
            <p className="font-medium">Every glyph verified</p>
            <p className="mt-1.5 text-muted-foreground text-sm">
              Hard quality gates check that each named weight matches its donor
              and that in-between weights don&apos;t collapse, self-intersect,
              or drift.
            </p>
          </div>
          <div>
            <p className="font-medium">Frozen, never faked</p>
            <p className="mt-1.5 text-muted-foreground text-sm">
              A glyph that can&apos;t be reconciled cleanly is pinned to a
              single master — constant and correct — and reported, so nothing
              deformed ever ships silently.
            </p>
          </div>
        </div>
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
