"use client";

import { FileDownloadIcon } from "blode-icons-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { BuildResult } from "@/lib/build-types";

import { FontPreview } from "./font-preview";

interface BuildResultProps {
  result: BuildResult;
}

const KILOBYTE = 1024;

function formatBytes(bytes: number): string {
  if (bytes < KILOBYTE) {
    return `${bytes} B`;
  }
  const kib = bytes / KILOBYTE;
  if (kib < KILOBYTE) {
    return `${kib.toFixed(1)} KB`;
  }
  return `${(kib / KILOBYTE).toFixed(2)} MB`;
}

export function BuildResult({ result }: BuildResultProps) {
  const { files, axis, instances, frozen } = result;
  const previewFile = files.find((file) => file.format === "ttf") ?? files[0];

  return (
    <div className="flex flex-col gap-6">
      {previewFile ? (
        <FontPreview axis={axis} instances={instances} src={previewFile.url} />
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Downloads</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {files.map((file) => (
            <div
              className="flex items-center justify-between gap-4 rounded-lg bg-background px-3 py-2 ring-1 ring-foreground/10"
              key={file.name}
            >
              <span className="flex min-w-0 flex-1 items-center gap-2 text-foreground text-sm">
                <span className="truncate">{file.name}</span>
                <Badge className="uppercase" variant="secondary">
                  {file.format}
                </Badge>
              </span>
              <span className="text-muted-foreground text-xs tabular-nums">
                {formatBytes(file.bytes)}
              </span>
              <Button asChild size="sm" variant="outline">
                <a download={file.name} href={file.url}>
                  <FileDownloadIcon />
                  Download
                </a>
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="flex flex-wrap gap-x-6 gap-y-2 px-1 text-muted-foreground text-xs">
        <span>
          Axis{" "}
          <span className="text-foreground tabular-nums">
            Weight {axis.min}–{axis.max}
          </span>{" "}
          · default{" "}
          <span className="text-foreground tabular-nums">{axis.def}</span>
        </span>
        <span>
          Instances:{" "}
          <span className="text-foreground">
            {instances.map((ins) => `${ins.name} ${ins.wght}`).join(" · ")}
          </span>
        </span>
      </div>

      {frozen.length > 0 ? (
        <p className="rounded-lg bg-card px-4 py-3 text-muted-foreground text-xs ring-1 ring-foreground/10">
          {frozen.length} glyph{frozen.length === 1 ? "" : "s"} couldn't
          interpolate cleanly and {frozen.length === 1 ? "was" : "were"} pinned
          — usually a sign of incompatible source outlines.
        </p>
      ) : null}
    </div>
  );
}
