import type { Metadata } from "next";

import "./globals.css";
import localFont from "next/font/local";

import { ogSiteName, productName, siteUrl, twitterCreator } from "@/lib/config";
import { cn } from "@/lib/utils";

const glide = localFont({
  src: [
    { path: "./fonts/glide-variable.woff2", style: "normal" },
    { path: "./fonts/glide-variable-italic.woff2", style: "italic" },
  ],
  variable: "--font-glide",
  weight: "100 950",
  display: "swap",
});

const glideMono = localFont({
  src: "./fonts/glide-mono.woff2",
  variable: "--font-glide-mono",
  weight: "400",
  display: "swap",
});

// `Product: what it does`, under 60 characters so it survives the SERP. The
// old title said only what it does, so the one line search gives you never
// mentioned what the thing is called.
const title = "Static to Variable: static fonts into one variable font";
const description =
  "Turn static font files into one variable font with every weight in between. Point the CLI at thin, regular, and bold. Get TTF and WOFF2.";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: title,
    template: `%s | ${productName}`,
  },
  description,
  authors: [{ name: "Matthew Blode", url: "https://blode.co" }],
  creator: "Matthew Blode",
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
    siteName: ogSiteName,
    url: siteUrl,
  },
  twitter: {
    card: "summary_large_image",
    creator: twitterCreator,
    title,
    description,
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      className={cn("dark font-sans", glide.variable, glideMono.variable)}
      lang="en"
    >
      <head>
        <link href={process.env.NEXT_PUBLIC_POSTHOG_HOST} rel="preconnect" />
      </head>
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
