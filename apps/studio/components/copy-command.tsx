"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

export function CopyCommand({
  command,
  label = "copy",
}: {
  command: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);

  return (
    <Button
      type="button"
      variant="outline"
      size="xs"
      onClick={async () => {
        await navigator.clipboard.writeText(command);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      }}
    >
      {copied ? "copied" : label}
    </Button>
  );
}
