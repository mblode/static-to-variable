import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import {
  createGenerationJob,
  listGenerationJobs,
  MAX_GENERATION_UPLOAD_BYTES,
  startGenerationJob,
} from "@/lib/generation.server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const jobs = await listGenerationJobs();
  return NextResponse.json({ jobs });
}

export async function POST(req: NextRequest) {
  const contentLength = Number(req.headers.get("content-length") ?? 0);
  if (contentLength > MAX_GENERATION_UPLOAD_BYTES) {
    return NextResponse.json(
      { error: "upload payload too large" },
      { status: 413 }
    );
  }

  const form = await req.formData().catch(() => null);
  if (!form) {
    return NextResponse.json(
      { error: "invalid multipart form" },
      { status: 400 }
    );
  }

  const useWorkspaceSources = form.get("useWorkspaceSources") !== "false";
  const files = form
    .getAll("files")
    .filter((value): value is File => value instanceof File && value.size > 0);

  try {
    const job = await createGenerationJob({ files, useWorkspaceSources });
    await startGenerationJob(job.id);
    return NextResponse.json({ job }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const status = message.includes("already")
      ? 409
      : message.includes("too large")
        ? 413
        : 400;
    return NextResponse.json({ error: message }, { status });
  }
}
