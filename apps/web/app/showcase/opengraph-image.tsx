import { renderZoneOgImage } from "@/app/og-image-shared";
import { OgLogo } from "@/app/og-logo";

export {
  OG_CONTENT_TYPE as contentType,
  OG_SIZE as size,
} from "@/app/og-image-shared";

export const alt = "Every family rebuilt as a variable font";

/**
 * `opengraph-image` files apply to their own segment, so the root card covers
 * `/` and the family card covers `/showcase/<family>`; without this one
 * `/showcase` would inherit the root card and claim to be the home page.
 */
export default function Image() {
  return renderZoneOgImage({
    background: "#f5f0e6",
    color: "#1a1510",
    logo: <OgLogo />,
    title: "Variable fonts that didn't exist",
  });
}
