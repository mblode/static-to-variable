import { GoogleAnalytics } from "@next/third-parties/google";
import type { Metadata } from "next";

import "./globals.css";
import { Inter } from "next/font/google";

import { cn } from "@/lib/utils";

const inter = Inter({
  subsets: ["latin"],
  style: ["normal", "italic"],
  variable: "--font-inter",
  display: "swap",
});

const siteName = "static-to-variable";
const title = "Turn static fonts into one variable font";
const description =
  "Turn static font files into one variable font with every weight in between. Upload thin, regular, and bold weights online, then download TTF and WOFF2 files.";

export const metadata: Metadata = {
  metadataBase: new URL("https://variable.blode.co"),
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
  openGraph: {
    title,
    description,
    type: "website",
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
      <body className="min-h-dvh antialiased">{children}</body>
      {process.env.NODE_ENV === "production" ? (
        <GoogleAnalytics gaId="G-1E6KD4YTJ8" />
      ) : null}
    </html>
  );
}
