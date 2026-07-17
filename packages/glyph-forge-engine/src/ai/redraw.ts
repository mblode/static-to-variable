import { generateObject, jsonSchema } from "ai";

/**
 * AI escape hatch for glyph reconstruction.
 *
 * When the deterministic `reconstruct()` in variable-gen cannot reconcile a
 * glyph's static masters into an interpolation-compatible structure, that glyph
 * is otherwise frozen (pinned to the default master, so it can't vary in
 * weight). This redraws it instead: an LLM re-expresses every master's outline
 * onto ONE shared point structure (the default master's), so the masters
 * interpolate. The model only supplies per-master coordinates — the reference
 * segment ops are reattached in code, which guarantees the result is
 * structurally compatible regardless of what the model returns.
 *
 * Routed through the Vercel AI Gateway (bare `provider/model` string,
 * authenticated with `AI_GATEWAY_API_KEY`); no per-provider SDK/key needed.
 */

export type Point = [number, number];

/** One drawing segment: op plus its points, matching variable-gen's contour form. */
export interface Segment {
  op: "moveTo" | "lineTo" | "curveTo" | "qCurveTo" | "closePath" | "endPath";
  points: Point[];
}

export interface Contour {
  segments: Segment[];
}

export interface MasterOutline {
  /** Axis position (e.g. wght) this master sits at. */
  pos: number;
  contours: Contour[];
}

export interface RedrawJob {
  glyph: string;
  unitsPerEm: number;
  /** The master whose structure every other master is redrawn onto. */
  referencePos: number;
  masters: MasterOutline[];
  /** Optional per-master PNG data URLs so the model can see each target shape. */
  images?: { pos: number; dataUrl: string }[];
}

export interface RedrawResult {
  glyph: string;
  /** Masters sharing the reference structure — safe to interpolate. */
  masters: MasterOutline[];
}

const MODEL = process.env.STV_AI_MODEL ?? "anthropic/claude-opus-4-8";

/** Flat, ordered list of the movable points in a contour (drops closePath/endPath). */
function contourPointCount(contour: Contour): number {
  let n = 0;
  for (const seg of contour.segments) {
    if (seg.op === "closePath" || seg.op === "endPath") {
      continue;
    }
    n += seg.points.length;
  }
  return n;
}

/** The reference structure: per-contour segment ops and how many points each takes. */
function referenceStructure(reference: MasterOutline) {
  return reference.contours.map((c) => ({
    ops: c.segments.map((s) => ({ op: s.op, count: s.points.length })),
    pointCount: contourPointCount(c),
  }));
}

/** Reattach the reference ops to a flat per-contour coordinate list. */
function rebuildContours(
  reference: MasterOutline,
  contourPoints: Point[][]
): Contour[] {
  return reference.contours.map((c, ci) => {
    const flat = contourPoints[ci] ?? [];
    let cursor = 0;
    const segments: Segment[] = c.segments.map((s) => {
      if (s.op === "closePath" || s.op === "endPath") {
        return { op: s.op, points: [] };
      }
      const pts = flat.slice(cursor, cursor + s.points.length);
      cursor += s.points.length;
      return { op: s.op, points: pts };
    });
    return { segments };
  });
}

export class AiRedrawError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AiRedrawError";
  }
}

/**
 * Redraw every master onto the reference master's structure. Returns compatible
 * masters, or throws `AiRedrawError` (caller falls back to freezing the glyph).
 */
