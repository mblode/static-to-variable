import { ImageResponse } from "next/og";

import { FONTS } from "@/lib/fonts";

export const alt =
  "A Google Fonts family rebuilt from static weights into one variable font";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export function generateStaticParams() {
  return FONTS.map((font) => ({ family: font.id }));
}

// Per-family OG card, matching the site's dark, mono-eyebrow style. Uses the
// next/og default font (the family's own woff2 is not embedded), so the family
// is named rather than shown, with the weight axis as the visual motif.
export default async function Image({
  params,
}: {
  params: Promise<{ family: string }>;
}) {
  const { family } = await params;
  const font = FONTS.find((f) => f.id === family);
  const name = font?.name ?? "Variable font";
  const min = font?.axis.min ?? 100;
  const max = font?.axis.max ?? 900;
  const ticks = [100, 200, 300, 400, 500, 600, 700, 800, 900].filter(
    (t) => t >= min && t <= max
  );

  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        backgroundColor: "#0a0a0a",
        color: "#fafafa",
        padding: "72px",
      }}
    >
      <div
        style={{
          fontSize: 26,
          letterSpacing: "0.02em",
          color: "#8a8a8a",
        }}
      >
        static-to-variable / showcase
      </div>

      <div style={{ display: "flex", flexDirection: "column" }}>
        <div
          style={{
            fontSize: 96,
            fontWeight: 700,
            lineHeight: 1.02,
            letterSpacing: "-0.03em",
          }}
        >
          {name}
        </div>
        <div
          style={{
            marginTop: 20,
            fontSize: 32,
            lineHeight: 1.3,
            color: "#a1a1a1",
            maxWidth: 940,
          }}
        >
          {font
            ? `${font.category}. Static-only on Google Fonts, rebuilt into one variable font.`
            : "Static weights rebuilt into one variable font."}
        </div>
      </div>

      {/* Weight-axis motif: a thin→bold gradient bar with named stops. */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div
          style={{
            display: "flex",
            height: 16,
            borderRadius: 999,
            background: "linear-gradient(90deg, #3a3a3a 0%, #fafafa 100%)",
          }}
        />
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 22,
            color: "#6a6a6a",
          }}
        >
          {ticks.map((tick) => (
            <span key={tick}>{tick}</span>
          ))}
        </div>
      </div>
    </div>,
    size
  );
}
