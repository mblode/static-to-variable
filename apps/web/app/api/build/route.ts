import { Buffer } from "node:buffer";
import { randomUUID } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
// Type-only: importing the value at module scope runs @vercel/sandbox's init
// when Next loads this route during the build (to read the route config), which
// crashes Vercel's build worker. The value is imported dynamically in the
// handler instead, so it only loads at request time.
import type { Sandbox } from "@vercel/sandbox";
import type { BuildOutcome, StageTimeline, Tail } from "@/lib/build-log";
import {
  createLineReader,
  createStageTimeline,
  createTail,
  isFailure,
  logEvent,
  STDERR_TAIL_LINES,
  tailLines,
  truncate,
} from "@/lib/build-log";

// The build runs untrusted-ish native tooling (fontmake, skia-pathops) in a
// throwaway Vercel Sandbox, so this route needs the Node runtime and must never
// be statically optimized.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
// Setup (uv venv + native-wheel install) plus the pipeline can approach a few
// minutes; give the function headroom above the in-build wall-clock guard.
export const maxDuration = 300;

// --- Upload guardrails -----------------------------------------------------
const MIN_FILES = 2;
const MAX_FILES = 13;
const MEGABYTE = 1024 * 1024;
const MAX_FILE_BYTES = 5 * MEGABYTE;
const MAX_TOTAL_BYTES = 20 * MEGABYTE;

// --- Sandbox layout / timing ----------------------------------------------
const SANDBOX_ROOT = "/vercel/sandbox";
const JOB_DIR = `${SANDBOX_ROOT}/job`;
const VENV_DIR = `${SANDBOX_ROOT}/.venv`;
// Wall-clock cap on the build_job run itself (setup gets the rest of maxDuration).
const BUILD_TIMEOUT_MS = 180_000;
// Sandbox session lifetime — must outlast setup + build.
const SANDBOX_TIMEOUT_MS = 8 * 60 * 1000;
// maxDuration is a hard kill: if the platform stops the function mid-build the
// finally never runs and this route logs nothing at all, which is the one
// failure mode the instrumentation below cannot see. The build guard is
// therefore capped by whatever remains of the function budget, less a reserve
// for reading artifacts out, stopping the sandbox and writing the summary, so
// the route always aborts itself first and leaves a record.
const FUNCTION_BUDGET_MS = maxDuration * 1000;
const SHUTDOWN_RESERVE_MS = 25_000;

// On Vercel the function's cwd is the app dir (apps/web); the engine + services
// live two levels up. `outputFileTracingIncludes` in next.config must ship
// packages/variable-gen and services/build with this route (owned by task #5).
// STV_REPO_ROOT overrides for local/dev runs.
const REPO_ROOT = process.env.STV_REPO_ROOT ?? path.join(process.cwd(), "..", "..");

const SFNT_MAGIC = new Set(["OTTO", "true"]);

// --- NDJSON event shapes emitted by build_job.py / runner.py ---------------
interface StagesEvent {
  type: "stages";
  stages: { id: string; title: string }[];
}
interface DetectedEvent {
  type: "detected";
  fonts: { id: string; name: string; weight: number }[];
  axis: { tag: string; min: number; def: number; max: number };
}
interface StageEvent {
  type: "stage";
  id: string;
  status: "running" | "succeeded" | "failed";
}
interface RunnerResultEvent {
  type: "result";
  files: { name: string; format: string; bytes: number; path: string }[];
  frozen: string[];
}
interface ErrorEvent {
  type: "error";
  code: string;
  message: string;
}
type BuildEvent =
  | StagesEvent
  | DetectedEvent
  | StageEvent
  | RunnerResultEvent
  | ErrorEvent;

// What the browser receives for a finished build: the same shape as the runner
// result, but each artifact carries its bytes inline as base64.
interface ClientResultEvent {
  type: "result";
  files: { name: string; format: string; bytes: number; dataBase64: string }[];
  frozen: string[];
}
type ClientEvent = Exclude<BuildEvent, RunnerResultEvent> | ClientResultEvent;

