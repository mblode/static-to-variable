import type {
  CellScores,
  GlyphScores,
  StrategySuggestion,
} from "@static-to-variable/glyph-forge-engine";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { CIRCULAR_WEIGHTS, cellKey } from "@/lib/data";
import type { Family } from "@/lib/data";
import {
  loadCellScores,
  loadGlyphScores,
  loadManifest,
  loadSuggestions,
} from "@/lib/data.server";

interface Params {
  family: string;
  name: string;
}

function asFamily(x: string): Family | null {
  return x === "roman" || x === "italic" ? x : null;
}

async function svgInline(
  origin: string,
  family: Family,
  name: string,
  wght: number,
  source: "donor" | "glide"
): Promise<string | null> {
  try {
    const url = new URL(
      `/svg/${family}/${encodeURIComponent(name)}/${wght}-${source}.svg`,
      origin
    );
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      return null;
    }
    return await response.text();
  } catch {
    return null;
  }
}

function scoreBadge(composite: number | null | undefined): {
  label: string;
  color: string;
} {
  if (composite === null || composite === undefined) {
    return { label: "—", color: "#666" };
  }
  const pct = Math.round(composite * 100);
  if (composite < 0.3) {
    return { label: `${pct}`, color: "#e04e5e" };
  }
  if (composite < 0.7) {
    return { label: `${pct}`, color: "#f0a020" };
  }
  return { color: "#3ba963", label: `${pct}` };
}

