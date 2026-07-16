import { expect, test } from "vitest";

import {
  buildStagePlan,
  defaultStages,
  normalizeStageId,
  PIPELINE_STAGES,
  resolveStage,
} from "./stages.js";

test("stage ids are unique", () => {
  const ids = PIPELINE_STAGES.map((stage) => stage.id);
  expect(new Set(ids).size).toBe(ids.length);
});

test("stage aliases normalize to status ids", () => {
  expect(normalizeStageId("raw-compatibility")).toBe("raw_compatibility");
  expect(resolveStage("repair").id).toBe("repair_build");
  expect(resolveStage("rebuild").id).toBe("repair_build");
  expect(resolveStage("status").id).toBe("pipeline_status");
});

test("resolveStage throws a typed usage error for unknown stages", () => {
  expect(() => resolveStage("no-such-stage")).toThrow(/Unknown stage/);
});

test("default plan runs the exact expected sequence", () => {
  expect(defaultStages().map((stage) => stage.id)).toEqual([
    "inventory",
    "raw_compatibility",
    "repair_build",
    "audit_interpolation",
    "full_audit",
    "blocker_residuals",
    "glyph_forge",
    "pipeline_status",
  ]);
});

test("the rebuild stage runs the config-driven engine command", () => {
  const stage = resolveStage("repair_build");
  expect(stage.args.at(-1)).toBe("rebuild");
  expect(stage.artifact).toBe(
    "packages/variable-gen/reports/reconstruction-report.json"
  );
  expect(stage.mutatesSources).toBe(true);
});

test("blocking plan keeps reporting and excludes diagnostics", () => {
  const stages = buildStagePlan({ blockingOnly: true });
  expect(stages.map((stage) => stage.kind)).toEqual([
    "blocking",
    "blocking",
    "blocking",
    "blocking",
    "reporting",
  ]);
});

test("range plans respect --from/--to and reject empty ranges", () => {
  const range = buildStagePlan({ from: "repair_build", to: "full_audit" });
  expect(range.map((stage) => stage.id)).toEqual([
    "repair_build",
    "audit_interpolation",
    "full_audit",
  ]);
  expect(() => buildStagePlan({ from: "full_audit", to: "inventory" })).toThrow(
    /range is empty/i
  );
});
