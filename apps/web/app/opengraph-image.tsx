import { ImageResponse } from "next/og";

export const alt =
  "static-to-variable: turn a family of static weights into one variable font";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Neutral, dark, mono-eyebrow card matching the site. Uses the default
// font (next/og cannot embed the Glide .woff2), so brand comes from
// layout and a weight-axis motif rather than the typeface itself.
export default function OpengraphImage() {
  const ticks = [100, 200, 300, 400, 500, 600, 700, 800, 900];

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
        static-to-variable
      </div>

      <div style={{ display: "flex", flexDirection: "column" }}>
        <div
          style={{
            fontSize: 68,
            fontWeight: 700,
            lineHeight: 1.05,
            letterSpacing: "-0.02em",
            maxWidth: 940,
          }}
        >
          Turn a family of static weights into one variable font.
        </div>
        <div
          style={{
            marginTop: 24,
            fontSize: 30,
            lineHeight: 1.3,
            color: "#a1a1a1",
            maxWidth: 900,
          }}
        >
          Rebuilt onto a shared structure so they interpolate. Every glyph
          verified, nothing faked.
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
