import type { MetadataRoute } from "next";

import { FONTS } from "@/lib/fonts";

const BASE = "https://variable.blode.co";

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();

  return [
    {
      url: BASE,
      lastModified,
      changeFrequency: "monthly",
      priority: 1,
    },
    ...FONTS.map((font) => ({
      url: `${BASE}/showcase/${font.id}`,
      lastModified,
      changeFrequency: "monthly" as const,
      priority: 0.6,
    })),
  ];
}
