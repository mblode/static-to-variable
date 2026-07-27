import type { Metadata } from "next";

import "./globals.css";
import { Inter } from "next/font/google";

import { siteName, siteUrl } from "@/lib/config";
import { cn } from "@/lib/utils";

const inter = Inter({
  subsets: ["latin"],
  style: ["normal", "italic"],
  variable: "--font-inter",
  display: "swap",
});

const title = "Turn static fonts into one variable font";
const description =
  "Turn static font files into one variable font with every weight in between. Upload thin, regular, and bold weights online, then download TTF and WOFF2 files.";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: title,
    template: `%s · ${siteName}`,
  },
  description,
  keywords: [
    "variable fonts",
    "font interpolation",
    "fontmake",
    "fontTools",
    "OpenType",
    "typography",
    "static to variable",
  ],
  // Absolute, not "/": a relative canonical resolves to a trailing-slash
  // variant that would not match the 308 target from variable.blode.co.
  // Needed now that the old subdomain redirects here and the zone origin host
  // serves the same content.
  alternates: {
    canonical: siteUrl,
  },
  openGraph: {
    title,
    description,
    type: "website",
    siteName,
    url: siteUrl,
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html className={cn("dark font-sans", inter.variable)} lang="en">
      <head>
        <link href="https://us.i.posthog.com" rel="preconnect" />
        <link href="https://us-assets.i.posthog.com" rel="dns-prefetch" />
      </head>
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
