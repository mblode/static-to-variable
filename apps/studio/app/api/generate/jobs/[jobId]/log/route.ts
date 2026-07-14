import { NextResponse } from "next/server";

import { readGenerationLog } from "@/lib/generation.server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  try {
    const { jobId } = await params;
    const log = await readGenerationLog(jobId);
    return new NextResponse(log, {
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": "text/plain; charset=utf-8",
      },
    });
  } catch {
    return NextResponse.json({ error: "job not found" }, { status: 404 });
  }
}
