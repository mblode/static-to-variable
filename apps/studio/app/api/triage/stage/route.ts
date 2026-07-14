import { STRATEGY_NAMES } from "@static-to-variable/glyph-forge-engine";
import type {
  PendingManifestPatch,
  PendingTriageEdit,
  StrategyName,
} from "@static-to-variable/glyph-forge-engine";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { loadManifest } from "@/lib/data.server";
import {
  indexByKey,
  keyOf,
  readPending,
  writePending,
} from "@/lib/pending.server";

interface StageBody {
  family: "roman" | "italic";
  glyph: string;
  strategy: StrategyName;
  source: "suggestion" | "manual";
  notes?: string;
  manifestPatch?: PendingManifestPatch;
}

function isValidBody(x: unknown): x is StageBody {
  if (!x || typeof x !== "object") {
    return false;
  }
  const b = x as Record<string, unknown>;
  return (
    (b.family === "roman" || b.family === "italic") &&
    typeof b.glyph === "string" &&
    b.glyph.length > 0 &&
    typeof b.strategy === "string" &&
    (STRATEGY_NAMES as readonly string[]).includes(b.strategy) &&
    (b.source === "suggestion" || b.source === "manual") &&
    (b.notes === undefined || typeof b.notes === "string") &&
    isValidManifestPatch(b.manifestPatch)
  );
}

function isValidManifestPatch(
  x: unknown
): x is PendingManifestPatch | undefined {
  if (x === undefined) {
    return true;
  }
  if (!x || typeof x !== "object" || Array.isArray(x)) {
    return false;
  }

  const allowedKeys = new Set([
    "repair_bucket",
    "base_glyph",
    "brace_weights",
    "priority",
    "deferred",
    "defer_reason",
  ]);
  const patch = x as Record<string, unknown>;
  for (const key of Object.keys(patch)) {
    if (!allowedKeys.has(key)) {
      return false;
    }
  }

  return (
    optionalString(patch.repair_bucket) &&
    optionalString(patch.base_glyph) &&
    optionalString(patch.priority) &&
    optionalString(patch.defer_reason) &&
    (patch.deferred === undefined || typeof patch.deferred === "boolean") &&
    (patch.brace_weights === undefined ||
      (Array.isArray(patch.brace_weights) &&
        patch.brace_weights.every(
          (value) => typeof value === "number" && Number.isFinite(value)
        )))
  );
}

function optionalString(x: unknown): boolean {
  return x === undefined || typeof x === "string";
}

export async function POST(req: NextRequest) {
  const raw = await req.json().catch(() => null);
  if (!isValidBody(raw)) {
    return NextResponse.json({ error: "invalid body" }, { status: 400 });
  }

  const manifest = await loadManifest();
  const entry = manifest.find(
    (g) => g.family === raw.family && g.name === raw.glyph
  );
  if (!entry) {
    return NextResponse.json(
      { error: "glyph not in manifest" },
      { status: 404 }
    );
  }

  const pending = await readPending();
  const byKey = indexByKey(pending);
  const edit: PendingTriageEdit = {
    family: raw.family,
    glyph: raw.glyph,
    manifestPatch: raw.manifestPatch,
    notes: raw.notes,
    previousStrategy: entry.existingStrategy ?? null,
    source: raw.source,
    stagedAt: new Date().toISOString(),
    strategy: raw.strategy,
  };
  byKey.set(keyOf(edit), edit);
  const next = [...byKey.values()].toSorted((a, b) =>
    keyOf(a).localeCompare(keyOf(b))
  );
  await writePending(next);
  return NextResponse.json({ count: next.length, edit, ok: true });
}
