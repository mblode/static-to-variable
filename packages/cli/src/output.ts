/**
 * Output helpers that respect TTY/pipe conventions.
 *
 * - Color only when stdout is a TTY and NO_COLOR is unset.
 * - Human progress and logs go to stderr, so a piped stdout stays clean.
 * - Machine output (--json) goes to stdout as a single JSON document.
 */
import { styleText } from "node:util";

type Style = Parameters<typeof styleText>[0];

/** Whether ANSI color should be emitted on stdout. */
export function colorEnabled(): boolean {
  return Boolean(process.stdout.isTTY) && !process.env.NO_COLOR;
}

/** Apply a style only when color is enabled; otherwise return the raw text. */
export function color(style: Style, text: string): string {
  return colorEnabled() ? styleText(style, text) : text;
}

/** Write a human-facing progress/log line to stderr (never stdout). */
export function progress(line: string): void {
  process.stderr.write(`${line}\n`);
}

/** Write a machine-readable JSON document to stdout. */
export function emitJson(value: unknown): void {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

/** Print a typed error to stderr as `error [CODE]: message` + optional fix. */
export function printError(
  message: string,
  options: { code?: string; fix?: string } = {}
): void {
  const label = options.code ? `error [${options.code}]` : "error";
  process.stderr.write(`${color("red", label)}: ${message}\n`);
  if (options.fix) {
    process.stderr.write(`${color("cyan", "fix")}: ${options.fix}\n`);
  }
}
