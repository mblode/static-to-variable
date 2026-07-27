import type { MetadataRoute } from "next";

import { siteUrl } from "@/lib/config";
import { FONTS } from "@/lib/fonts";

const BASE = siteUrl;

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();

  return [
    {
      url: BASE,
      lastModified,
      changeFrequency: "monthly",
      priority: 1,
    },
    {
      url: `${BASE}/showcase`,
      lastModified,
      changeFrequency: "monthly",
      priority: 0.8,
    },
    ...FONTS.map((font) => ({
      url: `${BASE}/showcase/${font.id}`,
      lastModified,
      changeFrequency: "monthly" as const,
      priority: 0.6,
    })),
  ];
}
