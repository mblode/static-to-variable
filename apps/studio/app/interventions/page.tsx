import Link from "next/link";
import type * as React from "react";

import { ApplyPendingPanel } from "@/components/apply-pending-panel";
import { CopyCommand } from "@/components/copy-command";
import { InterventionQueue } from "@/components/intervention-queue";
import { Button } from "@/components/ui/button";
import { buildInterventionDashboard } from "@/lib/interventions.server";
import { cn } from "@/lib/utils";

export const metadata = { title: "Interventions — Static to Variable" };
export const dynamic = "force-dynamic";

export default async function InterventionsPage() {
  const dashboard = await buildInterventionDashboard();
  const verdict = dashboard.status?.verdict ?? "missing";

  return (
    <main>
      <div className="mx-auto flex max-w-[1600px] items-center gap-2 px-6 pt-4">
        <StatusPill status={verdict} />
      </div>

      <div className="mx-auto grid max-w-[1600px] gap-6 px-6 py-6">
        <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <Metric
            label="Blocking"
            value={dashboard.counts.blockingFailures}
            tone="red"
          />
          <Metric
            label="Diagnostics"
            value={dashboard.counts.diagnostics}
            tone="amber"
          />
          <Metric
            label="Required"
            value={dashboard.counts.mustDecide}
            tone="red"
          />
          <Metric
            label="Candidates"
            value={dashboard.counts.candidates}
            tone="amber"
          />
          <Metric
            label="Pending"
            value={dashboard.counts.pending}
            tone="green"
          />
        </section>

        <ArtifactBanner stale={dashboard.freshness.stale}>
          {dashboard.freshness.message}
        </ArtifactBanner>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="grid gap-6">
            <StageRail stages={dashboard.stages} />

            {dashboard.residualIssues.length > 0 && (
              <ResidualPanel issues={dashboard.residualIssues} />
            )}

            <InterventionQueue queue={dashboard.queue} />
          </div>

          <aside className="grid content-start gap-4">
            <ApplyPendingPanel pendingCount={dashboard.counts.pending} />
            <CommandPanel commands={dashboard.commands} />
          </aside>
        </div>
      </div>
    </main>
  );
}

function ArtifactBanner({
  stale,
  children,
}: {
  stale: boolean;
  children: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "rounded-lg border px-4 py-3 font-mono text-xs",
        stale
          ? "border-[--color-band-amber]/40 bg-[--color-band-amber]/10 text-[--color-band-amber]"
          : "border-border bg-card text-muted-foreground"
      )}
    >
      {children}
    </section>
  );
}

