import { describe, expect, it } from "vitest";

import { resolveWeight } from "./font-inspect.js";

describe("resolveWeight", () => {
  it("trusts the name over a wrong usWeightClass", () => {
    // Google's shipped Inter statics declare 250 for BOTH Thin and ExtraLight.
    // `init` drops same-weight files as duplicates, so trusting OS/2 silently
    // discarded one of them and left the family a weight short.
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

  it('never lets a default "Regular" subfamily overrule OS/2', () => {
    // Inter's own statics ship Thin, Regular and Black all as family "Inter"
    // with subfamily "Regular", and rely entirely on usWeightClass. Treating
    // "Regular" as a claim of 400 collapsed the whole family onto one weight.
    expect(resolveWeight(100, "Inter", "Regular")).toBe(100);
    expect(resolveWeight(400, "Inter", "Regular")).toBe(400);
    expect(resolveWeight(900, "Inter", "Regular")).toBe(900);
  });

  it("falls back to the default only when nothing else knows", () => {
    expect(resolveWeight(0, "Inter", "Regular")).toBe(400);
    expect(resolveWeight(0, "Some Serif", "Book")).toBe(400);
  });

  it("prefers the longest keyword match", () => {
    expect(resolveWeight(400, "Foo", "ExtraBold")).toBe(800);
    expect(resolveWeight(400, "Foo", "SemiBold")).toBe(600);
    expect(resolveWeight(400, "Foo", "ExtraLight")).toBe(200);
  });

  it("gives the whole Inter weight run nine distinct weights", () => {
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