interface UploadFile {
  path: string;
  content: Buffer;
  mode?: number;
}

const encoder = new TextEncoder();

function errorJson(code: string, message: string, status: number): Response {
  return Response.json({ error: { code, message } }, { status });
}

function hasFontExtension(name: string): boolean {
  const lower = name.toLowerCase();
  return lower.endsWith(".ttf") || lower.endsWith(".otf");
}

// sfnt magic sniff of the first 4 bytes: 0x00010000 (TrueType), "OTTO" (CFF),
// or "true" (legacy Apple). Rejects WOFF/WOFF2 and non-fonts.
function sniffSfnt(buf: Buffer): boolean {
  if (buf.length < 4) {
    return false;
  }
  if (
    buf[0] === 0x00 &&
    buf[1] === 0x01 &&
    buf[2] === 0x00 &&
    buf[3] === 0x00
  ) {
    return true;
  }
  return SFNT_MAGIC.has(buf.subarray(0, 4).toString("latin1"));
}

// Recursively list repo-relative POSIX paths under an engine directory, skipping
// caches and dotfiles that the sandbox doesn't need.
async function walk(absDir: string, relBase: string): Promise<string[]> {
  const entries = await readdir(absDir, { withFileTypes: true });
  const nested = await Promise.all(
    entries
      .filter((e) => e.name !== "__pycache__" && !e.name.startsWith("."))
      .map((e) => {
        const rel = `${relBase}/${e.name}`;
        if (e.isDirectory()) {
          return walk(path.join(absDir, e.name), rel);
        }
        return e.isFile() ? [rel] : [];
      })
  );
  return nested.flat();
}

// The files the sandbox needs to `uv pip install` the engine and run the job:
// the variable-gen package (pyproject + README + src) and services/build.
async function collectEngineFiles(): Promise<UploadFile[]> {
  const relPaths = [
    "packages/variable-gen/pyproject.toml",
    "packages/variable-gen/README.md",
    ...(await walk(
      path.join(REPO_ROOT, "packages/variable-gen/src"),
      "packages/variable-gen/src"
    )),
    ...(await walk(path.join(REPO_ROOT, "services/build"), "services/build")),
  ];
  return Promise.all(
    relPaths.map(async (rel) => {
      const content = await readFile(path.join(REPO_ROOT, rel));
      return rel.endsWith(".sh")
        ? { path: rel, content, mode: 0o755 }
        : { path: rel, content };
    })
  );
}

// setup.sh prints `export STV_FONTMAKE=<path>` on stdout as its contract.
function parseFontmake(stdout: string): string | null {
  const match = stdout.match(/STV_FONTMAKE=(\S+)/);
  return match ? match[1] : null;
}

function parseEvent(line: string): BuildEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(line);
  } catch {
    return null;
  }
  if (
    typeof parsed === "object" &&
    parsed !== null &&
    "type" in parsed &&
    typeof (parsed as { type: unknown }).type === "string"
  ) {
    return parsed as BuildEvent;
  }
  return null;
}

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// What the user sees on a setup failure; short enough to fit an error banner.
const SETUP_ERROR_LINES = 4;

function elapsed(from: number | undefined): number | undefined {
  return from === undefined ? undefined : Date.now() - from;
}

// Mutable state of one build, collected for the summary log line. Grouped into
// an object so the phase helpers below can record into it without `start`
// having to thread a dozen locals through them.
interface BuildRun {
  outcome: BuildOutcome;
  errorCode?: string;
  detail?: string;
  setupStartedAt?: number;
  buildStartedAt?: number;
  setupMs?: number;
  buildMs?: number;
  guardMs?: number;
  sawTerminal: boolean;
}

