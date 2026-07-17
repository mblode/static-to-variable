"use client";

import { TriangleExclamationIcon } from "blode-icons-react";

import { ProgressItem, ProgressList } from "@/components/ui/progress-list";
import type { ProgressItemState } from "@/components/ui/progress-list";
import { Spinner } from "@/components/ui/spinner";
import type { BuildStage } from "@/lib/build-types";

const STATE_BY_STATUS: Record<
  Exclude<BuildStage["status"], "failed">,
  ProgressItemState
> = {
  pending: "pending",
  running: "current",
  succeeded: "completed",
};

export function BuildProgress({ stages }: { stages: BuildStage[] }) {
  return (
    <ProgressList className="gap-2 space-y-0 rounded-xl bg-card p-4 ring-1 ring-foreground/10">
      {stages.length === 0 ? (
        <div className="flex flex-row items-center space-x-2 text-muted-foreground">
          <Spinner className="size-4" />
          <span className="flex-1 text-left text-sm">Starting build…</span>
        </div>
      ) : null}
      {stages.map((stage) =>
        stage.status === "failed" ? (
          <div
            className="flex flex-row items-center space-x-2 text-destructive"
            key={stage.id}
          >
            <TriangleExclamationIcon className="size-4 shrink-0" />
            <span className="flex-1 text-left text-sm">{stage.title}</span>
          </div>
        ) : (
          <ProgressItem
            key={stage.id}
            state={STATE_BY_STATUS[stage.status]}
            title={stage.title}
          />
        )
      )}
    </ProgressList>
  );
}
