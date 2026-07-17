import { Buffer } from "node:buffer";
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { Sandbox } from "@vercel/sandbox";

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

// On Vercel the function's cwd is the app dir (apps/web); the engine + services
// live two levels up. `outputFileTracingIncludes` in next.config must ship
// packages/variable-gen and services/build with this route (owned by task #5).
// STV_REPO_ROOT overrides for local/dev runs.
const REPO_ROOT = process.env.STV_REPO_ROOT ?? join(process.cwd(), "..", "..");

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
          return walk(join(absDir, e.name), rel);
        }
        return Promise.resolve(e.isFile() ? [rel] : []);
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
      join(REPO_ROOT, "packages/variable-gen/src"),
      "packages/variable-gen/src"
    )),
    ...(await walk(join(REPO_ROOT, "services/build"), "services/build")),
  ];
  return Promise.all(
    relPaths.map(async (rel) => {
      const content = await readFile(join(REPO_ROOT, rel));
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
    const uploadName = `${index}-${font.name.replace(/[^\w.\-]+/g, "_")}`;
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
      const send = (payload: ClientEvent): void => {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`));
      };

      const ac = new AbortController();
      const onClientAbort = (): void => ac.abort();
      request.signal.addEventListener("abort", onClientAbort);

      let sandbox: Sandbox | undefined;
      let timer: ReturnType<typeof setTimeout> | undefined;
      let sawTerminal = false;

      try {
        sandbox = await Sandbox.create({
          runtime: "python3.13",
          timeout: SANDBOX_TIMEOUT_MS,
        });
        const sbx = sandbox;

        // writeFiles resolves relative paths under /vercel/sandbox; mkdir the
        // data dir up front since it holds no uploaded file yet.
        await sbx.fs.mkdir(`${JOB_DIR}/uploads`, { recursive: true });
        await sbx.writeFiles(engineFiles);
        await sbx.writeFiles(jobFiles);

        const setup = await sbx.runCommand({
          cmd: "bash",
          args: ["services/build/setup.sh", VENV_DIR],
          cwd: SANDBOX_ROOT,
          signal: ac.signal,
        });
        if (setup.exitCode !== 0) {
          const tail = (await setup.stderr())
            .trim()
            .split("\n")
            .slice(-4)
            .join(" ");
          send({
            type: "error",
            code: "setup_failed",
            message: `Engine setup failed. ${tail}`.trim(),
          });
          sawTerminal = true;
          return;
        }
        const fontmake =
          parseFontmake(await setup.stdout()) ?? `${VENV_DIR}/bin/fontmake`;
        const python = fontmake.replace(/fontmake$/, "python");

        // The wall-clock guard covers the build itself; abort kills the stream
        // and the finally disposes the sandbox (stopping the process).
        timer = setTimeout(() => ac.abort(), BUILD_TIMEOUT_MS);

        const build = await sbx.runCommand({
          cmd: python,
          args: ["services/build/build_job.py", JOB_DIR],
          cwd: SANDBOX_ROOT,
          env: { STV_FONTMAKE: fontmake },
          detached: true,
        });

        const flush = async (line: string): Promise<void> => {
          const event = parseEvent(line);
          if (!event) {
            return;
          }
          if (event.type === "result") {
            send(await materializeResult(sbx, event, ac.signal));
            sawTerminal = true;
          } else {
            if (event.type === "error") {
              sawTerminal = true;
            }
            send(event);
          }
        };

        let buffer = "";
        for await (const log of build.logs({ signal: ac.signal })) {
          if (log.stream !== "stdout") {
            continue;
          }
          buffer += log.data;
          while (buffer.includes("\n")) {
            const idx = buffer.indexOf("\n");
            const line = buffer.slice(0, idx).trim();
            buffer = buffer.slice(idx + 1);
            if (line) {
              await flush(line);
            }
          }
        }
        if (buffer.trim()) {
          await flush(buffer.trim());
        }

        const finished = await build.wait();
        if (finished.exitCode !== 0 && !sawTerminal) {
          send({
            type: "error",
            code: "build_failed",
            message: "The build exited without producing a font.",
          });
          sawTerminal = true;
        }
      } catch (err) {
        const message = ac.signal.aborted
          ? "The build took too long and was stopped."
          : errMessage(err);
        send({
          type: "error",
          code: ac.signal.aborted ? "timeout" : "sandbox_failed",
          message,
        });
      } finally {
        if (timer) {
          clearTimeout(timer);
        }
        request.signal.removeEventListener("abort", onClientAbort);
        if (sandbox) {
          try {
            await sandbox.stop();
          } catch {
            // Already stopping / gone — nothing to clean up.
          }
        }
        controller.close();
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
