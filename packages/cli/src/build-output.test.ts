import { expect, test } from "vitest";

import { parseBuildEngineOutput } from "./build-output.js";

test("parses a static layout line", () => {
  const [parsed] = parseBuildEngineOutput(
    "[roman] built (frozen: ['a', 'b']; layout: static (GDEF, GSUB, GPOS))"
  );
  expect(parsed?.style).toBe("roman");
  expect(parsed?.frozen).toEqual(["a", "b"]);
  expect(parsed?.layout.mode).toBe("static");
  expect(parsed?.layout.tables).toEqual(["GDEF", "GSUB", "GPOS"]);
});

test("parses the variable-kern mode without swallowing it as 'variable'", () => {
  const [parsed] = parseBuildEngineOutput(
    "[roman] built (frozen: []; layout: variable-kern (GDEF, GSUB, GPOS, 207 of 731 kern values vary))"
  );
  expect(parsed?.layout.mode).toBe("variable-kern");
  expect(parsed?.layout.tables).toEqual(["GDEF", "GSUB", "GPOS"]);
  expect(parsed?.layout.note).toBe("207 of 731 kern values vary");
});

test("captures the hinting segment", () => {
  const [parsed] = parseBuildEngineOutput(
    "[roman] built (frozen: []; layout: variable (GSUB, GPOS, BASE); hinting: smooth (gasp, prep))"
  );
  expect(parsed?.layout.tables).toEqual(["GSUB", "GPOS", "BASE"]);
  expect(parsed?.hinting).toBe("hinting: smooth (gasp, prep)");
});

test("still parses a line with no hinting segment", () => {
  const [parsed] = parseBuildEngineOutput(
    "built (frozen: []; layout: none (donor has no layout tables))"
  );
  expect(parsed?.style).toBeUndefined();
  expect(parsed?.layout.mode).toBe("none");
  expect(parsed?.layout.note).toBe("donor has no layout tables");
});

test("ignores unrelated engine chatter", () => {
  expect(
    parseBuildEngineOutput(
      ["[roman] reconstructing 500 glyphs on 8 core(s)", "done"].join("\n")
    )
  ).toEqual([]);
});
