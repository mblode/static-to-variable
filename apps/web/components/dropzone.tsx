"use client";

import { CloudUploadIcon } from "blode-icons-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

interface DropzoneProps {
  onFiles: (files: File[]) => void;
}

const ACCEPT = ".ttf,.otf";

export function Dropzone({ onFiles }: DropzoneProps) {
  const [dragging, setDragging] = useState(false);

  const emit = (list: FileList | null): void => {
    if (!list || list.length === 0) {
      return;
    }
    onFiles([...list]);
  };

  return (
    <label
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed px-6 py-14 text-center transition-colors focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20",
        dragging
          ? "border-ring bg-muted/50"
          : "border-border bg-card hover:border-ring hover:bg-muted/30"
      )}
      onDragLeave={(e) => {
        e.preventDefault();
        setDragging(false);
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        emit(e.dataTransfer.files);
      }}
    >
      <span className="flex size-11 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        <CloudUploadIcon className="size-5" />
      </span>
      <div className="flex flex-col gap-1">
        <span className="font-medium text-base text-foreground">
          Drop the weight files of one font
        </span>
        <span className="text-muted-foreground text-sm">
          or choose .ttf or .otf files
        </span>
      </div>
      <input
        accept={ACCEPT}
        className="sr-only"
        multiple
        onChange={(e) => {
          emit(e.target.files);
          e.target.value = "";
        }}
        type="file"
      />
    </label>
  );
}
