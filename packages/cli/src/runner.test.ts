import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { beforeEach, expect, test, vi } from "vitest";

import { spawnInherit } from "./proc.js";
import type { HandoffTarget } from "./runner.js";
import {
  compareHandoffTargets,
  findWorkspaceRoot,
  formatDuration,
  loadHandoffTargets,
  readPipelineStatus,
  runStage,
  runStages,
  verdictRank,
} from "./runner.js";
import { resolveStage } from "./stages.js";

vi.mock("./proc.js", () => ({
  spawnInherit: vi.fn(() => Promise.resolve(0)),
}));

const mockedSpawn = vi.mocked(spawnInherit);

beforeEach(() => {
  mockedSpawn.mockClear();
  mockedSpawn.mockResolvedValue(0);
});

/** A throwaway directory tree that looks like a static-to-variable checkout. */
function tempWorkspace(): string {
  const root = mkdtempSync(path.join(tmpdir(), "stv-workspace-"));
  writeFileSync(
    path.join(root, "package.json"),
    JSON.stringify({ name: "static-to-variable-monorepo", workspaces: [] })
  );
  return root;
}

function writeJson(root: string, relative: string, value: unknown): void {
  const file = path.join(root, relative);
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(value));
}

test("findWorkspaceRoot walks up to the monorepo package.json", () => {
  const root = tempWorkspace();
  const nested = path.join(root, "packages/cli/src");
  mkdirSync(nested, { recursive: true });
  expect(findWorkspaceRoot(nested)).toBe(root);
});

test("findWorkspaceRoot returns null outside a checkout", () => {
  const stray = mkdtempSync(path.join(tmpdir(), "stv-stray-"));
  expect(findWorkspaceRoot(stray)).toBeNull();
});

test("findWorkspaceRoot ignores unrelated package.json files", () => {
  const stray = mkdtempSync(path.join(tmpdir(), "stv-other-"));
  writeFileSync(
    path.join(stray, "package.json"),
    JSON.stringify({ name: "something-else", workspaces: [] })
  );
  expect(findWorkspaceRoot(stray)).toBeNull();
});

test("readPipelineStatus loads the report from the workspace", () => {
  const root = tempWorkspace();
  writeJson(root, "packages/variable-gen/reports/pipeline-status.json", {
    stages: [],
    verdict: "pass",
  });
  expect(readPipelineStatus(root).verdict).toBe("pass");
});

test("readPipelineStatus throws STV_STATUS_REPORT_MISSING when absent", () => {
  const root = tempWorkspace();
  expect(() => readPipelineStatus(root)).toThrow(/status report is missing/i);
  try {
    readPipelineStatus(root);
  } catch (error) {
    expect(error).toMatchObject({ code: "STV_STATUS_REPORT_MISSING" });
  }
});

test("runStage resolves with the child exit code", async () => {
  mockedSpawn.mockResolvedValueOnce(3);
  const result = await runStage(resolveStage("inventory"), {}, "/tmp");
  expect(result.code).toBe(3);
  expect(result.stage.id).toBe("inventory");
  expect(mockedSpawn).toHaveBeenCalledWith(
    "npm",
    ["--workspace", "@static-to-variable/variable-gen", "run", "inventory"],
    "/tmp"
  );
});

test("runStage uses npm.cmd on Windows", async () => {
  const original = process.platform;
  Object.defineProperty(process, "platform", { value: "win32" });
  try {
    await runStage(resolveStage("inventory"), {}, "/tmp");
  } finally {
    Object.defineProperty(process, "platform", { value: original });
  }
  expect(mockedSpawn).toHaveBeenCalledWith(
    "npm.cmd",
    expect.arrayContaining(["run", "inventory"]),
    "/tmp"
  );
});

test("runStage --dry-run never spawns", async () => {
  const result = await runStage(
    resolveStage("inventory"),
    { dryRun: true },
    "/tmp"
  );
  expect(result.code).toBe(0);
  expect(mockedSpawn).not.toHaveBeenCalled();
});

