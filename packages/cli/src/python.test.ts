import type { SpawnSyncReturns } from "node:child_process";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { engineKey, inspectEngineEnv, pythonVersion } from "./python.js";

vi.mock("node:child_process", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return { ...actual, spawnSync: vi.fn() };
});

const mockedSpawnSync = vi.mocked(spawnSync);

function versionResult(
  overrides: Partial<SpawnSyncReturns<string>>
): SpawnSyncReturns<string> {
  return {
    output: [],
    pid: 1,
    signal: null,
    status: 0,
    stderr: "",
    stdout: "",
    ...overrides,
  };
}

const env = { baseArgs: [], command: "python3", cwd: "/tmp" };

beforeEach(() => {
  mockedSpawnSync.mockReset();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

test("pythonVersion strips the Python prefix from stdout", () => {
  mockedSpawnSync.mockReturnValue(versionResult({ stdout: "Python 3.12.4\n" }));
  expect(pythonVersion(env)).toBe("3.12.4");
});

test("pythonVersion reads stderr too (Python 2 convention)", () => {
  mockedSpawnSync.mockReturnValue(versionResult({ stderr: "Python 3.11.9\n" }));
  expect(pythonVersion(env)).toBe("3.11.9");
});

test("pythonVersion returns null on a non-zero exit", () => {
  mockedSpawnSync.mockReturnValue(versionResult({ status: 1 }));
  expect(pythonVersion(env)).toBeNull();
});

test("pythonVersion returns null when output is empty", () => {
  mockedSpawnSync.mockReturnValue(versionResult({}));
  expect(pythonVersion(env)).toBeNull();
});

function tempEngine(): string {
  const dir = mkdtempSync(path.join(tmpdir(), "stv-engine-"));
  mkdirSync(path.join(dir, "variable-gen/src"), { recursive: true });
  writeFileSync(path.join(dir, "variable-gen/pyproject.toml"), "[project]\n");
  writeFileSync(path.join(dir, "variable-gen/src/module.py"), "VALUE = 1\n");
  return dir;
}

test("engineKey is stable for identical content", () => {
  const dir = tempEngine();
  expect(engineKey(dir)).toBe(engineKey(dir));
  expect(engineKey(dir)).toMatch(/^[0-9a-f]{16}$/);
});

test("engineKey changes when any engine source byte changes", () => {
  const dir = tempEngine();
  const before = engineKey(dir);
  writeFileSync(path.join(dir, "variable-gen/src/module.py"), "VALUE = 2\n");
  expect(engineKey(dir)).not.toBe(before);
});

test("engineKey ignores non-source files", () => {
  const dir = tempEngine();
  const before = engineKey(dir);
  writeFileSync(path.join(dir, "variable-gen/notes.txt"), "scratch\n");
  expect(engineKey(dir)).toBe(before);
});

test("engineKey has a stable fallback for a missing dir", () => {
  const missing = path.join(tmpdir(), "stv-engine-definitely-missing");
  expect(engineKey(missing)).toBe(engineKey(missing));
});

test("inspectEngineEnv reports an unprovisioned venv under the data root", () => {
  const dataHome = mkdtempSync(path.join(tmpdir(), "stv-data-"));
  vi.stubEnv("XDG_DATA_HOME", dataHome);

  const info = inspectEngineEnv();
  expect(info.provisioned).toBe(false);
  expect(info.venvDir.startsWith(dataHome)).toBe(true);
  expect(info.python.startsWith(info.venvDir)).toBe(true);
});
