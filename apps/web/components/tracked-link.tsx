"use client";

import type { ComponentProps } from "react";

import { captureConversion } from "@/lib/conversion-events";

export function TrackedLink({
  action,
  event,
  label,
  onClick,
  ...props
}: ComponentProps<"a"> & {
  action: string;
  event?: "cta_clicked" | "download_clicked";
  label: string;
}) {
  return (
    <a
      {...props}
      onClick={(clickEvent) => {
        captureConversion({
          action,
          event,
          href: props.href ?? "",
          label,
        });
        onClick?.(clickEvent);
      }}
    />
  );
}
