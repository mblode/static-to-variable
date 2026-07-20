import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { beforeEach, expect, test, vi } from "vitest";

import { spawnInherit } from "./proc.js";
import {
  findWorkspaceRoot,
  formatDuration,
  readPipelineStatus,
  runStage,
  runStages,
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
  const result = await runStage(resolveStage("repair_build"), {}, "/tmp");
  expect(result.code).toBe(3);
  expect(result.stage.id).toBe("repair_build");
  expect(mockedSpawn).toHaveBeenCalledWith(
    "npm",
    ["--workspace", "@static-to-variable/variable-gen", "run", "rebuild"],
    "/tmp"
  );
});

test("runStage uses npm.cmd on Windows", async () => {
  const original = process.platform;
  Object.defineProperty(process, "platform", { value: "win32" });
  try {
    await runStage(resolveStage("repair_build"), {}, "/tmp");
  } finally {
    Object.defineProperty(process, "platform", { value: original });
  }
  expect(mockedSpawn).toHaveBeenCalledWith(
    "npm.cmd",
    expect.arrayContaining(["run", "rebuild"]),
    "/tmp"
  );
});

test("runStage --dry-run never spawns", async () => {
  const result = await runStage(
    resolveStage("repair_build"),
    { dryRun: true },
    "/tmp"
  );
  expect(result.code).toBe(0);
  expect(mockedSpawn).not.toHaveBeenCalled();
});

test("runStages stops at the first failure unless continueOnFail", async () => {
  const stages = [resolveStage("repair_build"), resolveStage("status")];
  mockedSpawn.mockResolvedValueOnce(1);
  const stopped = await runStages(stages, {}, "/tmp");
  expect(stopped.map((result) => result.code)).toEqual([1]);

  mockedSpawn.mockResolvedValueOnce(1);
  const all = await runStages(stages, { continueOnFail: true }, "/tmp");
  expect(all.map((result) => result.code)).toEqual([1, 0]);
});

test("formatDuration switches to seconds at 1s", () => {
  expect(formatDuration(999)).toBe("999ms");
  expect(formatDuration(1500)).toBe("1.5s");
});
