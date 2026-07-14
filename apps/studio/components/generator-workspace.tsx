"use client";

import * as React from "react";

import type {
  GenerationArtifact,
  GenerationJob,
  GenerationJobStatus,
  GenerationStageRun,
} from "@/lib/generation-types";
import { isActiveGenerationStatus } from "@/lib/generation-types";
import { cn } from "@/lib/utils";

interface GeneratorWorkspaceProps {
  initialJobs: GenerationJob[];
}

export function GeneratorWorkspace({ initialJobs }: GeneratorWorkspaceProps) {
  const [jobs, setJobs] = React.useState(initialJobs);
  const [selectedId, setSelectedId] = React.useState(initialJobs[0]?.id ?? "");
  const [files, setFiles] = React.useState<File[]>([]);
  const [useWorkspaceSources, setUseWorkspaceSources] = React.useState(false);
  const [isDragging, setIsDragging] = React.useState(false);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string | null>(null);
  const [log, setLog] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);

  const selectedJob =
    jobs.find((job) => job.id === selectedId) ?? jobs[0] ?? null;
  const activeJob = jobs.find((job) => isActiveGenerationStatus(job.status));

  React.useEffect(() => {
    setLog("");
  }, [selectedId]);

  React.useEffect(() => {
    if (!activeJob) {
      return;
    }
    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;

    async function pollJobs() {
      try {
        const response = await fetch("/api/generate/jobs", {
          cache: "no-store",
        });
        if (!cancelled && response.ok) {
          const payload = (await response.json()) as { jobs: GenerationJob[] };
          setJobs(payload.jobs);
        }
      } finally {
        if (!cancelled) {
          timeout = setTimeout(pollJobs, 3000);
        }
      }
    }

    void pollJobs();
    return () => {
      cancelled = true;
      if (timeout) {
        clearTimeout(timeout);
      }
    };
  }, [activeJob?.id]);

  React.useEffect(() => {
    if (!selectedJob) {
      return;
    }
    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      try {
        const [jobResponse, logResponse] = await Promise.all([
          fetch(`/api/generate/jobs/${selectedJob.id}`, { cache: "no-store" }),
          fetch(`/api/generate/jobs/${selectedJob.id}/log`, {
            cache: "no-store",
          }),
        ]);
        if (!cancelled && jobResponse.ok) {
          const payload = (await jobResponse.json()) as { job: GenerationJob };
          setJobs((current) => upsertJob(current, payload.job));
        }
        if (!cancelled && logResponse.ok) {
          setLog(await logResponse.text());
        }
      } finally {
        if (
          !cancelled &&
          selectedJob &&
          isActiveGenerationStatus(selectedJob.status)
        ) {
          timeout = setTimeout(poll, 2500);
        }
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timeout) {
        clearTimeout(timeout);
      }
    };
  }, [selectedJob?.id, selectedJob?.status]);

  async function refreshJobs() {
    const response = await fetch("/api/generate/jobs", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = (await response.json()) as { jobs: GenerationJob[] };
    setJobs(payload.jobs);
    if (!selectedId && payload.jobs[0]) {
      setSelectedId(payload.jobs[0].id);
    }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    setIsSubmitting(true);
    try {
      const form = new FormData();
      form.set("useWorkspaceSources", String(useWorkspaceSources));
      for (const file of files) {
        form.append("files", file);
      }

      const response = await fetch("/api/generate/jobs", {
        body: form,
        method: "POST",
      });
      const payload = (await response.json()) as {
        job?: GenerationJob;
        error?: string;
      };
      if (!response.ok || !payload.job) {
        throw new Error(payload.error ?? "Could not start generation job.");
      }
      const { job } = payload;
      setJobs((current) => upsertJob(current, job));
      setSelectedId(job.id);
      setFiles([]);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
      void refreshJobs();
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : String(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  function addFiles(list: FileList | null) {
    if (!list) {
      return;
    }
    const next = [...list];
    setFiles((current) => dedupeFiles([...current, ...next]));
  }

  return (
    <div className="mx-auto grid max-w-[1600px] gap-6 px-6 py-6 xl:grid-cols-[430px_minmax(0,1fr)]">
      <form
        className="grid content-start gap-4"
        onSubmit={submit}
        onDragEnter={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => {
          if (
            event.currentTarget.contains(event.relatedTarget as Node | null)
          ) {
            return;
          }
          setIsDragging(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          addFiles(event.dataTransfer.files);
        }}
      >
        <section
          className={cn(
            "rounded-lg border bg-card",
            isDragging ? "border-foreground" : "border-border"
          )}
        >
          <header className="border-b border-border px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-medium text-foreground">
                  Source intake
                </h2>
                <p className="mt-1 text-sm font-medium">
                  Circular OTFs, glyph sources, triage manifests
                </p>
              </div>
              <button
                className="rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-muted"
                type="button"
                onClick={() => inputRef.current?.click()}
              >
                Browse
              </button>
            </div>
          </header>
          <div className="grid gap-4 p-4">
            <label
              className={cn(
                "grid min-h-36 place-items-center rounded-md border border-dashed p-4 text-center transition-colors",
                isDragging
                  ? "border-foreground bg-muted"
                  : "border-border bg-background"
              )}
            >
              <input
                ref={inputRef}
                className="sr-only"
                type="file"
                multiple
                accept=".otf,.ttf,.glyphs,.json"
                onChange={(event) => addFiles(event.currentTarget.files)}
              />
              <span className="grid gap-1">
                <span className="text-sm font-medium">Drop source files</span>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {files.length} queued · {formatBytes(sumFileSize(files))}
                </span>
              </span>
            </label>

            <label className="flex items-start gap-3 rounded-md border border-border bg-background p-3">
              <input
                checked={useWorkspaceSources}
                className="mt-1"
                type="checkbox"
                onChange={(event) =>
                  setUseWorkspaceSources(event.currentTarget.checked)
                }
              />
              <span>
                <span className="block text-sm font-medium">
                  Use workspace templates for missing targets
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  Uploaded files are overlaid; missing source files and triage
                  data come from the isolated copy.
                </span>
              </span>
            </label>

            {!useWorkspaceSources && (
              <p className="rounded-md border border-[--color-band-amber]/40 bg-[--color-band-amber]/10 px-3 py-2 text-xs text-[--color-band-amber]">
                Strict upload mode requires all 16 Circular OTFs, both `.glyphs`
                sources, and `circular-triage.json`.
              </p>
            )}

            {files.length > 0 && (
              <div className="max-h-52 overflow-auto rounded-md border border-border">
                {files.map((file) => (
                  <div
                    key={`${file.name}:${file.size}:${file.lastModified}`}
                    className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 border-b border-border px-3 py-2 last:border-b-0"
                  >
                    <span className="truncate font-mono text-xs">
                      {file.name}
                    </span>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {formatBytes(file.size)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {submitError && (
              <p className="rounded-md border border-[--color-band-red]/40 bg-[--color-band-red]/10 px-3 py-2 text-sm text-[--color-band-red]">
                {submitError}
              </p>
            )}

            <div className="flex items-center justify-between gap-3">
              <button
                className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-45"
                disabled={isSubmitting || Boolean(activeJob)}
                type="submit"
              >
                {isSubmitting ? "Starting" : "Generate variable fonts"}
              </button>
              {files.length > 0 && (
                <button
                  className="rounded-md border border-border px-3 py-2 text-sm hover:bg-muted"
                  type="button"
                  onClick={() => {
                    setFiles([]);
                    if (inputRef.current) {
                      inputRef.current.value = "";
                    }
                  }}
                >
                  Clear
                </button>
              )}
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-border bg-card">
          <header className="border-b border-border px-4 py-3">
            <h2 className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
              Jobs
            </h2>
          </header>
          <div className="divide-y divide-border">
            {jobs.length === 0 ? (
              <p className="px-4 py-6 text-sm text-muted-foreground">
                No jobs yet.
              </p>
            ) : (
              jobs.map((job) => (
                <button
                  key={job.id}
                  className={cn(
                    "grid w-full gap-1 px-4 py-3 text-left hover:bg-muted/60",
                    selectedJob?.id === job.id && "bg-muted"
                  )}
                  title={job.id}
                  type="button"
                  onClick={() => setSelectedId(job.id)}
                >
                  <span className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium">
                      {formatJobTimestamp(job.id)}
                    </span>
                    <StatusPill status={job.status} />
                  </span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {job.inputs.length} inputs
                  </span>
                </button>
              ))
            )}
          </div>
        </section>
      </form>

      <section className="grid content-start gap-6">
        {selectedJob ? (
          <>
            <JobHeader job={selectedJob} />
            <StageTable stages={selectedJob.stages} />
            <Artifacts job={selectedJob} artifacts={selectedJob.artifacts} />
            <LogPanel log={log} />
          </>
        ) : (
          <div className="rounded-lg border border-border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
            No generation job selected.
          </div>
        )}
      </section>
    </div>
  );
}

function JobHeader({ job }: { job: GenerationJob }) {
  const completed = job.stages.filter(
    (stage) => stage.status === "succeeded"
  ).length;
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-mono text-sm" title={job.id}>
              {job.id.slice(-8)}
            </h2>
            <StatusPill status={job.status} />
            {job.pipelineVerdict && (
              <span className="rounded bg-muted px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                verdict {job.pipelineVerdict}
              </span>
            )}
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            {completed}/{job.stages.length} stages · {job.inputs.length} inputs
            · {job.artifacts.length} outputs
          </p>
        </div>
        <div className="grid gap-1 text-right font-mono text-[11px] text-muted-foreground">
          <span>created {new Date(job.createdAt).toLocaleTimeString()}</span>
          <span>updated {new Date(job.updatedAt).toLocaleTimeString()}</span>
        </div>
      </div>
      {(job.error || job.warnings.length > 0) && (
        <div className="mt-4 grid gap-2">
          {job.error && (
            <p className="rounded-md border border-[--color-band-red]/40 bg-[--color-band-red]/10 px-3 py-2 text-sm text-[--color-band-red]">
              {job.error}
            </p>
          )}
          {job.warnings.map((warning) => (
            <p
              key={warning}
              className="rounded-md border border-[--color-band-amber]/40 bg-[--color-band-amber]/10 px-3 py-2 text-xs text-[--color-band-amber]"
            >
              {warning}
            </p>
          ))}
        </div>
      )}
      {job.status === "needs_review" && (
        <div className="mt-4 rounded-md border border-[--color-band-amber]/40 bg-[--color-band-amber]/10 px-3 py-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-[--color-band-amber]">
              Human review is required before these fonts should be promoted.
            </p>
            <a
              className="rounded-md border border-[--color-band-amber]/40 px-2.5 py-1.5 text-xs text-[--color-band-amber] hover:bg-[--color-band-amber]/10"
              href="/interventions"
            >
              Open interventions
            </a>
          </div>
        </div>
      )}
    </section>
  );
}

function StageTable({ stages }: { stages: GenerationStageRun[] }) {
  return (
    <section className="rounded-lg border border-border bg-card">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium text-foreground">Pipeline</h2>
      </header>
      <div className="divide-y divide-border">
        {stages.map((stage) => (
          <div
            key={stage.id}
            className="grid gap-3 px-4 py-3 md:grid-cols-[180px_minmax(0,1fr)_120px]"
          >
            <div className="flex items-center gap-2">
              <StageDot status={stage.status} />
              <div>
                <p className="font-mono text-xs">{stage.id}</p>
                <p className="font-mono text-[11px] text-muted-foreground">
                  {stage.phase}
                </p>
              </div>
            </div>
            <div>
              <p className="text-sm font-medium">{stage.title}</p>
              {stage.summary && (
                <p
                  className="mt-1 truncate text-xs text-muted-foreground"
                  title={stage.summary}
                >
                  {truncatePath(stage.summary)}
                </p>
              )}
              {stage.error && (
                <p className="mt-1 text-xs text-[--color-band-red]">
                  {stage.error}
                </p>
              )}
              {stage.command && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-[11px] text-muted-foreground hover:text-foreground">
                    show command
                  </summary>
                  <code className="mt-1 block break-words font-mono text-[11px] text-muted-foreground">
                    {stage.command}
                  </code>
                </details>
              )}
            </div>
            <div className="font-mono text-[11px] text-muted-foreground md:text-right">
              {stage.durationMs
                ? formatDuration(stage.durationMs)
                : stage.status}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Artifacts({
  job,
  artifacts,
}: {
  job: GenerationJob;
  artifacts: GenerationArtifact[];
}) {
  if (artifacts.length === 0) {
    return null;
  }
  const reviewOnly = job.status !== "succeeded";
  return (
    <section className="rounded-lg border border-border bg-card">
      <header className="border-b border-border px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            {reviewOnly ? "Review artifacts" : "Outputs"}
          </h2>
          {reviewOnly && (
            <span className="rounded bg-[--color-band-amber]/10 px-2 py-0.5 font-mono text-[11px] text-[--color-band-amber]">
              provisional
            </span>
          )}
        </div>
        {reviewOnly && (
          <p className="mt-2 text-xs text-muted-foreground">
            TTFs are available for inspection, but promotion is blocked until
            review clears.
          </p>
        )}
      </header>
      <div className="grid gap-2 p-4 md:grid-cols-2">
        {artifacts.map((artifact) => (
          <a
            key={artifact.id}
            className="rounded-md border border-border bg-background p-3 hover:border-muted-foreground"
            href={`/api/generate/jobs/${job.id}/artifacts/${artifact.id}`}
          >
            <span className="block text-sm font-medium">{artifact.label}</span>
            <span className="mt-1 block font-mono text-[11px] text-muted-foreground">
              {artifact.fileName} · {formatBytes(artifact.size)}
            </span>
            {artifact.sha256 && (
              <span className="mt-1 block font-mono text-[10px] text-muted-foreground/70">
                sha256 {artifact.sha256.slice(0, 12)}
              </span>
            )}
          </a>
        ))}
      </div>
    </section>
  );
}

function LogPanel({ log }: { log: string }) {
  return (
    <section className="rounded-lg border border-border bg-card">
      <header className="border-b border-border px-4 py-3">
        <h2 className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
          Log
        </h2>
      </header>
      <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap p-4 font-mono text-[11px] leading-relaxed text-muted-foreground">
        {log || "No log output yet."}
      </pre>
    </section>
  );
}

function StatusPill({ status }: { status: GenerationJobStatus }) {
  const className = {
    cancelled: "bg-muted text-muted-foreground",
    failed: "bg-[--color-band-red]/10 text-[--color-band-red]",
    needs_review: "bg-[--color-band-amber]/10 text-[--color-band-amber]",
    queued: "bg-muted text-muted-foreground",
    running: "bg-[--color-band-amber]/10 text-[--color-band-amber]",
    succeeded: "bg-[--color-band-green]/10 text-[--color-band-green]",
  }[status];
  return (
    <span
      className={cn("rounded px-2 py-0.5 font-mono text-[11px]", className)}
    >
      {status}
    </span>
  );
}

function StageDot({ status }: { status: GenerationStageRun["status"] }) {
  const className = {
    failed: "bg-[--color-band-red]",
    pending: "bg-muted",
    running: "bg-[--color-band-amber]",
    skipped: "bg-muted-foreground",
    succeeded: "bg-[--color-band-green]",
  }[status];
  return <span className={cn("size-2 rounded-full", className)} />;
}

function upsertJob(jobs: GenerationJob[], job: GenerationJob): GenerationJob[] {
  const without = jobs.filter((candidate) => candidate.id !== job.id);
  return [job, ...without].toSorted((a, b) =>
    b.createdAt.localeCompare(a.createdAt)
  );
}

function dedupeFiles(files: File[]): File[] {
  const seen = new Set<string>();
  const out: File[] = [];
  for (const file of files) {
    const key = `${file.name}:${file.size}:${file.lastModified}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    out.push(file);
  }
  return out;
}

function sumFileSize(files: File[]): number {
  return files.reduce((total, file) => total + file.size, 0);
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${ms}ms`;
  }
  const seconds = ms / 1000;
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function formatJobTimestamp(jobId: string): string {
  const match = jobId.match(
    /^(?<year>\d{4})(?<month>\d{2})(?<day>\d{2})(?<hours>\d{2})(?<minutes>\d{2})(?<seconds>\d{2})/
  );
  if (!match?.groups) {
    return jobId;
  }
  const { month, day, hours, minutes } = match.groups;
  const monthNames = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  const monthName = monthNames[Number(month) - 1] ?? month;
  return `${monthName} ${Number(day)}, ${hours}:${minutes}`;
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