// Stopping the sandbox refreshes its session snapshot and returns it, which is
// the only place the final CPU figure is populated: the sandbox getter of the
// same name still reads the pre-stop snapshot. Failure here is uninteresting,
// the microVM is already going away either way.
async function stopSandbox(sandbox: Sandbox): Promise<number | undefined> {
  try {
    const stopped = await sandbox.stop();
    return stopped.activeCpuDurationMs;
  } catch {
    return undefined;
  }
}

// One line per build. This is the only record that survives the microVM, so it
// carries enough to separate a slow provision from a slow fontmake run from a
// stage that never came back.
function logFinished(summary: {
  run: BuildRun;
  stages: StageTimeline;
  stderrTail: Tail;
  requestId: string;
  requestStartedAt: number;
  sandbox: Sandbox | undefined;
  activeCpuMs: number | undefined;
  uploads: number;
  uploadBytes: number;
}): void {
  const { run } = summary;
  logEvent(isFailure(run.outcome) ? "error" : "info", {
    event: "finished",
    requestId: summary.requestId,
    sandbox: summary.sandbox?.name,
    outcome: run.outcome,
    errorCode: run.errorCode,
    detail: run.detail,
    totalMs: elapsed(summary.requestStartedAt),
    setupMs: run.setupMs,
    buildMs: run.buildMs,
    guardMs: run.guardMs,
    stages: summary.stages.timings(),
    stalledStage: summary.stages.stalled(),
    uploads: summary.uploads,
    uploadBytes: summary.uploadBytes,
    activeCpuMs: summary.activeCpuMs,
    stderrTail: summary.stderrTail.toArray(),
  });
}

// Everything one NDJSON event from the engine may need to act on.
interface EventPump {
  run: BuildRun;
  stages: StageTimeline;
  sandbox: Sandbox;
  requestId: string;
  signal: AbortSignal;
  send: (payload: ClientEvent) => void;
  clearGuard: () => void;
}

// Forwards one engine event to the browser and records what it means for the
// summary line. Lives outside the stream handler so the orchestration in `POST`
// stays readable.
async function handleEvent(
  event: BuildEvent,
  pump: EventPump
): Promise<void> {
  const { run, send } = pump;
  if (event.type === "stage") {
    pump.stages.record(event.id, event.status);
  }
  // The detected weights and axis span are what you need to reproduce a failing
  // build locally; they never leave the browser otherwise.
  if (event.type === "detected") {
    logEvent("info", {
      event: "detected",
      requestId: pump.requestId,
      sandbox: pump.sandbox.name,
      weights: event.fonts.map((font) => font.weight),
      axis: event.axis,
    });
  }
  if (event.type === "result") {
    // The build itself is done, so stop the wall-clock guard before reading
    // artifacts out. Otherwise a build that finishes just under the guard is
    // aborted mid-base64 and reported to the user as a timeout.
    pump.clearGuard();
    run.buildMs = elapsed(run.buildStartedAt);
    send(await materializeResult(pump.sandbox, event, pump.signal));
    run.outcome = "succeeded";
    run.sawTerminal = true;
    return;
  }
  if (event.type === "error") {
    // One stable outcome for dashboards; the engine's own code stays as an
    // attribute so it can still be grouped on when needed.
    run.outcome = "engine_error";
    run.errorCode = event.code;
    run.detail = truncate(event.message);
    run.sawTerminal = true;
  }
  send(event);
}

// Why the run unwound. `clientClosed` and `timedOut` both abort the same
// signal, and telling them apart is the difference between "the build is too
// slow" and "the user closed the tab".
function recordAbort(
  run: BuildRun,
  ctx: {
    error: unknown;
    clientClosed: boolean;
    timedOut: boolean;
    send: (payload: ClientEvent) => void;
  }
): void {
  run.sawTerminal = true;
  if (ctx.clientClosed) {
    // The user left. Not a defect, and `send` is a no-op by now anyway.
    run.outcome = "client_closed";
    return;
  }
  if (ctx.timedOut) {
    run.outcome = "timeout";
    ctx.send({
      type: "error",
      code: "timeout",
      message: "The build took too long and was stopped.",
    });
    return;
  }
  run.outcome = "sandbox_failed";
  run.detail = truncate(errMessage(ctx.error));
  ctx.send({
    type: "error",
    code: "sandbox_failed",
    message: errMessage(ctx.error),
  });
}

