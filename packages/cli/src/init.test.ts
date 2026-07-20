import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { Ajv2020 } from "ajv/dist/2020.js";
import { expect, test } from "vitest";

import schema from "../../../schemas/stv-config.schema.json" with { type: "json" };
import { inspectFont } from "./font-inspect.js";
import type { FoundFont } from "./init.js";
import { buildInitConfig, scanFonts } from "./init.js";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../.."
);
const donorsDir = path.join(repoRoot, "examples/minimal/donors");

const validate = new Ajv2020({ allErrors: true }).compile(schema);

function donor(fileName: string): FoundFont {
  return {
    info: inspectFont(readFileSync(path.join(donorsDir, fileName))),
    relPath: `donors/${fileName}`,
  };
}

test("inspectFont reads names and weights from a real donor", () => {
  const regular = donor("Inter-Regular.ttf").info;
  expect(regular.family).toBe("Inter");
  expect(regular.weight).toBe(400);
  expect(regular.italic).toBe(false);

  expect(donor("Inter-Thin.ttf").info.weight).toBe(100);
  expect(donor("Inter-Black.ttf").info.weight).toBe(900);
});

test("scanFonts finds donors and skips build directories", () => {
  const found = scanFonts(path.join(repoRoot, "examples/minimal"));
  expect(found.map((f) => f.relPath)).toEqual([
    path.join("donors", "Inter-Thin.ttf"),
    path.join("donors", "Inter-Regular.ttf"),
    path.join("donors", "Inter-Black.ttf"),
  ]);
});

test("buildInitConfig generates a schema-valid config from detected fonts", () => {
  const fonts = [
    donor("Inter-Thin.ttf"),
    donor("Inter-Regular.ttf"),
    donor("Inter-Black.ttf"),
  ];
  const { config, skipped } = buildInitConfig(fonts, "My Sans");
  expect(skipped).toEqual([]);
  expect(validate(config)).toBe(true);
  expect(validate.errors ?? []).toEqual([]);

  const c = config as {
    id: string;
    axes: {
      minimum: number;
      default: number;
      maximum: number;
      namedInstances: Record<string, string>;
    }[];
    styles: {
      roman: {
        donors: { path: string }[];
        masters: { name: string; default?: boolean }[];
      };
    };
  };
  expect(c.id).toBe("mysans");
  expect(c.axes[0]).toMatchObject({ minimum: 100, default: 400, maximum: 900 });
  expect(c.axes[0]?.namedInstances).toEqual({
    "100": "Thin",
    "400": "Regular",
    "900": "Black",
  });
  expect(c.styles.roman.donors.map((d) => d.path)).toEqual([
    "donors/Inter-Thin.ttf",
    "donors/Inter-Regular.ttf",
    "donors/Inter-Black.ttf",
  ]);
  expect(
    c.styles.roman.masters.filter((m) => m.default === true).map((m) => m.name)
  ).toEqual(["Regular"]);
});

test("buildInitConfig skips duplicate weights and keeps the first", () => {
  const fonts = [
    donor("Inter-Thin.ttf"),
    donor("Inter-Regular.ttf"),
    {
      ...donor("Inter-Black.ttf"),
      info: { ...donor("Inter-Black.ttf").info, weight: 400 },
    },
  ];
  const { skipped } = buildInitConfig(fonts, "My Sans");
  expect(skipped).toEqual(["donors/Inter-Black.ttf (duplicate weight 400)"]);
});

test("buildInitConfig rejects a single usable weight", () => {
  expect(() =>
    buildInitConfig([donor("Inter-Regular.ttf")], "My Sans")
  ).toThrow(/at least two/);
});
