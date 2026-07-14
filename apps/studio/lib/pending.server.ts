import "server-only";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import type { PendingTriageEdit } from "@static-to-variable/glyph-forge-engine";

const PENDING_PATH = path.resolve(
  process.cwd(),
  "..",
  "..",
  "packages",
  "glyph-forge-engine",
  "manifests",
  "pending-triage-edits.json"
);

export async function readPending(): Promise<PendingTriageEdit[]> {
  try {
    const raw = await readFile(PENDING_PATH, "utf-8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as PendingTriageEdit[]) : [];
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return [];
    }
    throw error;
  }
}

export async function writePending(edits: PendingTriageEdit[]): Promise<void> {
  await mkdir(path.dirname(PENDING_PATH), { recursive: true });
  await writeFile(PENDING_PATH, JSON.stringify(edits, null, 2), "utf-8");
}

export function keyOf(
  edit: Pick<PendingTriageEdit, "family" | "glyph">
): string {
  return `${edit.family}/${edit.glyph}`;
}

export function indexByKey(
  edits: PendingTriageEdit[]
): Map<string, PendingTriageEdit> {
  return new Map(edits.map((e) => [keyOf(e), e]));
}
