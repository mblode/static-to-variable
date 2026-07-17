// Browser helper: POST the dropped fonts to the build API and dispatch the
// streamed SSE progress to typed handlers. Returns a function that aborts the
// in-flight build. Runs in the browser only (uses fetch/atob/URL/FormData).

export interface BuildStageInfo {
  id: string;
  title: string;
}
export interface DetectedFontInfo {
  id: string;
  name: string;
  weight: number;
}
export interface DetectedPayload {
  fonts: DetectedFontInfo[];
  axis: { tag: string; min: number; def: number; max: number };
}
export interface StageProgress {
  id: string;
  status: "running" | "succeeded" | "failed";
}
export interface BuiltFile {
  name: string;
  format: string;
  bytes: number;
  /** Object URL for the decoded artifact; revoke it when done. */
  url: string;
  blob: Blob;
}
export interface BuildResultPayload {
  files: BuiltFile[];
  frozen: string[];
}
export interface BuildErrorPayload {
  code: string;
  message: string;
}

export interface BuildHandlers {
  onStages: (stages: BuildStageInfo[]) => void;
  onDetected: (detected: DetectedPayload) => void;
  onStage: (stage: StageProgress) => void;
  onResult: (result: BuildResultPayload) => void;
  onError: (error: BuildErrorPayload) => void;
}

// --- Raw SSE event shapes (as emitted by the route) ------------------------
interface StagesEvent {
  type: "stages";
  stages: BuildStageInfo[];
}
interface DetectedEvent extends DetectedPayload {
  type: "detected";
}
interface StageEvent extends StageProgress {
  type: "stage";
}
interface ResultEvent {
  type: "result";
  files: { name: string; format: string; bytes: number; dataBase64: string }[];
  frozen: string[];
}
interface ErrorEvent {
  type: "error";
  code: string;
  message: string;
}

const MIME_BY_FORMAT: Record<string, string> = {
  ttf: "font/ttf",
  otf: "font/otf",
  woff: "font/woff",
  woff2: "font/woff2",
};

function base64ToBuffer(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const buffer = new ArrayBuffer(binary.length);
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.codePointAt(i) ?? 0;
  }
  return buffer;
}

function toResult(event: ResultEvent): BuildResultPayload {
  const files = event.files.map((file) => {
    const blob = new Blob([base64ToBuffer(file.dataBase64)], {
      type: MIME_BY_FORMAT[file.format] ?? "application/octet-stream",
    });
    return {
      name: file.name,
      format: file.format,
      bytes: file.bytes,
      url: URL.createObjectURL(blob),
      blob,
    };
  });
  return { files, frozen: event.frozen };
}

function dispatch(event: unknown, handlers: BuildHandlers): void {
  if (typeof event !== "object" || event === null || !("type" in event)) {
    return;
  }
  const { type } = event as { type: unknown };
  switch (type) {
    case "stages": {
      handlers.onStages((event as StagesEvent).stages);
      break;
    }
    case "detected": {
      const detected = event as DetectedEvent;
      handlers.onDetected({ fonts: detected.fonts, axis: detected.axis });
      break;
    }
    case "stage": {
      const stage = event as StageEvent;
      handlers.onStage({ id: stage.id, status: stage.status });
      break;
    }
    case "result": {
      handlers.onResult(toResult(event as ResultEvent));
      break;
    }
    case "error": {
      const error = event as ErrorEvent;
      handlers.onError({ code: error.code, message: error.message });
      break;
    }
    default: {
      break;
    }
  }
}

// Parse the `data:` lines out of one SSE record and dispatch each event.
function handleRecord(record: string, handlers: BuildHandlers): void {
  for (const line of record.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) {
      continue;
    }
    const json = trimmed.slice("data:".length).trim();
    if (!json) {
      continue;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(json);
    } catch {
      continue;
    }
    dispatch(parsed, handlers);
  }
}

async function run(
  files: File[],
  overrides: Record<string, number>,
  handlers: BuildHandlers,
  signal: AbortSignal
): Promise<void> {
  const url = process.env.NEXT_PUBLIC_BUILD_API_URL ?? "/api/build";
  const body = new FormData();
  for (const file of files) {
    body.append("files", file);
  }
  if (Object.keys(overrides).length > 0) {
    body.append("overrides", JSON.stringify(overrides));
  }

  const response = await fetch(url, { method: "POST", body, signal });

  // Guardrail failures come back as a JSON error, not a stream.
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null);
    const error =
      typeof data === "object" && data !== null && "error" in data
        ? (data as { error: { code?: string; message?: string } }).error
        : null;
    handlers.onError({
      code: error?.code ?? "request_failed",
      message:
        error?.message ?? `The build request failed (${response.status}).`,
    });
    return;
  }
  if (!response.body) {
    handlers.onError({
      code: "no_stream",
      message: "The server returned an empty response.",
    });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let streaming = true;
  while (streaming) {
    const { done, value } = await reader.read();
    if (done) {
      streaming = false;
    }
    if (value) {
      buffer += decoder.decode(value, { stream: true });
      let sep = buffer.indexOf("\n\n");
      while (sep !== -1) {
        handleRecord(buffer.slice(0, sep), handlers);
        buffer = buffer.slice(sep + 2);
        sep = buffer.indexOf("\n\n");
      }
    }
  }
  if (buffer.trim()) {
    handleRecord(buffer, handlers);
  }
}

/**
 * Build a variable font from static weights. Streams progress to `handlers`.
 * `overrides` optionally overrides the detected weight per file, keyed by the
 * file's name (from the editable weight table). Returns an abort function that
 * cancels the in-flight build.
 */
export function buildFont(
  files: File[],
  overrides: Record<string, number> | undefined,
  handlers: BuildHandlers
): () => void {
  const controller = new AbortController();
  run(files, overrides ?? {}, handlers, controller.signal).catch(
    (error: unknown) => {
      if (controller.signal.aborted) {
        return;
      }
      handlers.onError({
        code: "network",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  );
  return () => controller.abort();
}
