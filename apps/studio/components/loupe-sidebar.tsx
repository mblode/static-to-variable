import type {
  PendingTriageEdit,
  SolverVerdict,
  StrategySuggestion,
} from "@static-to-variable/glyph-forge-engine";

import type { ScoredGlyph } from "@/lib/data";

import { SolverCard } from "./solver-card";
import { SuggestionCard } from "./suggestion-card";
import { TriagePanel } from "./triage-panel";

export function LoupeSidebar({
  glyph,
  suggestion,
  pending,
  solver,
}: {
  glyph: ScoredGlyph;
  suggestion?: StrategySuggestion;
  pending: PendingTriageEdit | null;
  solver?: SolverVerdict;
}) {
  return (
    <aside className="flex flex-col gap-4 text-sm">
      {solver && (
        <SolverCard
          verdict={solver}
          family={glyph.family}
          glyph={glyph.name}
          staged={!!pending}
        />
      )}

      {suggestion && (
        <SuggestionCard
          suggestion={suggestion}
          currentStrategy={glyph.existingStrategy}
        />
      )}

      <TriagePanel
        family={glyph.family}
        glyph={glyph.name}
        currentStrategy={glyph.existingStrategy}
        suggestion={suggestion}
        initialPending={pending}
      />

      <section className="flex flex-col gap-5 rounded-lg border border-border bg-card p-5">
        <div className="flex flex-col gap-1">
          <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground/70">
            Origin
          </h2>
          <ul className="font-mono text-xs text-muted-foreground">
            {glyph.sources.map((s) => (
              <li key={s}>· {s}</li>
            ))}
          </ul>
        </div>

        {glyph.existingStrategy && (
          <div className="flex flex-col gap-1">
            <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground/70">
              Current strategy
            </h2>
            <p className="font-mono text-xs text-foreground">
              {glyph.existingStrategy}
            </p>
            {glyph.priority && (
              <p className="text-xs text-muted-foreground/70">
                priority: <span className="font-mono">{glyph.priority}</span>
              </p>
            )}
          </div>
        )}

        {glyph.notes && (
          <div className="flex flex-col gap-1">
            <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground/70">
              Notes
            </h2>
            <p className="whitespace-pre-wrap text-xs leading-relaxed text-foreground">
              {glyph.notes}
            </p>
          </div>
        )}

        <div className="flex flex-col gap-1">
          <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground/70">
            Audit report
          </h2>
          <p className="text-xs text-muted-foreground">
            Row-level findings live in
            <br />
            <code className="text-foreground">
              packages/variable-gen/reports/audit/{glyph.family}/{glyph.family}
              -variable-audit.md
            </code>
          </p>
        </div>
      </section>
    </aside>
  );
}
