import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createLineReader,
  createStageTimeline,
  createTail,
  isFailure,
  logEvent,
  MAX_FIELD_CHARS,
  tailLines,
  truncate,
} from "./build-log";

describe("createLineReader", () => {
  it("holds back a line until its newline arrives", () => {
    const reader = createLineReader();
    // The Sandbox log stream splits on byte boundaries, so this is the case
    // that matters: naive per-chunk splitting reports two mangled fragments.
    expect(reader.feed("Traceback (most recent ")).toEqual([]);
    expect(reader.feed("call last):\n")).toEqual([
      "Traceback (most recent call last):",
    ]);
  });

  it("emits every line a single chunk completes", () => {
    const reader = createLineReader();
    expect(reader.feed('{"a":1}\n{"b":2}\n{"c":3')).toEqual([
      '{"a":1}',
      '{"b":2}',
    ]);
    expect(reader.flush()).toEqual(['{"c":3']);
  });

  it("buffers nothing when a chunk ends on a newline", () => {
    const reader = createLineReader();
    expect(reader.feed("done\n")).toEqual(["done"]);
    expect(reader.flush()).toEqual([]);
  });

  it("drops blank lines rather than reporting empty entries", () => {
    const reader = createLineReader();
    expect(reader.feed("a\n\n   \nb\n")).toEqual(["a", "b"]);
  });

  it("reassembles a line split across three chunks", () => {
    const reader = createLineReader();
    reader.feed("one");
    reader.feed("-two");
    expect(reader.feed("-three\n")).toEqual(["one-two-three"]);
  });
});

describe("createTail", () => {
  it("keeps only the most recent lines across pushes", () => {
    const tail = createTail(3);
    tail.add(["a", "b"]);
    tail.add(["c", "d", "e"]);
    expect(tail.toArray()).toEqual(["c", "d", "e"]);
  });

  it("caps line length so one runaway line cannot blow the log budget", () => {
    const tail = createTail(2);
    tail.add(["x".repeat(MAX_FIELD_CHARS + 50)]);
    expect(tail.toArray()[0]).toHaveLength(MAX_FIELD_CHARS + 3);
    expect(tail.toArray()[0].endsWith("...")).toBe(true);
  });

  it("returns a copy, so the caller cannot mutate the tail", () => {
    const tail = createTail(2);
    tail.add(["a"]);
    tail.toArray().push("b");
    expect(tail.toArray()).toEqual(["a"]);
  });
});

describe("createStageTimeline", () => {
  it("names the stage that started and never reported back", () => {
    const stages = createStageTimeline();
    stages.record("normalize", "running");
    stages.record("normalize", "succeeded");
    stages.record("build", "running");
    expect(stages.stalled()).toBe("build");
  });

  it("reports no stalled stage once every stage has finished", () => {
    const stages = createStageTimeline();
    stages.record("build", "running");
    stages.record("build", "failed");
    expect(stages.stalled()).toBeUndefined();
    expect(stages.timings()).toEqual([
      { id: "build", status: "failed", ms: expect.any(Number) },
    ]);
  });

  it("records a finish with no matching start rather than throwing", () => {
    const stages = createStageTimeline();
    stages.record("orphan", "succeeded");
    expect(stages.timings()).toEqual([
      { id: "orphan", status: "succeeded", ms: 0 },
    ]);
  });
});

describe("truncate", () => {
  it("leaves short text alone", () => {
    expect(truncate("short")).toBe("short");
  });

  it("marks text it cut", () => {
    expect(truncate("abcdef", 3)).toBe("abc...");
  });
});

describe("tailLines", () => {
  it("returns the last non-empty lines", () => {
    expect(tailLines("a\n\nb\nc\n", 2)).toEqual(["b", "c"]);
  });
});

describe("isFailure", () => {
  it("does not count a user leaving as a failure", () => {
    expect(isFailure("client_closed")).toBe(false);
    expect(isFailure("succeeded")).toBe(false);
  });

  it("counts every other outcome as a failure", () => {
    expect(isFailure("timeout")).toBe(true);
    expect(isFailure("engine_error")).toBe(true);
    expect(isFailure("unknown")).toBe(true);
  });
});

describe("logEvent", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("writes failures at error level so alerts can key off them", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {
      // silence
    });
    logEvent("error", { event: "finished", outcome: "timeout" });
    expect(error).toHaveBeenCalledWith(
      '{"scope":"stv.build","event":"finished","outcome":"timeout"}'
    );
  });

  it("emits one parseable JSON object per line", () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => {
      // silence
    });
    logEvent("info", { event: "started", uploads: 3 });
    const [line] = log.mock.calls[0] ?? [];
    expect(JSON.parse(line as string)).toEqual({
      scope: "stv.build",
      event: "started",
      uploads: 3,
    });
  });
});
