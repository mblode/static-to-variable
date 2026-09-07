import type { MetadataRoute } from "next";

import { siteUrl } from "@/lib/config";
import { FONTS } from "@/lib/fonts";

const BASE = siteUrl;

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: BASE,
      changeFrequency: "monthly",
      priority: 1,
    },
    {
      url: `${BASE}/showcase`,
      changeFrequency: "monthly",
      priority: 0.8,
    },
    ...FONTS.map((font) => ({
      url: `${BASE}/showcase/${font.id}`,
      changeFrequency: "monthly" as const,
      priority: 0.6,
    })),
  ];
}