export async function redrawGlyph(job: RedrawJob): Promise<RedrawResult> {
  if (!process.env.AI_GATEWAY_API_KEY && !process.env.VERCEL_OIDC_TOKEN) {
    throw new AiRedrawError(
      "AI_GATEWAY_API_KEY is not set — cannot reach the Vercel AI Gateway."
    );
  }
  const reference =
    job.masters.find((m) => m.pos === job.referencePos) ?? job.masters[0];
  if (!reference) {
    throw new AiRedrawError(`glyph ${job.glyph}: no masters in job`);
  }
  const structure = referenceStructure(reference);
  const totalPoints = structure.reduce((n, c) => n + c.pointCount, 0);

  // Flat coordinate list per master ([x0,y0,x1,y1,...] over all contours in
  // reference order): the structure is reattached in code so the result is
  // always interpolation-compatible regardless of what the model emits. Uses a
  // raw JSON Schema with an explicit type (not zod) so the AI SDK doesn't
  // recurse into a nested schema type (TS2589).
  const schema = jsonSchema<{ masters: { pos: number; coords: number[] }[] }>({
    type: "object",
    additionalProperties: false,
    required: ["masters"],
    properties: {
      masters: {
        type: "array",
        items: {
          type: "object",
          additionalProperties: false,
          required: ["pos", "coords"],
          properties: {
            pos: { type: "number" },
            coords: { type: "array", items: { type: "number" } },
          },
        },
      },
    },
  });

  const { object } = await generateObject({
    model: MODEL,
    schema,
    system:
      "You are a type engineer reconciling incompatible font masters for variable-font interpolation. " +
      "You re-express each weight's outline onto ONE shared point structure so the masters interpolate cleanly. " +
      "Preserve each master's actual shape and weight; only move points to sit on the shared structure. " +
      "Coordinates are in font units; y is up.",
    prompt: buildPrompt(job, reference, structure, totalPoints),
  });

  const byPos = new Map<number, number[]>(
    object.masters.map((m: { pos: number; coords: number[] }) => [
      m.pos,
      m.coords,
    ])
  );
  const outMasters: MasterOutline[] = [];
  for (const master of job.masters) {
    const coords = byPos.get(master.pos);
    if (!coords || coords.length !== totalPoints * 2) {
      throw new AiRedrawError(
        `glyph ${job.glyph}: master ${master.pos} returned ${coords?.length ?? 0}/${totalPoints * 2} coords`
      );
    }
    const contourPoints: Point[][] = [];
    let idx = 0;
    for (const c of structure) {
      const pts: Point[] = [];
      for (let k = 0; k < c.pointCount; k += 1) {
        pts.push([coords[idx * 2], coords[idx * 2 + 1]]);
        idx += 1;
      }
      contourPoints.push(pts);
    }
    outMasters.push({
      pos: master.pos,
      contours: rebuildContours(reference, contourPoints),
    });
  }
  return { glyph: job.glyph, masters: outMasters };
}

function buildPrompt(
  job: RedrawJob,
  reference: MasterOutline,
  structure: ReturnType<typeof referenceStructure>,
  totalPoints: number
): string {
  const structureLines = structure
    .map(
      (c, i) =>
        `  contour ${i}: ${c.pointCount} points — segments [${c.ops
          .map((o) => `${o.op}(${o.count})`)
          .join(", ")}]`
    )
    .join("\n");
  return [
    `Glyph "${job.glyph}", unitsPerEm ${job.unitsPerEm}.`,
    `These static masters were drawn independently and do NOT share a point structure, so they cannot interpolate.`,
    `Redraw EVERY master onto the reference structure below (from the pos=${job.referencePos} master):`,
    structureLines,
    ``,
    `For each master, return "coords": a FLAT array of exactly ${totalPoints * 2} numbers — the x,y of each of the ${totalPoints} points, contour by contour in the order above (contour 0's points first, then contour 1's, ...). Place points to reproduce THIS master's shape and weight (heavier masters have thicker strokes and smaller counters) while lying on the shared structure. Do not change the point count.`,
    ``,
    `Reference master (pos=${job.referencePos}) points per contour:`,
    ...reference.contours.map(
      (c, i) => `  contour ${i}: ${JSON.stringify(flatten(c))}`
    ),
    ``,
    `Original per-master outlines to reproduce (segment ops may differ from the reference — that is the incompatibility you are resolving):`,
    ...job.masters.map(
      (m) =>
        `  pos ${m.pos}: ${JSON.stringify(m.contours.map((c) => flatten(c)))}`
    ),
  ].join("\n");
}

function flatten(contour: Contour): Point[] {
  const pts: Point[] = [];
  for (const seg of contour.segments) {
    if (seg.op === "closePath" || seg.op === "endPath") {
      continue;
    }
    pts.push(...seg.points);
  }
  return pts;
}
