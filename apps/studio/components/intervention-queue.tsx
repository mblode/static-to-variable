"use client";

import { STRATEGY_NAMES } from "@static-to-variable/glyph-forge-engine";
import type {
  PendingManifestPatch,
  StrategyName,
} from "@static-to-variable/glyph-forge-engine";
import Link from "next/link";
import { useMemo, useState, useTransition } from "react";

import { ScoreBadge } from "@/components/score-badge";
import { Button } from "@/components/ui/button";
import { VerdictDot } from "@/components/verdict-dot";
import type { InterventionGlyph } from "@/lib/interventions.server";
import { cn } from "@/lib/utils";

type QueueFilter = "must_decide" | "candidate" | "all";

export function InterventionQueue({ queue }: { queue: InterventionGlyph[] }) {
  const [filter, setFilter] = useState<QueueFilter>("must_decide");
  const [family, setFamily] = useState<"all" | "roman" | "italic">("all");
  const [search, setSearch] = useState("");
  const [staged, setStaged] = useState<
    Record<string, StrategyName | undefined>
  >(() =>
    Object.fromEntries(queue.map((glyph) => [glyph.key, glyph.pendingStrategy]))
  );
  const [selectedKey, setSelectedKey] = useState<string | null>(
    () => queue[0]?.key ?? null
  );

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return queue.filter((glyph) => {
      if (filter !== "all" && glyph.tier !== filter) {
        return false;
      }
      if (family !== "all" && glyph.family !== family) {
        return false;
      }
      if (needle && !glyph.key.toLowerCase().includes(needle)) {
        return false;
      }
      return true;
    });
  }, [family, filter, queue, search]);
  const selected =
    visible.find((glyph) => glyph.key === selectedKey) ?? visible[0] ?? null;

  const advanceFrom = (key: string) => {
    const index = visible.findIndex((glyph) => glyph.key === key);
    const next = index !== -1 ? visible[index + 1] : visible[0];
    setSelectedKey(next?.key ?? null);
  };

  return (
    <section className="rounded-lg border border-border bg-card">
      <header className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h2 className="mr-auto text-sm font-medium text-foreground">
          Reconstruction queue
        </h2>
        <Segmented
          value={filter}
          options={[
            ["must_decide", "Required"],
            ["candidate", "Staged"],
            ["all", "All"],
          ]}
          onChange={setFilter}
        />
        <Segmented
          value={family}
          options={[
            ["all", "Both"],
            ["roman", "Roman"],
            ["italic", "Italic"],
          ]}
          onChange={setFamily}
        />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="glyph"
          className="h-8 w-40 rounded-md border border-border bg-background px-2 font-mono text-xs text-foreground placeholder:text-muted-foreground/60 focus:border-ring focus:outline-none"
        />
      </header>

      {selected && (
        <FocusedWorkbench
          key={selected.key}
          glyph={selected}
          stagedStrategy={staged[selected.key]}
          onSelectGlyph={setSelectedKey}
          onAdvance={advanceFrom}
          onStaged={setStaged}
          queue={visible.slice(0, 12)}
        />
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[980px] border-collapse font-mono text-xs">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground/70">
              <th className="px-4 py-2.5 font-medium">Glyph</th>
              <th className="px-4 py-2.5 font-medium">Worst</th>
              <th className="px-4 py-2.5 font-medium">Gain</th>
              <th className="px-4 py-2.5 font-medium">Current</th>
              <th className="px-4 py-2.5 font-medium">Suggestion</th>
              <th className="px-4 py-2.5 font-medium">Decision</th>
              <th className="px-4 py-2.5 font-medium" />
            </tr>
          </thead>
          <tbody>
            {visible.map((glyph) => (
              <tr
                key={glyph.key}
                className="border-b border-border last:border-0"
              >
                <td className="px-4 py-2.5">
                  <Link
                    href={`/g/${glyph.family}/${encodeURIComponent(glyph.name)}`}
                    className="inline-flex items-center gap-2 hover:text-primary"
                  >
                    <VerdictDot verdict={glyph.verdict} />
                    <span className="text-muted-foreground/70">
                      {glyph.family}/
                    </span>
                    <span>{glyph.name}</span>
                    {glyph.requiresReconstruction && (
                      <span className="rounded bg-[--color-band-red]/15 px-1.5 py-0.5 text-[10px] text-[--color-band-red]">
                        reconstruct
                      </span>
                    )}
                  </Link>
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <ScoreBadge composite={glyph.worstComposite} compact />
                    {glyph.worstWght !== null && (
                      <span className="text-muted-foreground/70">
                        @{glyph.worstWght}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2.5 text-muted-foreground">
                  {glyph.gain === null
                    ? "—"
                    : `+${Math.round(glyph.gain * 100)}`}
                </td>
                <td className="px-4 py-2.5 text-muted-foreground">
                  {glyph.currentStrategy ?? "—"}
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex flex-col gap-1">
                    <span>
                      {glyph.suggestedStrategy ?? glyph.bestStrategy ?? "—"}
                    </span>
                    {glyph.suggestionReason && (
                      <span className="max-w-[320px] truncate text-[10px] text-muted-foreground/70">
                        {glyph.suggestionReason}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2.5">
                  {staged[glyph.key] ? (
                    <span className="rounded bg-[--color-band-amber]/15 px-2 py-1 text-[--color-band-amber]">
                      staged {staged[glyph.key]}
                    </span>
                  ) : (
                    <span className="text-muted-foreground/60">not staged</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right">
                  <div className="flex justify-end gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="xs"
                      onClick={() => setSelectedKey(glyph.key)}
                    >
                      focus
                    </Button>
                    <StageButton glyph={glyph} onStaged={setStaged} />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {visible.length === 0 && (
        <p className="px-4 py-10 text-center text-sm text-muted-foreground">
          No interventions match the current filters.
        </p>
      )}
    </section>
  );
}

function FocusedWorkbench({
  glyph,
  queue,
  stagedStrategy,
  onSelectGlyph,
  onAdvance,
  onStaged,
}: {
  glyph: InterventionGlyph;
  queue: InterventionGlyph[];
  stagedStrategy?: StrategyName;
  onSelectGlyph: (key: string) => void;
  onAdvance: (key: string) => void;
  onStaged: React.Dispatch<
    React.SetStateAction<Record<string, StrategyName | undefined>>
  >;
}) {
  return (
    <div className="grid gap-4 border-b border-border p-4 xl:grid-cols-[220px_minmax(0,1fr)_360px]">
      <div className="rounded-md border border-border bg-background p-2">
        <p className="px-2 pb-2 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          Review rail
        </p>
        <div className="grid max-h-[360px] gap-1 overflow-y-auto">
          {queue.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => onSelectGlyph(item.key)}
              className={cn(
                "grid gap-1 rounded px-2 py-2 text-left font-mono text-[11px]",
                item.key === glyph.key
                  ? "bg-foreground text-background"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <span className="truncate">{item.name}</span>
              <span className="text-[10px] opacity-70">
                {item.family} · {item.verdict}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-md border border-border bg-background p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <VerdictDot verdict={glyph.verdict} />
              <h3 className="font-mono text-base">
                <span className="text-muted-foreground">{glyph.family}/</span>
                {glyph.name}
              </h3>
            </div>
            <p className="mt-1 font-mono text-[11px] text-muted-foreground">
              {glyph.tier} · {glyph.verdict}
            </p>
          </div>
          <div className="flex gap-2">
            <Button asChild variant="outline" size="xs">
              <Link
                href={`/g/${glyph.family}/${encodeURIComponent(glyph.name)}`}
              >
                inspect
              </Link>
            </Button>
            <Button asChild variant="outline" size="xs">
              <Link
                href={`/api/export/${glyph.family}/${encodeURIComponent(glyph.name)}`}
              >
                export
              </Link>
            </Button>
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <Evidence
            label="Worst"
            value={<ScoreBadge composite={glyph.worstComposite} compact />}
          />
          <Evidence
            label="Weight"
            value={
              glyph.worstWght === null ? "unknown" : String(glyph.worstWght)
            }
          />
          <Evidence
            label="Gain"
            value={
              glyph.gain === null
                ? "unknown"
                : `+${Math.round(glyph.gain * 100)}`
            }
          />
          <Evidence label="Current" value={glyph.currentStrategy ?? "none"} />
          <Evidence
            label="Review"
            value={
              glyph.requiresReconstruction ? "reconstruction" : "automatic"
            }
          />
          <Evidence
            label="Suggested"
            value={glyph.suggestedStrategy ?? glyph.bestStrategy ?? "none"}
          />
          <Evidence label="Pending" value={stagedStrategy ?? "none"} />
        </div>

        {(glyph.reconstructionReason || glyph.suggestionReason) && (
          <p className="mt-4 rounded-md border border-border bg-card p-3 text-sm text-muted-foreground">
            {glyph.reconstructionReason ?? glyph.suggestionReason}
          </p>
        )}
      </div>

      <WorkbenchDecision
        glyph={glyph}
        onAdvance={onAdvance}
        onStaged={onStaged}
      />
    </div>
  );
}

function Evidence({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-card p-3">
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <div className="mt-1 min-h-5 font-mono text-xs text-foreground">
        {value}
      </div>
    </div>
  );
}

function WorkbenchDecision({
  glyph,
  onAdvance,
  onStaged,
}: {
  glyph: InterventionGlyph;
  onAdvance: (key: string) => void;
  onStaged: React.Dispatch<
    React.SetStateAction<Record<string, StrategyName | undefined>>
  >;
}) {
  const [isPending, startTransition] = useTransition();
  const [strategy, setStrategy] = useState<StrategyName>(() =>
    glyph.requiresReconstruction ? "manual_review" : initialStrategy(glyph)
  );
  const [repairBucket, setRepairBucket] = useState(
    glyph.requiresReconstruction ? "reconstruction_required" : ""
  );
  const [baseGlyph, setBaseGlyph] = useState("");
  const [braceWeights, setBraceWeights] = useState("");
  const [priority, setPriority] = useState(
    glyph.requiresReconstruction ? "blocker" : ""
  );
  const [deferred, setDeferred] = useState(false);
  const [deferReason, setDeferReason] = useState("");
  const [notes, setNotes] = useState(
    glyph.reconstructionReason ?? glyph.suggestionReason ?? ""
  );

  return (
    <form
      className="rounded-md border border-border bg-background p-4"
      onSubmit={(event) => {
        event.preventDefault();
        startTransition(async () => {
          const manifestPatch = buildManifestPatch({
            baseGlyph,
            braceWeights,
            deferReason,
            deferred,
            priority,
            repairBucket,
          });
          const res = await fetch("/api/triage/stage", {
            body: JSON.stringify({
              family: glyph.family,
              glyph: glyph.name,
              strategy,
              source: "manual",
              notes: notes.trim() || undefined,
              manifestPatch,
            }),
            headers: { "content-type": "application/json" },
            method: "POST",
          });
          if (res.ok) {
            onStaged((current) => ({ ...current, [glyph.key]: strategy }));
            onAdvance(glyph.key);
          }
        });
      }}
    >
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        Decision
      </p>
      <div className="mt-3 grid gap-2">
        <label className="grid gap-1 font-mono text-[11px] text-muted-foreground">
          Strategy
          <select
            value={strategy}
            onChange={(event) =>
              setStrategy(event.target.value as StrategyName)
            }
            className="h-8 rounded-md border border-border bg-card px-2 text-xs text-foreground"
          >
            {STRATEGY_NAMES.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 font-mono text-[11px] text-muted-foreground">
          Repair bucket
          <input
            value={repairBucket}
            onChange={(event) => setRepairBucket(event.target.value)}
            className="h-8 rounded-md border border-border bg-card px-2 text-xs text-foreground"
          />
        </label>
        <label className="grid gap-1 font-mono text-[11px] text-muted-foreground">
          Base glyph
          <input
            value={baseGlyph}
            onChange={(event) => setBaseGlyph(event.target.value)}
            className="h-8 rounded-md border border-border bg-card px-2 text-xs text-foreground"
          />
        </label>
        <label className="grid gap-1 font-mono text-[11px] text-muted-foreground">
          Brace weights
          <input
            value={braceWeights}
            onChange={(event) => setBraceWeights(event.target.value)}
            placeholder="250, 400, 950"
            className="h-8 rounded-md border border-border bg-card px-2 text-xs text-foreground placeholder:text-muted-foreground/50"
          />
        </label>
        <label className="grid gap-1 font-mono text-[11px] text-muted-foreground">
          Priority
          <input
            value={priority}
            onChange={(event) => setPriority(event.target.value)}
            className="h-8 rounded-md border border-border bg-card px-2 text-xs text-foreground"
          />
        </label>
        <label className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
          <input
            type="checkbox"
            checked={deferred}
            onChange={(event) => setDeferred(event.target.checked)}
          />
          Defer
        </label>
        {deferred && (
          <input
            value={deferReason}
            onChange={(event) => setDeferReason(event.target.value)}
            placeholder="defer reason"
            className="h-8 rounded-md border border-border bg-card px-2 font-mono text-xs text-foreground placeholder:text-muted-foreground/50"
          />
        )}
        <textarea
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          rows={3}
          className="min-h-20 rounded-md border border-border bg-card px-2 py-2 font-mono text-xs text-foreground"
        />
      </div>
      <Button
        type="submit"
        className="mt-3 w-full"
        size="sm"
        disabled={isPending}
      >
        {isPending ? "Staging" : "Stage & next"}
      </Button>
    </form>
  );
}

function StageButton({
  glyph,
  onStaged,
}: {
  glyph: InterventionGlyph;
  onStaged: React.Dispatch<
    React.SetStateAction<Record<string, StrategyName | undefined>>
  >;
}) {
  const [isPending, startTransition] = useTransition();
  const strategy = glyph.suggestedStrategy ?? glyph.bestStrategy;

  if (glyph.requiresReconstruction) {
    return (
      <Button type="button" variant="outline" size="xs" disabled>
        rebuild
      </Button>
    );
  }

  if (!strategy) {
    return (
      <Button asChild variant="outline" size="xs">
        <Link href={`/g/${glyph.family}/${encodeURIComponent(glyph.name)}`}>
          inspect
        </Link>
      </Button>
    );
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="xs"
      disabled={isPending}
      onClick={() => {
        startTransition(async () => {
          const res = await fetch("/api/triage/stage", {
            body: JSON.stringify({
              family: glyph.family,
              glyph: glyph.name,
              strategy,
              source: "suggestion",
              notes: glyph.suggestionReason,
            }),
            headers: { "content-type": "application/json" },
            method: "POST",
          });
          if (res.ok) {
            onStaged((current) => ({ ...current, [glyph.key]: strategy }));
          }
        });
      }}
    >
      {isPending ? "staging" : "stage"}
    </Button>
  );
}

function initialStrategy(glyph: InterventionGlyph): StrategyName {
  if (glyph.suggestedStrategy) {
    return glyph.suggestedStrategy;
  }
  if (glyph.bestStrategy) {
    return glyph.bestStrategy;
  }
  if (
    glyph.currentStrategy &&
    (STRATEGY_NAMES as readonly string[]).includes(glyph.currentStrategy)
  ) {
    return glyph.currentStrategy as StrategyName;
  }
  return "manual_review";
}

function buildManifestPatch({
  repairBucket,
  baseGlyph,
  braceWeights,
  priority,
  deferred,
  deferReason,
}: {
  repairBucket: string;
  baseGlyph: string;
  braceWeights: string;
  priority: string;
  deferred: boolean;
  deferReason: string;
}): PendingManifestPatch | undefined {
  const patch: PendingManifestPatch = {};
  if (repairBucket.trim()) {
    patch.repair_bucket = repairBucket.trim();
  }
  if (baseGlyph.trim()) {
    patch.base_glyph = baseGlyph.trim();
  }
  if (priority.trim()) {
    patch.priority = priority.trim();
  }
  const weights = braceWeights
    .split(",")
    .map((value) => Number(value.trim()))
    .filter(Number.isFinite);
  if (weights.length > 0) {
    patch.brace_weights = weights;
  }
  if (deferred) {
    patch.deferred = true;
    if (deferReason.trim()) {
      patch.defer_reason = deferReason.trim();
    }
  }
  return Object.keys(patch).length > 0 ? patch : undefined;
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: [T, string][];
  onChange: (value: T) => void;
}) {
  return (
    <div className="inline-flex rounded-md border border-border bg-background p-0.5">
      {options.map(([next, label]) => (
        <button
          key={next}
          type="button"
          onClick={() => onChange(next)}
          className={cn(
            "h-7 rounded px-2 font-mono text-[11px]",
            value === next
              ? "bg-foreground text-background"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
