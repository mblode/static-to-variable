import { Grid } from "@/components/grid";
import { attachGlyphScores } from "@/lib/data";
import {
  loadGlyphScores,
  loadManifest,
  loadSolverResults,
} from "@/lib/data.server";

export default async function HomePage() {
  const [glyphs, scores, solver] = await Promise.all([
    loadManifest(),
    loadGlyphScores(),
    loadSolverResults(),
  ]);
  const scored = attachGlyphScores(glyphs, scores, solver);

  const redCount = scores
    ? Object.values(scores).filter(
        (s) => s.worstComposite !== null && s.worstComposite < 0.3
      ).length
    : 0;
  const amberCount = scores
    ? Object.values(scores).filter(
        (s) =>
          s.worstComposite !== null &&
          s.worstComposite < 0.7 &&
          s.worstComposite >= 0.3
      ).length
    : 0;
  const solverImprovements = solver
    ? Object.values(solver).filter((v) => v.gain !== null && v.gain > 0.1)
        .length
    : 0;

  return (
    <main>
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-2 px-6 py-4 font-mono text-xs text-muted-foreground/70">
        <span>{glyphs.length} catalogued</span>
        {scores && (
          <span className="rounded bg-card px-2 py-0.5">
            {redCount} red · {amberCount} amber
          </span>
        )}
        {solverImprovements > 0 && (
          <span
            className="rounded bg-[--color-band-green]/15 px-2 py-0.5 text-[--color-band-green]"
            title="Glyphs where the solver projects a worst-case gain > 0.1"
          >
            solver can improve {solverImprovements}
          </span>
        )}
      </div>
      <Grid glyphs={scored} />
    </main>
  );
}
