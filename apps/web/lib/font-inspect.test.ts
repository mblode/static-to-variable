import { describe, expect, it } from "vitest";

import { resolveWeight } from "./font-inspect";

describe("resolveWeight", () => {
  it("trusts the name over a wrong usWeightClass", () => {
    // Google's shipped Inter statics declare 250 for BOTH Thin and ExtraLight,
    // so the weight table showed "250" for a font plainly named Thin and the
    // two weights collided.
    expect(resolveWeight(250, "Inter 18pt", "Thin")).toBe(100);
    expect(resolveWeight(250, "Inter 18pt", "ExtraLight")).toBe(200);
  });

  it("trusts the name over a generic 400", () => {
    expect(resolveWeight(400, "Operator Mono", "Bold")).toBe(700);
  });

  it("keeps usWeightClass when the name names no weight", () => {
    expect(resolveWeight(350, "Some Serif", "Book")).toBe(350);
  });

  it("reads the weight from the family when the style is the default label", () => {
    expect(resolveWeight(250, "Foo Thin", "Regular")).toBe(100);
  });

  it("keeps a real Regular at 400", () => {
    expect(resolveWeight(400, "Inter 18pt", "Regular")).toBe(400);
  });

  it("prefers the longest keyword match", () => {
    expect(resolveWeight(400, "Foo", "ExtraBold")).toBe(800);
    expect(resolveWeight(400, "Foo", "SemiBold")).toBe(600);
    expect(resolveWeight(400, "Foo", "ExtraLight")).toBe(200);
  });

  it("matches the whole Inter weight run to distinct values", () => {
    const run = [
      ["Thin", 250, 100],
      ["ExtraLight", 250, 200],
      ["Light", 300, 300],
      ["Regular", 400, 400],
      ["Medium", 500, 500],
      ["SemiBold", 600, 600],
      ["Bold", 700, 700],
      ["ExtraBold", 800, 800],
      ["Black", 900, 900],
    ] as const;
    const resolved = run.map(([style, us]) =>
      resolveWeight(us, "Inter 18pt", style)
    );
    expect(resolved).toEqual(run.map((entry) => entry[2]));
    expect(new Set(resolved).size).toBe(run.length);
  });
});
