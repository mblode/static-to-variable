"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Grid" },
  { href: "/generate", label: "Generate" },
  { href: "/triage", label: "Triage" },
  { href: "/interventions", label: "Interventions" },
] as const;

export function NavLinks() {
  const pathname = usePathname();

  return (
    <nav className="flex items-center gap-1">
      {NAV_ITEMS.map(({ href, label }) => {
        const isActive =
          href === "/"
            ? pathname === "/" || pathname.startsWith("/g/")
            : pathname.startsWith(href);

        return (
          <Button
            key={href}
            asChild
            variant="ghost"
            size="sm"
            className={cn(isActive && "bg-muted")}
          >
            <Link href={href}>{label}</Link>
          </Button>
        );
      })}
    </nav>
  );
}