function escapeHtml(s: string): string {
  return s.replaceAll(/[&<>"']/g, (c) =>
    c === "&"
      ? "&amp;"
      : c === "<"
        ? "&lt;"
        : c === ">"
          ? "&gt;"
          : c === '"'
            ? "&quot;"
            : "&#39;"
  );
}

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<Params> }
) {
  const { family: rawFamily, name: rawName } = await params;
  const family = asFamily(rawFamily);
  if (!family) {
    return NextResponse.json({ error: "bad family" }, { status: 400 });
  }
  const name = decodeURIComponent(rawName);

  const [manifest, glyphScores, cellScores, suggestions] = await Promise.all([
    loadManifest(),
    loadGlyphScores(),
    loadCellScores(),
    loadSuggestions(),
  ]);

  const entry = manifest.find((g) => g.family === family && g.name === name);
  if (!entry) {
    return NextResponse.json({ error: "glyph not found" }, { status: 404 });
  }

  const aggregate: GlyphScores | undefined = glyphScores?.[`${family}/${name}`];
  const suggestion: StrategySuggestion | undefined =
    suggestions?.[`${family}/${name}`];

  const cellRows = await Promise.all(
    CIRCULAR_WEIGHTS.map(async (w) => {
      const donor = await svgInline(
        req.nextUrl.origin,
        family,
        name,
        w.wght,
        "donor"
      );
      const glide = await svgInline(
        req.nextUrl.origin,
        family,
        name,
        w.wght,
        "glide"
      );
      const s: CellScores | undefined =
        cellScores?.[cellKey(family, name, w.wght)];
      return { donor, glide, s, w };
    })
  );

  const title = `${family}/${name} — Static to Variable export`;
  const worst = aggregate?.worstComposite ?? null;
  const worstBadge = scoreBadge(worst);

  const rowHtml = (
    source: "donor" | "glide" | "overlay",
    label: string,
    color: string
  ) => {
    const cells = cellRows
      .map(({ w, donor, glide, s }) => {
        const inner =
          source === "overlay"
            ? `<div class="overlay">${donor ?? ""}${glide ?? ""}</div>`
            : ((source === "donor" ? donor : glide) ??
              '<span class="empty">—</span>');
        const scoreTag =
          source === "overlay" && s
            ? `<span class="score" style="color:${scoreBadge(s.composite).color}">${scoreBadge(s.composite).label}</span>`
            : "";
        return `
          <div class="cell">
            <div class="art ${source}">${scoreTag}${inner}</div>
            <div class="label">${w.name} · ${w.wght}</div>
          </div>`;
      })
      .join("");
    return `
      <section class="row">
        <header><span class="dot" style="background:${color}"></span>${label}</header>
        <div class="strip">${cells}</div>
      </section>`;
  };

  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>${escapeHtml(title)}</title>
<style>
  :root {
    --bg:#111; --fg:#eee; --dim:#777; --surface:#191919; --border:#2a2a2a;
    --donor:#8097a9; --glide:#f0a020;
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.4 ui-sans-serif, system-ui, sans-serif; }
  header.top { padding:20px 32px; border-bottom:1px solid var(--border); }
  header.top h1 { margin:0; font:500 22px/1.2 ui-monospace, monospace; }
  header.top .meta { color:var(--dim); font:12px/1.5 ui-monospace, monospace; margin-top:4px; }
  .worst { display:inline-block; padding:2px 8px; border-radius:4px; font:500 12px ui-monospace; background:${worstBadge.color}20; color:${worstBadge.color}; margin-left:8px; }
  main { padding: 20px 32px; display: grid; gap: 24px; grid-template-columns: 1fr 280px; max-width: 1600px; margin: 0 auto; }
  section.row header { display:flex; align-items:center; gap:8px; font:600 11px/1 ui-monospace, monospace; color:var(--dim); text-transform:uppercase; letter-spacing:0.1em; margin-bottom:10px; }
  .dot { width:8px; height:8px; border-radius:50%; display:inline-block; }
  .strip { display:grid; grid-template-columns: repeat(8, 1fr); gap:10px; }
  .cell { display:flex; flex-direction:column; gap:6px; }
  .art { position:relative; aspect-ratio:1/1; background:#00000060; border-radius:4px; padding:12px; }
  .art.donor svg { color: var(--donor); width:100%; height:100%; display:block; }
  .art.glide svg { color: var(--glide); width:100%; height:100%; display:block; }
  .art.overlay { position:relative; }
  .art.overlay .overlay { position:relative; width:100%; height:100%; }
  .art.overlay svg { position:absolute; inset:0; width:100%; height:100%; display:block; mix-blend-mode: screen; }
  .art.overlay svg:first-child { color: var(--donor); opacity:0.6; }
  .art.overlay svg:last-child  { color: var(--glide); opacity:0.8; }
  .score { position:absolute; top:4px; right:4px; padding:1px 6px; border-radius:3px; background:#000000a0; font:500 11px ui-monospace; }
  .label { text-align:center; font:500 10px/1 ui-monospace; color:var(--dim); }
  .empty { display:flex; align-items:center; justify-content:center; height:100%; color:var(--dim); font:10px ui-monospace; }
  aside { display:flex; flex-direction:column; gap:12px; }
  aside .card { border:1px solid var(--border); background:var(--surface); border-radius:8px; padding:14px; }
  aside h2 { font:600 11px ui-monospace; color:var(--dim); text-transform:uppercase; letter-spacing:0.1em; margin:0 0 6px; }
  aside .row2 { display:flex; gap:6px; flex-wrap:wrap; font:500 12px ui-monospace; color:var(--fg); }
  aside .reason { font-size:12px; line-height:1.55; color:#bbb; }
  @media print { body { background:#fff; color:#000; } .art { background:#00000010; } }
</style>
</head>
<body>
<header class="top">
  <h1>${escapeHtml(family)}/${escapeHtml(name)} ${worst === null ? "" : `<span class="worst">worst ${worstBadge.label}</span>`}</h1>
  <div class="meta">
    ${entry.unicode ?? ""}
    ${entry.features.length ? `· ${entry.features.join(" · ")}` : ""}
    ${entry.auditVerdict ? `· verdict ${entry.auditVerdict}` : ""}
    ${entry.severityScore === undefined ? "" : `· severity ${entry.severityScore}`}
    ${aggregate?.avgComposite !== null && aggregate?.avgComposite !== undefined ? `· avg ${Math.round(aggregate.avgComposite * 100)}` : ""}
  </div>
</header>
<main>
  <div>
    ${rowHtml("donor", "Circular donor", "#8097a9")}
    ${rowHtml("glide", "Glide instance", "#f0a020")}
    ${rowHtml("overlay", "Overlay + score", "#888")}
  </div>
  <aside>
    ${
      suggestion
        ? `<div class="card">
             <h2>Suggested strategy</h2>
             <div class="row2" style="color:${suggestion.strategy === "manual_review" ? "#e04e5e" : "#3ba963"}">${escapeHtml(suggestion.strategy)}<span style="color:var(--dim)">· ${Math.round(suggestion.confidence * 100)}%</span></div>
             <p class="reason">${escapeHtml(suggestion.reason)}</p>
           </div>`
        : ""
    }
    ${
      entry.existingStrategy
        ? `<div class="card">
             <h2>Current strategy</h2>
             <div class="row2">${escapeHtml(entry.existingStrategy)}</div>
             ${entry.notes ? `<p class="reason">${escapeHtml(entry.notes)}</p>` : ""}
           </div>`
        : ""
    }
    <div class="card">
      <h2>Origin</h2>
      <div class="row2">${entry.sources.map((s) => escapeHtml(s)).join(" · ")}</div>
    </div>
  </aside>
</main>
</body></html>`;

  return new NextResponse(html, {
    headers: {
      "content-disposition": `attachment; filename="glyph-forge-${family}-${name}.html"`,
      "content-type": "text/html; charset=utf-8",
    },
  });
}
