"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Button } from "@/components/ui/button";
import type { Family } from "@/lib/data";

export function TriageActions({
  family,
  glyph,
}: {
  family: Family;
  glyph: string;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  const unstage = () => {
    startTransition(async () => {
      const res = await fetch("/api/triage/unstage", {
        body: JSON.stringify({ family, glyph }),
        headers: { "content-type": "application/json" },
        method: "POST",
      });
      if (res.ok) {
        router.refresh();
      }
    });
  };

  return (
    <Button
      type="button"
      onClick={unstage}
      disabled={isPending}
      variant="ghost"
      size="xs"
    >
      {isPending ? "…" : "unstage"}
    </Button>
  );
}
