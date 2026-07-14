import type { Metadata } from "next";

import { AppShell } from "@/components/app-shell";

import "./globals.css";

export const metadata: Metadata = {
  description:
    "Visual audit and generation workspace for static-to-variable font conversion.",
  robots: { follow: false, index: false },
  title: "Static to Variable Studio",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-dvh antialiased">
        <AppShell />
        {children}
      </body>
    </html>
  );
}