test("runStages stops at the first failure unless continueOnFail", async () => {
  const stages = [resolveStage("inventory"), resolveStage("status")];
  mockedSpawn.mockResolvedValueOnce(1);
  const stopped = await runStages(stages, {}, "/tmp");
  expect(stopped.map((result) => result.code)).toEqual([1]);

  mockedSpawn.mockResolvedValueOnce(1);
  const all = await runStages(stages, { continueOnFail: true }, "/tmp");
  expect(all.map((result) => result.code)).toEqual([1, 0]);
});

test("verdictRank orders blocker < unknown < high < everything else", () => {
  const ranks = ["blocker", "unknown", "high", "medium"].map(verdictRank);
  expect(ranks).toEqual([0, 1, 2, 3]);
});

function target(overrides: Partial<HandoffTarget>): HandoffTarget {
  return {
    best: null,
    family: "roman",
    gain: null,
    name: "a",
    verdict: "high",
    worstComposite: null,
    worstWght: null,
    ...overrides,
  };
}

test("compareHandoffTargets sorts by verdict, then worst score, then gain", () => {
  const sorted = [
    target({ name: "high-good", verdict: "high", worstComposite: 0.9 }),
    target({
      gain: 0.1,
      name: "blocker-lowgain",
      verdict: "blocker",
      worstComposite: 0.5,
    }),
    target({ name: "blocker-bad", verdict: "blocker", worstComposite: 0.2 }),
    target({
      gain: 0.4,
      name: "blocker-highgain",
      verdict: "blocker",
      worstComposite: 0.5,
    }),
    target({ name: "blocker-null-worst", verdict: "blocker" }),
    target({ name: "unknown-mid", verdict: "unknown", worstComposite: 0.1 }),
  ].toSorted(compareHandoffTargets);

  expect(sorted.map((entry) => entry.name)).toEqual([
    // blockers first, lowest worstComposite first, higher gain breaks ties
    "blocker-bad",
    "blocker-highgain",
    "blocker-lowgain",
    // null worstComposite sorts after real scores within a verdict
    "blocker-null-worst",
    "unknown-mid",
    "high-good",
  ]);
});

test("loadHandoffTargets filters, joins, and limits the manifests", () => {
  const root = tempWorkspace();
  writeJson(root, "packages/glyph-forge-engine/manifests/broken-glyphs.json", [
    { auditVerdict: "blocker", family: "roman", name: "dollar" },
    { auditVerdict: "high", family: "roman", name: "at" },
    // filtered out: verdict not in blocker/unknown/high
    { auditVerdict: "medium", family: "roman", name: "percent" },
    // filtered out: solver does not require reconstruction
    { auditVerdict: "blocker", family: "roman", name: "ampersand" },
  ]);
  writeJson(root, "packages/glyph-forge-engine/manifests/glyph-scores.json", {
    "roman/at": { worstComposite: 0.8, worstWght: 700 },
    "roman/dollar": { worstComposite: 0.4, worstWght: 250 },
  });
  writeJson(root, "packages/glyph-forge-engine/manifests/solver-results.json", {
    "roman/ampersand": { requiresReconstruction: false },
    "roman/at": { best: "open_bar", gain: 0.05, requiresReconstruction: true },
    "roman/dollar": {
      best: "donor_copy",
      gain: 0.2,
      requiresReconstruction: true,
    },
  });

  const targets = loadHandoffTargets(root, 5);
  expect(targets.map((entry) => entry.name)).toEqual(["dollar", "at"]);
  expect(targets[0]).toMatchObject({
    best: "donor_copy",
    gain: 0.2,
    verdict: "blocker",
    worstComposite: 0.4,
    worstWght: 250,
  });

  expect(loadHandoffTargets(root, 1)).toHaveLength(1);
});

test("loadHandoffTargets returns empty when manifests are missing", () => {
  const root = tempWorkspace();
  expect(loadHandoffTargets(root, 5)).toEqual([]);
});

test("formatDuration switches to seconds at 1s", () => {
  expect(formatDuration(999)).toBe("999ms");
  expect(formatDuration(1500)).toBe("1.5s");
});
