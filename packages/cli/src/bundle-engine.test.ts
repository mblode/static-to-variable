import { expect, test } from "vitest";

// @ts-expect-error — plain .mjs build script; it exports stripUvSourcesText
// for tests and only executes its copy logic when run as a script.
import { stripUvSourcesText } from "../scripts/bundle-engine.mjs";

const strip = stripUvSourcesText as (text: string) => string;

test("removes a trailing [tool.uv.sources] section", () => {
  const input = [
    "[project]",
    'name = "x"',
    "",
    "[tool.uv.sources]",
    "variable-gen = { workspace = true }",
    "",
  ].join("\n");
  expect(strip(input)).toBe(["[project]", 'name = "x"', ""].join("\n"));
});

test("removes a mid-file section and keeps the following table", () => {
  const input = [
    "[project]",
    'name = "x"',
    "[tool.uv.sources]",
    "variable-gen = { workspace = true }",
    "[tool.other]",
    "keep = true",
  ].join("\n");
  expect(strip(input)).toBe(
    ["[project]", 'name = "x"', "[tool.other]", "keep = true"].join("\n")
  );
});

test("leaves files without the section untouched", () => {
  const input = ["[project]", 'name = "x"'].join("\n");
  expect(strip(input)).toBe(input);
});

test("survives '[' inside section values (the old regex truncated here)", () => {
  const input = [
    "[project]",
    'name = "x"',
    "[tool.uv.sources]",
    'dep = { extras = ["one", "two"] }',
    "[tool.keepme]",
    'value = "[bracketed]"',
  ].join("\n");
  expect(strip(input)).toBe(
    ["[project]", 'name = "x"', "[tool.keepme]", 'value = "[bracketed]"'].join(
      "\n"
    )
  );
});
