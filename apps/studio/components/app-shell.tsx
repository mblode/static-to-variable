import Link from "next/link";

import { NavLinks } from "@/components/nav-links";

export function AppShell() {
  return (
    <header className="border-b border-border">
      <div className="mx-auto flex max-w-[1600px] items-center justify-between px-6 py-3">
        <Link
          href="/"
          className="font-semibold text-sm tracking-tight text-foreground"
        >
          Static to Variable
        </Link>
        <NavLinks />
      </div>
    </header>
  );
}
