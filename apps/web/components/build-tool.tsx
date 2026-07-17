"use client";

import {
  ArrowRotateClockwiseIcon,
  MagicWandIcon,
  TriangleExclamationIcon,
} from "blode-icons-react";
import { useCallback, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { buildFont } from "@/lib/build-client";
import type {
  BuildError,
  BuildResult as BuildResultData,
  BuildStage,
  DetectedFont,
} from "@/lib/build-types";
import { inspectFont } from "@/lib/font-inspect";

import { BuildProgress } from "./build-progress";
import { BuildResult } from "./build-result";
import { Dropzone } from "./dropzone";
import { WeightTable } from "./weight-table";

type Phase = "collect" | "building" | "done" | "error";

/** One dropped file plus its client-detected metadata. */
interface Entry {
  file: File;
  row: DetectedFont;
}

/** Axis + named instances the server reports for the built font. */
interface DetectedAxis {
  axis: BuildResultData["axis"];
  instances: BuildResultData["instances"];
}

function isValid(entries: Entry[]): boolean {
  if (entries.length < 2) {
    return false;
  }
  const weights = entries.map((e) => e.row.weight);
  return new Set(weights).size === weights.length;
}

export function BuildTool() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [rejected, setRejected] = useState<string[]>([]);
  const [phase, setPhase] = useState<Phase>("collect");
  const [stages, setStages] = useState<BuildStage[]>([]);
  const [result, setResult] = useState<BuildResultData | null>(null);
  const [error, setError] = useState<BuildError | null>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const detectedRef = useRef<DetectedAxis | null>(null);

  const addFiles = useCallback(async (files: File[]) => {
    const added: Entry[] = [];
    const bad: string[] = [];
    for (const file of files) {
      try {
        const info = inspectFont(await file.arrayBuffer());
        added.push({ file, row: { fileName: file.name, ...info } });
      } catch {
        bad.push(file.name);
      }
    }
    setRejected(bad);
    setEntries((prev) => {
      const seen = new Set(prev.map((e) => e.row.fileName));
      return [...prev, ...added.filter((e) => !seen.has(e.row.fileName))];
    });
  }, []);

  const changeWeight = useCallback((i: number, weight: number) => {
    setEntries((prev) =>
      prev.map((e, idx) =>
        idx === i ? { ...e, row: { ...e.row, weight } } : e
      )
    );
  }, []);

  const remove = useCallback((i: number) => {
    setEntries((prev) => prev.filter((_, idx) => idx !== i));
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.();
    abortRef.current = null;
    detectedRef.current = null;
    for (const file of result?.files ?? []) {
      URL.revokeObjectURL(file.url);
    }
    setResult(null);
    setError(null);
    setStages([]);
    setEntries([]);
    setRejected([]);
    setPhase("collect");
  }, [result]);

  const start = useCallback(() => {
    setError(null);
    setResult(null);
    setStages([]);
    detectedRef.current = null;
    setPhase("building");

    const weights = Object.fromEntries(
      entries.map((e) => [e.row.fileName, e.row.weight])
    );
    abortRef.current = buildFont(
      entries.map((e) => e.file),
      weights,
      {
        onStages: (list) =>
          setStages(list.map((s) => ({ ...s, status: "pending" }))),
        onDetected: (d) => {
          detectedRef.current = {
            axis: { min: d.axis.min, def: d.axis.def, max: d.axis.max },
            instances: d.fonts.map((f) => ({ name: f.name, wght: f.weight })),
          };
        },
        onStage: (stage) =>
          setStages((prev) =>
            prev.map((s) =>
              s.id === stage.id ? { ...s, status: stage.status } : s
            )
          ),
        onResult: (payload) => {
          const detected = detectedRef.current;
          setResult({
            files: payload.files,
            frozen: payload.frozen,
            axis: detected?.axis ?? { min: 0, def: 0, max: 0 },
            instances: detected?.instances ?? [],
          });
          setPhase("done");
        },
        onError: (err) => {
          setError(err);
          setPhase("error");
        },
      }
    );
  }, [entries]);

  const canBuild = isValid(entries);

  return (
    <div className="flex flex-col gap-5">
      {phase === "collect" || entries.length === 0 ? (
        <Dropzone onFiles={addFiles} />
      ) : null}

      {rejected.length > 0 && phase === "collect" ? (
        <p className="text-destructive text-sm">
          Skipped {rejected.join(", ")} — not a readable .ttf/.otf.
        </p>
      ) : null}

      {phase === "collect" && entries.length > 0 ? (
        <>
          <WeightTable
            onChangeWeight={changeWeight}
            onRemove={remove}
            rows={entries.map((e) => e.row)}
          />
          <Button
            className="self-start"
            disabled={!canBuild}
            onClick={start}
            size="lg"
          >
            <MagicWandIcon />
            Build variable font
          </Button>
        </>
      ) : null}

      {phase === "building" ? (
        <>
          <BuildProgress stages={stages} />
          <p className="text-[var(--mut)] text-sm">
            Rebuilding masters and compiling with fontmake — a build usually
            takes 30s–2min.
          </p>
        </>
      ) : null}

      {phase === "done" && result ? (
        <>
          <BuildResult result={result} />
          <Button className="self-start" onClick={reset} variant="outline">
            <ArrowRotateClockwiseIcon />
            Build another
          </Button>
        </>
      ) : null}

      {phase === "error" && error ? (
        <div className="flex flex-col gap-4">
          <Alert variant="destructive">
            <TriangleExclamationIcon />
            <AlertTitle>Build failed — {error.code}</AlertTitle>
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
          <Button
            className="self-start"
            onClick={() => setPhase("collect")}
            variant="outline"
          >
            Back to files
          </Button>
        </div>
      ) : null}
    </div>
  );
}