// Weight overrides from the editable weight table, sent as a JSON object keyed
// by original filename. Silently drops anything that isn't a finite number.
function parseOverrides(raw: FormDataEntryValue | null): Record<string, number> {
  if (typeof raw !== "string" || !raw) {
    return {};
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return {};
  }
  if (typeof parsed !== "object" || parsed === null) {
    return {};
  }
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(parsed)) {
    if (typeof value === "number" && Number.isFinite(value)) {
      out[key] = value;
    }
  }
  return out;
}

// Read each produced artifact out of the sandbox and inline it as base64.
async function materializeResult(
  sandbox: Sandbox,
  event: RunnerResultEvent,
  signal: AbortSignal
): Promise<ClientResultEvent> {
  const files = await Promise.all(
    event.files.map(async (file) => {
      const buffer = await sandbox.readFileToBuffer({ path: file.path }, { signal });
      return {
        name: file.name,
        format: file.format,
        bytes: file.bytes,
        dataBase64: buffer ? buffer.toString("base64") : "",
      };
    })
  );
  return { type: "result", files, frozen: event.frozen };
}

export async function POST(request: Request): Promise<Response> {
  // Measured from the true start of the invocation, not from when the stream
  // opens: parsing up to 20 MB of multipart body is already on the clock, and
  // the build guard below is derived from what is left of it.
  const requestStartedAt = Date.now();
  // Vercel's own request id, so a log line joins to the platform's record of
  // the same request rather than to an id only this route knows.
  const requestId = request.headers.get("x-vercel-id") ?? randomUUID();

  const form = await request.formData();
  const files = form
    .getAll("files")
    .filter((entry): entry is File => entry instanceof File);

  if (files.length < MIN_FILES) {
    return errorJson(
      "too_few_files",
      `Upload at least ${MIN_FILES} static weights to build a variable font.`,
      400
    );
  }
  if (files.length > MAX_FILES) {
    return errorJson(
      "too_many_files",
      `Upload at most ${MAX_FILES} static weights.`,
      400
    );
  }

  const loaded = await Promise.all(
    files.map(async (file) => ({
      name: file.name,
      content: Buffer.from(await file.arrayBuffer()),
    }))
  );

  let total = 0;
  for (const font of loaded) {
    if (font.content.byteLength > MAX_FILE_BYTES) {
      return errorJson(
        "file_too_large",
        `${font.name} is larger than ${MAX_FILE_BYTES / MEGABYTE} MB.`,
        413
      );
    }
    total += font.content.byteLength;
    if (!(hasFontExtension(font.name) && sniffSfnt(font.content))) {
      return errorJson(
        "unsupported_type",
        `${font.name} is not a TTF or OTF font.`,
        415
      );
    }
  }
  if (total > MAX_TOTAL_BYTES) {
    return errorJson(
      "file_too_large",
      `The fonts total more than ${MAX_TOTAL_BYTES / MEGABYTE} MB.`,
      413
    );
  }

  const engineFiles = await collectEngineFiles();
  // Rename uploads to `<index>-<safe>` (dedupes names, blocks path traversal),
  // and re-key the weight overrides (sent keyed by original filename) onto those
  // sandbox filenames so build_job maps them back by upload path.name.
  const overridesByName = parseOverrides(form.get("overrides"));
  const sandboxOverrides: Record<string, number> = {};
  const fontFiles: UploadFile[] = loaded.map((font, index) => {
    const uploadName = `${index}-${font.name.replaceAll(/[^\w.-]+/g, "_")}`;
    const override = overridesByName[font.name];
    if (typeof override === "number") {
      sandboxOverrides[uploadName] = override;
    }
    return { path: `job/uploads/${uploadName}`, content: font.content };
  });
  const jobFiles: UploadFile[] =
    Object.keys(sandboxOverrides).length > 0
      ? [
          ...fontFiles,
          {
            path: "job/overrides.json",
            content: Buffer.from(JSON.stringify(sandboxOverrides)),
          },
        ]
      : fontFiles;

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      // Writing to a controller whose client has gone throws. That must not
      // escape: `send` is called from the catch block, where a throw would
      // replace the real failure with a stream error and skip the summary log.
      let streamOpen = true;
      const send = (payload: ClientEvent): void => {
        if (!streamOpen) {
          return;
        }
        try {
          controller.enqueue(
            encoder.encode(`data: ${JSON.stringify(payload)}\n\n`)
          );
        } catch {
          streamOpen = false;
        }
      };

      const stages = createStageTimeline();
      // The engine's real diagnostics (fontmake tracebacks, interpolation
      // warnings) only ever appear on the sandbox's stderr, which this route
      // used to drop on the floor.
      const stderrTail = createTail(STDERR_TAIL_LINES);
      // `*StartedAt` are recorded before each phase so the finally can still
      // report a duration for a run aborted mid-phase, which is exactly the run
      // whose timings matter.
      const run: BuildRun = { outcome: "unknown", sawTerminal: false };

      const ac = new AbortController();
      // Distinguish the two things that abort `ac`. Both used to surface to the
      // user as "the build took too long", so closing the tab was indexed as a
      // timeout and a genuine timeout was indistinguishable from a disconnect.
      let timedOut = false;
      let clientClosed = false;
      const onClientAbort = (): void => {
        clientClosed = true;
        ac.abort();
      };
      request.signal.addEventListener("abort", onClientAbort);

      let sandbox: Sandbox | undefined;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const clearGuard = (): void => {
        if (timer) {
          clearTimeout(timer);
          timer = undefined;
        }
      };

      // Emitted before anything that can hang, so that even a run the platform
      // hard-kills leaves a trace with the inputs that caused it.
      logEvent("info", {
        event: "started",
        requestId,
        uploads: loaded.length,
        uploadBytes: total,
      });

      try {
        const { Sandbox } = await import("@vercel/sandbox");
        const createStartedAt = Date.now();
        sandbox = await Sandbox.create({
          runtime: "python3.13",
          timeout: SANDBOX_TIMEOUT_MS,
        });
        const sbx = sandbox;
        logEvent("info", {
          event: "sandbox_created",
          requestId,
          sandbox: sbx.name,
          ms: elapsed(createStartedAt),
        });

        // writeFiles resolves relative paths under /vercel/sandbox; mkdir the
        // data dir up front since it holds no uploaded file yet.
        await sbx.fs.mkdir(`${JOB_DIR}/uploads`, { recursive: true });
        await sbx.writeFiles(engineFiles);
        await sbx.writeFiles(jobFiles);

        // setup.sh reinstalls the whole native wheel set (fontmake, numpy,
        // scipy, skia-pathops) into a cold microVM on every request. Timing it
        // separately is what tells you whether a slow build is provisioning or
        // the pipeline, and it is charged against maxDuration before the
        // BUILD_TIMEOUT_MS guard below even starts.
        run.setupStartedAt = Date.now();
        const setup = await sbx.runCommand({
          cmd: "bash",
          args: ["services/build/setup.sh", VENV_DIR],
          cwd: SANDBOX_ROOT,
          signal: ac.signal,
        });
        run.setupMs = elapsed(run.setupStartedAt);
        const setupErr = await setup.stderr();
        logEvent("info", {
          event: "setup_finished",
          requestId,
          sandbox: sbx.name,
          ms: run.setupMs,
          exitCode: setup.exitCode,
        });
        if (setup.exitCode !== 0) {
          run.outcome = "setup_failed";
          run.detail = truncate(
            tailLines(setupErr, STDERR_TAIL_LINES).join(" | ")
          );
          send({
            type: "error",
            code: "setup_failed",
            message:
              `Engine setup failed. ${tailLines(setupErr, SETUP_ERROR_LINES).join(" ")}`.trim(),
          });
          run.sawTerminal = true;
          return;
        }
        const fontmake =
          parseFontmake(await setup.stdout()) ?? `${VENV_DIR}/bin/fontmake`;
        const python = fontmake.replace(/fontmake$/, "python");

        // The wall-clock guard covers the build itself; abort kills the stream
        // and the finally disposes the sandbox (stopping the process). Capped
        // by what is left of the function budget so a slow setup shortens the
        // build rather than pushing the whole invocation past maxDuration,
        // where it would be killed without logging anything.
        const budgetLeft =
          requestStartedAt + FUNCTION_BUDGET_MS - SHUTDOWN_RESERVE_MS -
          Date.now();
        run.guardMs = Math.max(0, Math.min(BUILD_TIMEOUT_MS, budgetLeft));
        timer = setTimeout(() => {
          timedOut = true;
          ac.abort();
        }, run.guardMs);

        run.buildStartedAt = Date.now();
        const build = await sbx.runCommand({
          cmd: python,
          args: ["services/build/build_job.py", JOB_DIR],
          cwd: SANDBOX_ROOT,
          env: { STV_FONTMAKE: fontmake },
          detached: true,
        });

        const pump: EventPump = {
          run,
          stages,
          sandbox: sbx,
          requestId,
          signal: ac.signal,
          send,
          clearGuard,
        };
        const onLine = async (line: string): Promise<void> => {
          const event = parseEvent(line);
          if (event) {
            await handleEvent(event, pump);
          }
        };

        // Both streams arrive as arbitrary chunks, so both need reassembly: a
        // traceback line can straddle two chunks and one chunk can carry
        // several NDJSON events.
        const stdout = createLineReader();
        const stderr = createLineReader();
        for await (const log of build.logs({ signal: ac.signal })) {
          if (log.stream === "stdout") {
            for (const line of stdout.feed(log.data)) {
              await onLine(line);
            }
          } else {
            stderrTail.add(stderr.feed(log.data));
          }
        }
        for (const line of stdout.flush()) {
          await onLine(line);
        }
        stderrTail.add(stderr.flush());

        const finished = await build.wait();
        run.buildMs ??= elapsed(run.buildStartedAt);
        if (finished.exitCode !== 0 && !run.sawTerminal) {
          run.outcome = "build_failed";
          run.detail = `exit ${finished.exitCode}`;
          send({
            type: "error",
            code: "build_failed",
            message: "The build exited without producing a font.",
          });
          run.sawTerminal = true;
        }
      } catch (error) {
        recordAbort(run, { error, clientClosed, timedOut, send });
      } finally {
        clearGuard();
        request.signal.removeEventListener("abort", onClientAbort);

        // A run aborted mid-phase never reached its own timing line, so fill in
        // whatever elapsed before the abort.
        run.setupMs ??= elapsed(run.setupStartedAt);
        run.buildMs ??= elapsed(run.buildStartedAt);

        const activeCpuMs = sandbox ? await stopSandbox(sandbox) : undefined;
        logFinished({
          run,
          stages,
          stderrTail,
          requestId,
          requestStartedAt,
          sandbox,
          activeCpuMs,
          uploads: loaded.length,
          uploadBytes: total,
        });

        if (streamOpen) {
          try {
            controller.close();
          } catch {
            // Client already gone; the stream is closed from the other end.
          }
        }
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
