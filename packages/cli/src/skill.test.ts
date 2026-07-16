import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { Ajv2020 } from "ajv/dist/2020.js";
import { expect, test } from "vitest";

import schema from "../../../schemas/stv-config.schema.json" with { type: "json" };
import { INIT_CONFIG_TEMPLATE } from "./init-template.js";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../.."
);

// The root skills/ directory is the single committed copy; prepack copies it
// into the package (packages/cli/skills is gitignored and generated).
const skillPath = path.join(repoRoot, "skills/static-to-variable/SKILL.md");

const validate = new Ajv2020({ allErrors: true }).compile(schema);

test("the init scaffold validates against the schema", () => {
  const config = JSON.parse(INIT_CONFIG_TEMPLATE) as unknown;
  expect(validate(config)).toBe(true);
  expect(validate.errors ?? []).toEqual([]);
});

test("the skill's embedded example config validates against the schema", () => {
  const skill = readFileSync(skillPath, "utf-8");
  const fences = [...skill.matchAll(/```json\n([\s\S]*?)```/g)];
  expect(fences.length).toBeGreaterThan(0);
  for (const fence of fences) {
    const config = JSON.parse(fence[1] ?? "") as unknown;
    expect(validate(config)).toBe(true);
    expect(validate.errors ?? []).toEqual([]);
  }
});
