import { renderZoneOgImage } from "@/app/og-image-shared";
import { OgLogo } from "@/app/og-logo";

export {
  OG_CONTENT_TYPE as contentType,
  OG_SIZE as size,
} from "@/app/og-image-shared";

export const alt = "Static to Variable: static fonts into one variable font";

/**
 * The house card (Rule 12). The dark card this replaces carried a weight-axis
 * motif and 68px type in the next/og default face, which meant the one project
 * on this site that is about typography was the one shipping a card set in a
 * typeface nobody chose.
 */
export default function OpengraphImage() {
  return renderZoneOgImage({
    background: "#f5f0e6",
    color: "#1a1510",
    logo: <OgLogo />,
    title: "Static to Variable",
  });
}
