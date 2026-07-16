import { mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { Ajv2020 } from "ajv/dist/2020.js";
import { describe, expect, test } from "vitest";

import schema from "../../../schemas/stv-config.schema.json" with { type: "json" };
import { loadProjectConfig } from "./config.js";
import { isCliError } from "./errors.js";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../.."
);
const fixturesRoot = path.join(repoRoot, "schemas/fixtures");

interface Fixture {
  name: string;
  config: Record<string, unknown>;
  expect: { schema: boolean; python: boolean };
}

function loadFixtures(kind: "valid" | "invalid"): Fixture[] {
  const dir = path.join(fixturesRoot, kind);
  return readdirSync(dir)
    .filter((name) => name.endsWith(".json"))
    .map((name) => {
      const parsed = JSON.parse(
        readFileSync(path.join(dir, name), "utf-8")
      ) as Record<string, unknown> & {
        _expect: { schema: boolean; python: boolean };
      };
      const { _expect, ...config } = parsed;
      return { config, expect: _expect, name: `${kind}/${name}` };
    });
}

function tempConfig(contents: string): string {
  const dir = mkdtempSync(path.join(tmpdir(), "stv-config-"));
  const file = path.join(dir, "stv.config.json");
  writeFileSync(file, contents);
  return file;
}

const allFixtures = [...loadFixtures("valid"), ...loadFixtures("invalid")];

test("loads the Glide example config", () => {
  const config = loadProjectConfig(
    path.join(repoRoot, "examples/glide/stv.config.json")
  );
  expect(config.id).toBe("glide");
  expect(config.familyName).toBe("Glide");
  expect(config.styleKeys).toEqual(["italic", "roman"]);
  expect(config.formats).toEqual(["ttf", "woff2"]);
  expect(config.outputDir).toBe("packages/variable-gen/build");
  expect(config.releaseDir).toBe("packages/variable-gen/build/release");
});

test("loads the minimal example config", () => {
  const config = loadProjectConfig(
    path.join(repoRoot, "examples/minimal/stv.config.json")
  );
  expect(config.id).toBe("minimal");
  expect(config.styleKeys).toEqual(["roman"]);
});

test("throws STV_CONFIG_NOT_FOUND (exit 2) on a missing file", () => {
  try {
    loadProjectConfig(path.join(repoRoot, "does-not-exist.json"));
    expect.unreachable("should have thrown");
  } catch (error) {
    if (!isCliError(error)) {
      throw error;
    }
    expect(error.code).toBe("STV_CONFIG_NOT_FOUND");
    expect(error.exitCode).toBe(2);
  }
});

test("throws STV_CONFIG_INVALID (exit 2) with the offending path named", () => {
  const file = tempConfig(JSON.stringify({ id: "x", version: 2 }));
  try {
    loadProjectConfig(file);
    expect.unreachable("should have thrown");
  } catch (error) {
    if (!isCliError(error)) {
      throw error;
    }
    expect(error.code).toBe("STV_CONFIG_INVALID");
    expect(error.exitCode).toBe(2);
    expect(error.message).toMatch(/\/version/);
  }
});

test("throws STV_CONFIG_INVALID on malformed JSON", () => {
  const file = tempConfig("{ not json");
  expect(() => loadProjectConfig(file)).toThrow(/invalid JSON/);
});

test("names the unknown key when strict validation rejects it", () => {
  const fixture = allFixtures.find(
    (entry) => entry.name === "invalid/unknown-top-level-key.json"
  );
  expect(fixture).toBeDefined();
  const file = tempConfig(JSON.stringify(fixture?.config));
  expect(() => loadProjectConfig(file)).toThrow(/buildCache/);
});

describe("schema fixture corpus", () => {
  // The same corpus is checked against the Python loader in
  // packages/variable-gen/tests/test_schema_fixtures.py, pinning
  // cross-language agreement on what a valid config is.
  const validate = new Ajv2020({ allErrors: true }).compile(schema);

  for (const fixture of allFixtures) {
    test(`${fixture.name} matches its schema expectation`, () => {
      expect(validate(fixture.config)).toBe(fixture.expect.schema);
    });

    test(`${fixture.name} matches loadProjectConfig's verdict`, () => {
      const file = tempConfig(JSON.stringify(fixture.config));
      if (fixture.expect.schema) {
        expect(() => loadProjectConfig(file)).not.toThrow();
      } else {
        try {
          loadProjectConfig(file);
          expect.unreachable("should have thrown");
        } catch (error) {
          if (!isCliError(error)) {
            throw error;
          }
          expect(error.code).toBe("STV_CONFIG_INVALID");
          expect(error.exitCode).toBe(2);
        }
      }
    });
  }
});
