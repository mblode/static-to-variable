import { NextResponse } from "next/server";

import { readPending } from "@/lib/pending.server";

export async function GET() {
  const pending = await readPending();
  return NextResponse.json({ count: pending.length, edits: pending });
}
