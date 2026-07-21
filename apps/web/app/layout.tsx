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

const title = "static-to-variable";
const description =
  "Turn separate font weight files into one variable font you can slide between. Try it on real Google Fonts that never had a variable version.";

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
    <html className={cn("dark font-sans", inter.variable)} lang="en">
      <body className="min-h-dvh antialiased">{children}</body>
      {process.env.NODE_ENV === "production" ? (
        <GoogleAnalytics gaId="G-1E6KD4YTJ8" />
      ) : null}
    </html>
  );
}
