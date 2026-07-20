import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { beforeEach, expect, test, vi } from "vitest";

import { runEngine, runEngineCapture } from "./python.js";
import { resolveSplitInvocation, runSplit } from "./split.js";

vi.mock("./python.js", () => ({
  runEngine: vi.fn(() => Promise.resolve(0)),
  runEngineCapture: vi.fn(() => Promise.resolve({ code: 0, stdout: "" })),
}));

const mockedRunEngine = vi.mocked(runEngine);
const mockedRunEngineCapture = vi.mocked(runEngineCapture);

beforeEach(() => {
  mockedRunEngine.mockClear();
  mockedRunEngine.mockResolvedValue(0);
  mockedRunEngineCapture.mockClear();
  mockedRunEngineCapture.mockResolvedValue({ code: 0, stdout: "" });
});

test("resolveSplitInvocation resolves relative paths against the given cwd", () => {
  const { fontPath, outDir, args } = resolveSplitInvocation(
    "fonts/vf.ttf",
    { out: "out/static" },
    "/work/here"
  );
  expect(fontPath).toBe("/work/here/fonts/vf.ttf");
  expect(outDir).toBe("/work/here/out/static");
  expect(args).toEqual([
    "split",
    "--input",
    "/work/here/fonts/vf.ttf",
    "--output",
    "/work/here/out/static",
    "--step",
    "100",
  ]);
});

test("resolveSplitInvocation keeps absolute font paths and defaults out to ./static", () => {
  const { fontPath, outDir } = resolveSplitInvocation(
    "/abs/vf.ttf",
    {},
    "/cwd"
  );
  expect(fontPath).toBe("/abs/vf.ttf");
  expect(outDir).toBe("/cwd/static");
});

test("resolveSplitInvocation forwards step and --json", () => {
  const { args } = resolveSplitInvocation(
    "/abs/vf.ttf",
    { step: 50, json: true },
    "/cwd"
  );
  expect(args).toContain("--json");
  expect(args[args.indexOf("--step") + 1]).toBe("50");
});

test("runSplit throws STV_INPUT_MISSING when the font does not exist", async () => {
  await expect(
    runSplit("/definitely/not/a/font.ttf", {})
  ).rejects.toMatchObject({ code: "STV_INPUT_MISSING" });
  expect(mockedRunEngine).not.toHaveBeenCalled();
});

test("runSplit delegates to the engine split subcommand and returns its exit code", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "stv-split-"));
  writeFileSync(
    path.join(dir, "vf.ttf"),
    "placeholder — only needs to exist for the presence check"
  );
  const original = process.cwd();
  process.chdir(dir);
  try {
    // Read cwd back after chdir: on macOS tmpdir() is symlinked, so the resolved
    // path differs from `dir` — the command resolves against the resolved cwd.
    const cwd = process.cwd();
    mockedRunEngine.mockResolvedValueOnce(3);
    const code = await runSplit("vf.ttf", { out: "static", step: 200 });
    expect(code).toBe(3);
    expect(mockedRunEngine).toHaveBeenCalledWith([
      "split",
      "--input",
      path.join(cwd, "vf.ttf"),
      "--output",
      path.join(cwd, "static"),
      "--step",
      "200",
    ]);
  } finally {
    process.chdir(original);
  }
});

test("runSplit --json captures the engine summary and forwards it to stdout", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "stv-split-json-"));
  writeFileSync(path.join(dir, "vf.ttf"), "placeholder font bytes");
  const original = process.cwd();
  process.chdir(dir);
  const written: string[] = [];
  const spy = vi
    .spyOn(process.stdout, "write")
    .mockImplementation((chunk: string | Uint8Array) => {
      written.push(String(chunk));
      return true;
    });
  try {
    mockedRunEngineCapture.mockResolvedValueOnce({
      code: 0,
      stdout: '{"count":1}',
    });
    const code = await runSplit("vf.ttf", { json: true });
    expect(code).toBe(0);
    // Capturing path used, not the inheriting one.
    expect(mockedRunEngine).not.toHaveBeenCalled();
    expect(mockedRunEngineCapture).toHaveBeenCalledWith(
      expect.arrayContaining(["split", "--json"])
    );
    expect(written.join("")).toBe('{"count":1}\n');
  } finally {
    spy.mockRestore();
    process.chdir(original);
  }
});
