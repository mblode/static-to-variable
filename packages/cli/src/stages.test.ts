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
  expect(resolveStage("status").id).toBe("pipeline_status");
});

test("default plan includes status last and excludes optional sync", () => {
  const stages = defaultStages();
  expect(stages.at(-1)?.id).toBe("pipeline_status");
  expect(stages.some((stage) => stage.id === "glyph_forge_sync")).toBe(false);
  expect(stages.some((stage) => stage.id === "isolate_blockers")).toBe(false);
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
