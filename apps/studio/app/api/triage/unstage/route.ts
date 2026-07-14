import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { keyOf, readPending, writePending } from "@/lib/pending.server";

interface UnstageBody {
  family: "roman" | "italic";
  glyph: string;
}

export async function POST(req: NextRequest) {
  const raw = (await req.json().catch(() => null)) as UnstageBody | null;
  if (
    !raw ||
    (raw.family !== "roman" && raw.family !== "italic") ||
    typeof raw.glyph !== "string"
  ) {
    return NextResponse.json({ error: "invalid body" }, { status: 400 });
  }
  const pending = await readPending();
  const target = keyOf(raw);
  const next = pending.filter((e) => keyOf(e) !== target);
  await writePending(next);
  return NextResponse.json({ count: next.length, ok: true });
}
