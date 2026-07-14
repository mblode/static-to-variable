import { readFile, stat } from "node:fs/promises";

import { NextResponse } from "next/server";

import { resolveArtifactPath } from "@/lib/generation.server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ jobId: string; artifactId: string }> }
) {
  try {
    const { jobId, artifactId } = await params;
    const { artifact, path } = await resolveArtifactPath(jobId, artifactId);
    const fileStat = await stat(path);
    const body = await readFile(path);
    return new NextResponse(body, {
      headers: {
        "Cache-Control": "no-store",
        "Content-Disposition": contentDisposition(artifact.fileName),
        "Content-Length": String(fileStat.size),
        "Content-Type": artifact.contentType,
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return NextResponse.json({ error: "artifact not found" }, { status: 404 });
  }
}

function contentDisposition(fileName: string): string {
  const safeName = fileName.replaceAll(/[^\w. -]/g, "_");
  return `attachment; filename="${safeName}"; filename*=UTF-8''${encodeURIComponent(safeName)}`;
}