function StageRail({
  stages,
}: {
  stages: Awaited<ReturnType<typeof buildInterventionDashboard>>["stages"];
}) {
  return (
    <section className="rounded-lg border border-border bg-card">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium text-foreground">Pipeline stages</h2>
      </header>
      <div className="divide-y divide-border">
        {stages.map((stage) => (
          <div
            key={stage.id}
            className="grid gap-3 px-4 py-3 md:grid-cols-[220px_minmax(0,1fr)_auto]"
          >
            <div>
              <div className="flex items-center gap-2">
                <StageDot status={stage.status} state={stage.state} />
                <p className="font-mono text-xs text-foreground">{stage.id}</p>
              </div>
              <p className="mt-1 text-[11px] text-muted-foreground">
                {stage.kind} · {stage.status}
              </p>
            </div>
            <div>
              <p className="text-sm font-medium">{stage.name}</p>
              <p
                className="mt-1 truncate text-xs text-muted-foreground"
                title={stage.humanLabel}
              >
                {truncatePath(stage.humanLabel)}
              </p>
              {(stage.failures?.length ?? 0) > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {stage.failures?.map((failure) => (
                    <span
                      key={failure}
                      className="max-w-xs truncate rounded bg-[--color-band-red]/10 px-2 py-0.5 font-mono text-[10px] text-[--color-band-red]"
                      title={failure}
                    >
                      {truncatePath(failure)}
                    </span>
                  ))}
                </div>
              )}
              {(stage.observations?.length ?? 0) > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {stage.observations?.map((observation) => (
                    <span
                      key={observation}
                      className="rounded bg-[--color-band-amber]/10 px-2 py-0.5 font-mono text-[10px] text-[--color-band-amber]"
                    >
                      {observation}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2">
              {stage.actionHref && (
                <Button asChild variant="outline" size="xs">
                  <Link href={stage.actionHref}>Open</Link>
                </Button>
              )}
              {stage.command && <CopyCommand command={stage.command} />}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ResidualPanel({
  issues,
}: {
  issues: Awaited<
    ReturnType<typeof buildInterventionDashboard>
  >["residualIssues"];
}) {
  return (
    <section className="rounded-lg border border-border bg-card">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium text-foreground">
          Residual blockers
        </h2>
      </header>
      <div className="grid gap-2 p-4 md:grid-cols-2 xl:grid-cols-3">
        {issues.map((issue) => (
          <Link
            key={issue.key}
            href={`/g/${issue.family}/${encodeURIComponent(issue.glyph)}`}
            className="rounded-md border border-border bg-background p-3 transition-colors hover:border-muted-foreground"
          >
            <div className="flex items-center justify-between gap-2">
              <p className="font-mono text-xs">
                <span className="text-muted-foreground/70">
                  {issue.family}/
                </span>
                {issue.glyph}
              </p>
              {issue.frozen && (
                <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                  frozen
                </span>
              )}
            </div>
            <p className="mt-1 font-mono text-[11px] text-muted-foreground">
              {issue.strategy ?? "no strategy"}
            </p>
            <div className="mt-2 flex flex-wrap gap-1">
              {issue.failures.map((failure) => (
                <span
                  key={failure}
                  className="rounded bg-[--color-band-red]/10 px-2 py-0.5 font-mono text-[10px] text-[--color-band-red]"
                >
                  {failure}
                </span>
              ))}
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

function CommandPanel({
  commands,
}: {
  commands: Awaited<ReturnType<typeof buildInterventionDashboard>>["commands"];
}) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
        Resume commands
      </h2>
      <div className="mt-3 grid gap-2">
        {Object.entries(commands).map(([key, command]) => (
          <div
            key={key}
            className="rounded-md border border-border bg-background p-2"
          >
            <div className="flex items-center justify-between gap-2">
              <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                {key}
              </p>
              <CopyCommand command={command} />
            </div>
            <details className="mt-1">
              <summary className="cursor-pointer text-[11px] text-muted-foreground hover:text-foreground">
                show command
              </summary>
              <code className="mt-1 block break-words font-mono text-[11px] text-foreground">
                {command}
              </code>
            </details>
          </div>
        ))}
      </div>
    </section>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "red" | "amber" | "green";
}) {
  const toneClass = {
    amber: "text-[--color-band-amber]",
    green: "text-[--color-band-green]",
    red: "text-[--color-band-red]",
  }[tone];
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className={cn("mt-2 font-mono text-3xl tabular-nums", toneClass)}>
        {value}
      </p>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "rounded-md px-2 py-1 font-mono text-xs",
        status === "pass"
          ? "bg-[--color-band-green]/15 text-[--color-band-green]"
          : "bg-[--color-band-red]/15 text-[--color-band-red]"
      )}
    >
      {status}
    </span>
  );
}

function truncatePath(path: string): string {
  const markers = ["/packages/", "/reports/", "/manifests/"];
  for (const marker of markers) {
    const idx = path.lastIndexOf(marker);
    if (idx !== -1) {
      return `...${path.slice(idx)}`;
    }
  }
  return path;
}

function StageDot({
  status,
  state,
}: {
  status: string;
  state: Awaited<
    ReturnType<typeof buildInterventionDashboard>
  >["stages"][number]["state"];
}) {
  return (
    <span
      className={cn(
        "size-2.5 rounded-full",
        status === "pass" && "bg-[--color-band-green]",
        state === "diagnostic" && "bg-[--color-band-amber]",
        status !== "pass" && state !== "diagnostic" && "bg-[--color-band-red]"
      )}
    />
  );
}
