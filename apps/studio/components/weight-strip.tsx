import type {
  CellScores,
  SolverVerdict,
} from "@static-to-variable/glyph-forge-engine";

import { CIRCULAR_WEIGHTS } from "@/lib/data";
import type { Family } from "@/lib/data";

import { ProjectionRow } from "./projection-row";
import { WeightCell } from "./weight-cell";

export function WeightStrip({
  family,
  glyph,
  cellScores,
  verdict,
}: {
  family: Family;
  glyph: string;
  cellScores: (wght: number) => CellScores | undefined;
  verdict?: SolverVerdict;
}) {
  return (
    <div className="flex flex-col gap-6">
      <Row label="Circular donor" accent="donor">
        {CIRCULAR_WEIGHTS.map((w) => (
          <WeightCell
            key={`donor-${w.wght}`}
            family={family}
            glyph={glyph}
            wght={w.wght}
            weightName={w.name}
            style="donor"
          />
        ))}
      </Row>
      <Row label="Glide instance" accent="glide">
        {CIRCULAR_WEIGHTS.map((w) => (
          <WeightCell
            key={`glide-${w.wght}`}
            family={family}
            glyph={glyph}
            wght={w.wght}
            weightName={w.name}
            style="glide"
          />
        ))}
      </Row>
      <Row label="Overlay + score" accent="overlay">
        {CIRCULAR_WEIGHTS.map((w) => (
          <WeightCell
            key={`overlay-${w.wght}`}
            family={family}
            glyph={glyph}
            wght={w.wght}
            weightName={w.name}
            style="overlay"
            scores={cellScores(w.wght)}
          />
        ))}
      </Row>
      {verdict && verdict.best && (
        <ProjectionRow family={family} glyph={glyph} verdict={verdict} />
      )}
    </div>
  );
}

function Row({
  label,
  accent,
  children,
}: {
  label: string;
  accent: "donor" | "glide" | "overlay";
  children: React.ReactNode;
}) {
  const dot =
    accent === "donor"
      ? "bg-[--color-donor]"
      : accent === "glide"
        ? "bg-[--color-glide]"
        : "bg-gradient-to-r from-[--color-donor] to-[--color-glide]";
  return (
    <section className="flex flex-col gap-2">
      <header className="flex items-center gap-2">
        <span className={`inline-block h-2 w-2 rounded-full ${dot}`} />
        <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
          {label}
        </h2>
      </header>
      <div className="grid grid-cols-4 gap-3 md:grid-cols-8">{children}</div>
    </section>
  );
}
