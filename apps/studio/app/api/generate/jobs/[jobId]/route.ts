import { NextResponse } from "next/server";

import { readGenerationJob } from "@/lib/generation.server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  try {
    const { jobId } = await params;
    const job = await readGenerationJob(jobId);
    return NextResponse.json({ job });
  } catch {
    return NextResponse.json({ error: "job not found" }, { status: 404 });
  }
}
