/**
 * Instrumentation for the server-side font build (`app/api/build/route.ts`).
 *
 * Vercel sees a healthy 200 for every build. The route streams SSE, so the
 * response headers go out the moment the stream opens and every failure is
 * delivered inside the body minutes later; Observability reports 0% error and
 * 0% timeout on the route even when nothing built. The engine's own output is
 * worse off: runner.py writes its chatter to <job_dir>/build.log inside a
 * microVM the route destroys on the way out, and the Sandboxes dashboard
 * reports CPU and transfer but no logs. Nothing below the function boundary
 * reaches the dashboard unless it is logged here.
 *
 * Every line is one JSON object tagged `scope: "stv.build"` so Observability's
 * Query view can filter on it, and carries the `x-vercel-id` request id plus
 * the Sandbox name (the `teal-wet-jaguar-xxxx` under Observability → Sandboxes)
 * so a log line joins to both the platform's request record and its microVM's
 * metrics.
 */

export const LOG_SCOPE = "stv.build";

/** Rolling stderr lines kept for the summary line. */
export const STDERR_TAIL_LINES = 8;
/**
 * Vercel truncates a runtime log line at 4 KB, and a truncated line is no
 * longer parseable JSON, which defeats structured querying. Rather than cut the
 * serialized line, cap the two fields that can grow without bound (stderr
 * lines, error detail) so the object is small by construction.
 */
export const MAX_FIELD_CHARS = 240;

/**
 * A bounded, stable set of outcomes, so dashboards and alerts can group on
 * `outcome` without unbounded cardinality. Engine-specific failures all report
 * `engine_error` and carry their own code in `errorCode`.
 */
export type BuildOutcome =
  | "succeeded"
  | "setup_failed"
  | "engine_error"
  | "build_failed"
  | "timeout"
  | "client_closed"
  | "sandbox_failed"
  | "unknown";

/** `client_closed` is the user leaving, not a defect; everything else is. */
export function isFailure(outcome: BuildOutcome): boolean {
  return outcome !== "succeeded" && outcome !== "client_closed";
}

export function truncate(text: string, limit = MAX_FIELD_CHARS): string {
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

/** Last `limit` non-empty lines of an already-complete captured stream. */
export function tailLines(text: string, limit: number): string[] {
  return text.trim().split("\n").filter(Boolean).slice(-limit);
}

/**
 * Failures go to `console.error` so they land at error level: that is what
 * Observability filters and alert rules key off, and a failed build logged at
 * info level is invisible to both.
 */
export function logEvent(
  level: "info" | "error",
  payload: Record<string, unknown>
): void {
  const line = JSON.stringify({ scope: LOG_SCOPE, ...payload });
  if (level === "error") {
    // oxlint-disable-next-line no-console -- the only build record that outlives the sandbox
    console.error(line);
    return;
  }
  // oxlint-disable-next-line no-console -- the only build record that outlives the sandbox
  console.log(line);
}

export interface LineReader {
  /** Feed a chunk; returns only the lines that chunk completed. */
  feed: (chunk: string) => string[];
  /** The trailing line, for a stream that ended without a final newline. */
  flush: () => string[];
}

/**
 * Reassembles lines from a chunked stream.
 *
 * The Sandbox log stream yields arbitrary chunks, not lines: a single stderr
 * traceback line can arrive split across two chunks, and one chunk can carry
 * several NDJSON events. Both the stdout (events) and stderr (diagnostics)
 * readers need the same reassembly, so they share this.
 */
export function createLineReader(): LineReader {
  let partial = "";
  return {
    feed(chunk) {
      partial += chunk;
      const lines = partial.split("\n");
      // The final element is the still-incomplete line (empty when the chunk
      // ended exactly on a newline); hold it back until its newline arrives.
      partial = lines.pop() ?? "";
      return lines.map((line) => line.trim()).filter(Boolean);
    },
    flush() {
      const rest = partial.trim();
      partial = "";
      return rest ? [rest] : [];
    },
  };
}

export interface Tail {
  add: (lines: string[]) => void;
  toArray: () => string[];
}

/**
 * The last `limit` lines pushed through it, each capped in length. The engine's
 * real diagnostics (fontmake tracebacks, interpolation warnings) only ever
 * appear on the sandbox's stderr, and the tail is the part that explains the
 * failure.
 */
export function createTail(limit: number): Tail {
  const kept: string[] = [];
  return {
    add(lines) {
      for (const line of lines) {
        kept.push(truncate(line));
      }
      if (kept.length > limit) {
        kept.splice(0, kept.length - limit);
      }
    },
    toArray: () => [...kept],
  };
}

export interface StageTiming {
  id: string;
  status: string;
  ms: number;
}

export interface StageTimeline {
  record: (id: string, status: "running" | "succeeded" | "failed") => void;
  timings: () => StageTiming[];
  /**
   * The stage that started and never reported back. On a timeout this is the
   * thing to actually go and profile.
   */
  stalled: () => string | undefined;
}

/**
 * Turns the `stage` events the runner already emits into a timeline. This is
 * what upgrades "it timed out" into "it timed out in `build`, after spending
 * 40s in `normalize`".
 */
export function createStageTimeline(): StageTimeline {
  const startedAt = new Map<string, number>();
  const finished: StageTiming[] = [];
  return {
    record(id, status) {
      if (status === "running") {
        startedAt.set(id, Date.now());
        return;
      }
      const from = startedAt.get(id);
      finished.push({
        id,
        status,
        ms: from === undefined ? 0 : Date.now() - from,
      });
    },
    timings: () => [...finished],
    stalled() {
      const done = new Set(finished.map((stage) => stage.id));
      return [...startedAt.keys()].find((id) => !done.has(id));
    },
  };
}
