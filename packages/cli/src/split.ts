/**
 * `split` command: turn one variable font into static weight files by delegating
 * to the Python engine (`variable_gen.cli split`). The engine runs from its own
 * cwd (repo root in a checkout), not the user's, so paths are resolved to
 * absolute against the caller's cwd before they cross that boundary.
 */
import { existsSync } from "node:fs";
import path from "node:path";

import { CliError, ExitCode } from "./errors.js";
import { progress } from "./output.js";
import { runEngine, runEngineCapture } from "./python.js";

export interface SplitOptions {
  out?: string;
  step?: number;
  json?: boolean;
}

export interface SplitInvocation {
  fontPath: string;
  outDir: string;
  args: string[];
}

/**
 * Resolve the engine invocation for a split. Pure (no I/O): resolves the font
 * and output paths against `cwd` and builds the engine argv. Exported for tests.
 */
export function resolveSplitInvocation(
  font: string,
  options: SplitOptions,
  cwd: string
): SplitInvocation {
  const fontPath = path.resolve(cwd, font);
  const outDir = path.resolve(cwd, options.out ?? "./static");
  const args = [
    "split",
    "--input",
    fontPath,
    "--output",
    outDir,
    "--step",
    String(options.step ?? 100),
  ];
  if (options.json) {
    args.push("--json");
  }
  return { fontPath, outDir, args };
}

/**
 * Run a split, returning the engine's exit code. Async so the pre-flight
 * existsSync check surfaces as a promise rejection rather than a sync throw.
 */
export async function runSplit(
  font: string,
  options: SplitOptions
): Promise<number> {
  const { fontPath, outDir, args } = resolveSplitInvocation(
    font,
    options,
    process.cwd()
  );
  if (!existsSync(fontPath)) {
    throw new CliError("STV_INPUT_MISSING", `No such font: ${font}.`, {
      fix: "Pass the path to a variable .ttf or .otf file.",
      exitCode: ExitCode.Usage,
    });
  }
  progress(`Splitting ${path.basename(fontPath)} -> ${outDir}`);
  if (options.json) {
    // The engine's stdout is normally routed to our stderr; capture it so the
    // JSON summary lands on the CLI's stdout, keeping piped output clean.
    const { code, stdout } = await runEngineCapture(args);
    if (stdout) {
      process.stdout.write(stdout.endsWith("\n") ? stdout : `${stdout}\n`);
    }
    return code;
  }
  return await runEngine(args);
}
