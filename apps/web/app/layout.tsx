import { GoogleAnalytics } from "@next/third-parties/google";
import type { Metadata } from "next";

import "./globals.css";
import localFont from "next/font/local";

import { cn } from "@/lib/utils";

const glide = localFont({
  src: [
    { path: "../public/glide-variable.woff2", style: "normal" },
    { path: "../public/glide-variable-italic.woff2", style: "italic" },
  ],
  variable: "--font-glide",
  weight: "100 950",
  display: "swap",
});

const glideMono = localFont({
  src: [{ path: "../public/glide-mono.woff2", style: "normal" }],
  variable: "--font-glide-mono",
  weight: "400",
  display: "swap",
});

const title = "static-to-variable";
const description =
  "Turn a family of independently-drawn static font weights into one variable font, rebuilt onto a shared structure so they interpolate. Scrub the weight axis on real fonts the pipeline built.";

export const metadata: Metadata = {
  metadataBase: new URL("https://variable.blode.co"),
  title: {
    default: `${title}: static weights into one variable font`,
    template: `%s · ${title}`,
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
  openGraph: {
    title: `${title}: static weights into one variable font`,
    description,
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: `${title}: static weights into one variable font`,
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
      <body className="min-h-dvh antialiased">{children}</body>
      {process.env.NODE_ENV === "production" ? (
        <GoogleAnalytics gaId="G-1E6KD4YTJ8" />
      ) : null}
    </html>
  );
}
