import { notFound } from "next/navigation";

import { LoupeHeader } from "@/components/loupe-header";
import { LoupeSidebar } from "@/components/loupe-sidebar";
import { WeightStrip } from "@/components/weight-strip";
import type { Family } from "@/lib/data";
import { attachGlyphScores, cellScoreLookup } from "@/lib/data";
import {
  loadCellScores,
  loadGlyphScores,
  loadManifest,
  loadSolverResults,
  loadSuggestions,
} from "@/lib/data.server";
import { keyOf, readPending } from "@/lib/pending.server";

interface Params {
  family: string;
  name: string;
}

function asFamily(x: string): Family | null {
  return x === "roman" || x === "italic" ? x : null;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}) {
  const { family, name } = await params;
  return {
    title: `${family}/${decodeURIComponent(name)} — Static to Variable`,
  };
}

export default async function LoupePage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { family: rawFamily, name: rawName } = await params;
  const family = asFamily(rawFamily);
  if (!family) {
    notFound();
  }

  const name = decodeURIComponent(rawName);
  const [manifest, glyphScores, cellScores, suggestions, solver, pending] =
    await Promise.all([
      loadManifest(),
      loadGlyphScores(),
      loadCellScores(),
      loadSuggestions(),
      loadSolverResults(),
      readPending(),
    ]);
  const scored = attachGlyphScores(manifest, glyphScores);
  const glyph = scored.find((g) => g.family === family && g.name === name);
  if (!glyph) {
    notFound();
  }

  const cellLookup = cellScoreLookup(cellScores, family, name);
  const suggestion = suggestions?.[`${family}/${name}`];
  const verdict = solver?.[`${family}/${name}`];
  const pendingEdit =
    pending.find((p) => keyOf(p) === `${family}/${name}`) ?? null;

  return (
    <main>
      <LoupeHeader glyph={glyph} stagedStrategy={pendingEdit?.strategy} />
      <div className="mx-auto grid max-w-[1600px] gap-6 px-6 py-8 lg:grid-cols-[1fr_340px]">
        <WeightStrip
          family={family}
          glyph={name}
          cellScores={cellLookup}
          verdict={verdict}
        />
        <LoupeSidebar
          glyph={glyph}
          suggestion={suggestion}
          pending={pendingEdit}
          solver={verdict}
        />
      </div>
    </main>
  );
}
