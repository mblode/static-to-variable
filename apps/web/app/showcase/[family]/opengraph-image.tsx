import { renderZoneOgImage } from "@/app/og-image-shared";
import { FONTS } from "@/lib/fonts";

export {
  OG_CONTENT_TYPE as contentType,
  OG_SIZE as size,
} from "@/app/og-image-shared";

export const alt =
  "A Google Fonts family rebuilt from static weights into one variable font";

export function generateStaticParams() {
  return FONTS.map((font) => ({ family: font.id }));
}

/**
 * The house card (Rule 12), carrying the per-family facts the old card did.
 *
 * Worth being clear about why this one is not exempt the way blode.co's
 * per-post film backgrounds are: this was never a specimen. The family's own
 * woff2 is not embedded here, so the old card *named* the family in the
 * next/og default face rather than showing it. It was a divergent design, not
 * a different system, and it loses nothing by joining the house one.
 */
export default async function Image({
  params,
}: {
  params: Promise<{ family: string }>;
}) {
  const { family } = await params;
  const font = FONTS.find((f) => f.id === family);

  return renderZoneOgImage({
    badge: "SHOWCASE",
    eyebrow: "blode.co/static-to-variable/showcase",
    subtitle: font
      ? `Rebuilt from ${font.staticStyles ?? "static"} static styles into one variable font. Weight axis ${font.axis.min} to ${font.axis.max}.`
      : "Rebuilt from static styles into one variable font.",
    title: `${font?.name ?? "Variable font"} variable font`,
  });
}
