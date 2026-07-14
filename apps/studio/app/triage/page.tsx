import type { BrokenGlyph } from "@static-to-variable/glyph-forge-engine";
import Link from "next/link";

import { TriageActions } from "@/components/triage-actions";
import { VerdictDot } from "@/components/verdict-dot";
import { loadManifest } from "@/lib/data.server";
import { keyOf, readPending } from "@/lib/pending.server";

export const metadata = { title: "Triage queue — Static to Variable" };

export default async function TriagePage() {
  const [manifest, pending] = await Promise.all([
    loadManifest(),
    readPending(),
  ]);
  const byKey = new Map<string, BrokenGlyph>();
  for (const g of manifest) {
    byKey.set(`${g.family}/${g.name}`, g);
  }

  const rows = pending
    .map((p) => ({
      glyph: byKey.get(keyOf(p)),
      pending: p,
    }))
    .toSorted((a, b) => keyOf(a.pending).localeCompare(keyOf(b.pending)));

  const counts: Record<string, number> = {};
  for (const p of pending) {
    counts[p.strategy] = (counts[p.strategy] ?? 0) + 1;
  }

  return (
    <main>
      {pending.length > 0 && (
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-2 px-6 pt-4 font-mono text-xs text-muted-foreground">
          <span className="text-muted-foreground/70">by strategy:</span>
          {Object.entries(counts)
            .toSorted((a, b) => b[1] - a[1])
            .map(([strat, n]) => (
              <span key={strat} className="rounded bg-card px-2 py-0.5">
                {strat} · {n}
              </span>
            ))}
        </div>
      )}

      <div className="mx-auto max-w-[1600px] px-6 py-6">
        {pending.length === 0 ? (
          <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-muted-foreground">
            <p>No pending edits.</p>
            <p className="mt-2 text-xs text-muted-foreground/70">
              Stage a strategy from any glyph loupe to populate this queue.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <table className="w-full border-collapse font-mono text-xs">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground/70">
                  <th className="px-4 py-2.5 font-medium">Glyph</th>
                  <th className="px-4 py-2.5 font-medium">Current</th>
                  <th className="px-4 py-2.5 font-medium">Proposed</th>
                  <th className="px-4 py-2.5 font-medium">Source</th>
                  <th className="px-4 py-2.5 font-medium">Staged at</th>
                  <th className="px-4 py-2.5 font-medium" />
                </tr>
              </thead>
              <tbody>
                {rows.map(({ pending: p, glyph }) => {
                  const changed = (p.previousStrategy ?? "") !== p.strategy;
                  return (
                    <tr
                      key={keyOf(p)}
                      className="border-b border-border last:border-0"
                    >
                      <td className="px-4 py-2.5">
                        <Link
                          href={`/g/${p.family}/${encodeURIComponent(p.glyph)}`}
                          className="flex items-center gap-2 text-foreground hover:text-primary"
                        >
                          {glyph && <VerdictDot verdict={glyph.auditVerdict} />}
                          <span className="text-muted-foreground/70">
                            {p.family}/
                          </span>
                          <span>{p.glyph}</span>
                        </Link>
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground/70">
                        {p.previousStrategy ?? "—"}
                      </td>
                      <td className="px-4 py-2.5">
                        <span
                          className={
                            changed
                              ? "text-[--color-band-amber]"
                              : "text-muted-foreground"
                          }
                        >
                          {p.strategy}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground">
                        {p.source}
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground/70">
                        {new Date(p.stagedAt).toLocaleString()}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <TriageActions family={p.family} glyph={p.glyph} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {pending.length > 0 && (
          <div className="mt-6 rounded-lg border border-border bg-background p-4 text-xs">
            <h2 className="font-mono font-semibold text-foreground">
              Apply these edits
            </h2>
            <p className="mt-2 text-muted-foreground">
              The UI never writes to <code>circular-triage.json</code> directly.
              Review the diff and merge via CLI:
            </p>
            <pre className="mt-3 overflow-x-auto rounded bg-muted p-3 font-mono text-[11px] text-foreground">
              {`# dry-run first — prints the diff without writing
npm --workspace @static-to-variable/glyph-forge-engine run apply -- --dry-run

# write to circular-triage.json (auto-backs up the current file)
npm --workspace @static-to-variable/glyph-forge-engine run apply`}
            </pre>
          </div>
        )}
      </div>
    </main>
  );
}
