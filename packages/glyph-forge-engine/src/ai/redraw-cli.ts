#!/usr/bin/env node
import { readFileSync, writeFileSync } from "node:fs";

import { AiRedrawError, redrawGlyph } from "./redraw.js";
import type { RedrawJob } from "./redraw.js";

/**
 * Batch AI-redraw CLI, driven by variable-gen's `ai_redraw.py`.
 *
 *   tsx redraw-cli.ts <jobs.json> <out.json>
 *
 * Input:  { jobs: RedrawJob[] }
 * Output: { results: { glyph, ok, masters?, error? }[] }
 *
 * Never throws for a single-glyph failure — records `ok: false` so the pipeline
 * can freeze that glyph and keep the others. A non-zero exit means the whole
 * batch could not run (bad input, no gateway credentials).
 */
async function main(): Promise<void> {
  const [jobPath, outPath] = process.argv.slice(2);
  if (!jobPath || !outPath) {
    process.stderr.write("usage: redraw-cli <jobs.json> <out.json>\n");
    process.exit(2);
  }

  let jobs: RedrawJob[];
  try {
    ({ jobs } = JSON.parse(readFileSync(jobPath, "utf-8")) as {
      jobs: RedrawJob[];
    });
  } catch (error) {
    process.stderr.write(`failed to read jobs: ${String(error)}\n`);
    process.exit(2);
    return;
  }

  const results = await Promise.all(
    jobs.map(async (job) => {
      try {
        const { masters } = await redrawGlyph(job);
        return { glyph: job.glyph, ok: true as const, masters };
      } catch (error) {
        // A credential/config failure is fatal for the whole batch; a
        // per-glyph model failure just drops that glyph to a freeze.
        if (
          error instanceof AiRedrawError &&
          /AI_GATEWAY_API_KEY/.test(error.message)
        ) {
          throw error;
        }
        return {
          glyph: job.glyph,
          ok: false as const,
          error: error instanceof Error ? error.message : String(error),
        };
      }
    })
  );

  writeFileSync(outPath, JSON.stringify({ results }, null, 2));
  const redrawn = results.filter((r) => r.ok).length;
  process.stderr.write(
    `ai-redraw: ${redrawn}/${results.length} glyphs redrawn\n`
  );
}

main().catch((error) => {
  process.stderr.write(
    `ai-redraw failed: ${error instanceof Error ? error.message : String(error)}\n`
  );
  process.exit(1);
});
