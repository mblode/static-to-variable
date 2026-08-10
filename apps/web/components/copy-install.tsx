"use client";

import { CheckIcon, CopySimpleIcon } from "blode-icons-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

interface CopyInstallProps {
  code: string;
}

export function CopyInstall({ code }: CopyInstallProps) {
  const [copied, setCopied] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    },
    []
  );

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
      timeoutRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard may be unavailable outside secure contexts.
    }
  }

  return (
    <div className="relative">
      <span
        aria-live="polite"
        className="absolute size-0 overflow-hidden whitespace-nowrap"
      >
        {copied ? "Copied install command to clipboard" : ""}
      </span>
      <Button
        aria-label={copied ? "Copied install command" : "Copy install command"}
        className="absolute top-3 right-3"
        onClick={handleCopy}
        size="xs"
        type="button"
        variant="outline"
      >
        {copied ? (
          <>
            <CheckIcon aria-hidden />
            Copied
          </>
        ) : (
          <>
            <CopySimpleIcon aria-hidden />
            Copy
          </>
        )}
      </Button>
      <pre className="overflow-x-auto rounded-xl bg-card px-5 py-4 pr-24 font-mono text-muted-foreground text-sm leading-6 ring-1 ring-foreground/10">
        <code>{code}</code>
      </pre>
    </div>
  );
}
