import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "vitest";

import { loadProjectConfig } from "./config.js";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../.."
);
const glideConfig = path.join(repoRoot, "examples/glide/stv.config.json");

function tempConfig(contents: string): string {
  const dir = mkdtempSync(path.join(tmpdir(), "stv-config-"));
  const file = path.join(dir, "stv.config.json");
  writeFileSync(file, contents);
  return file;
}

test("loads the Glide example config", () => {
  const config = loadProjectConfig(glideConfig);
  expect(config.id).toBe("glide");
  expect(config.familyName).toBe("Glide");
  expect(config.styleKeys).toEqual(["italic", "roman"]);
  expect(config.formats).toEqual(["ttf", "woff2"]);
  expect(config.outputDir).toBe("packages/variable-gen/build");
  expect(config.releaseDir).toBe("packages/variable-gen/build/release");
});

test("throws on a missing file", () => {
  expect(() =>
    loadProjectConfig(path.join(repoRoot, "does-not-exist.json"))
  ).toThrow(/config file not found/);
});

test("throws on a non-3 version", () => {
  const file = tempConfig(JSON.stringify({ version: 2, id: "x" }));
  expect(() => loadProjectConfig(file)).toThrow(/expected version 3/);
});
