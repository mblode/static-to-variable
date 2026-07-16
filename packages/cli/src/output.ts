/**
 * Output helpers that respect TTY/pipe conventions.
 *
 * - Color only when the DESTINATION stream is a TTY and NO_COLOR is unset —
 *   a piped stdout must never receive ANSI even while stderr is a terminal.
 * - Human progress and logs go to stderr, so a piped stdout stays clean.
 * - Machine output (--json) goes to stdout as a single JSON document.
 */
import { styleText } from "node:util";

type Style = Parameters<typeof styleText>[0];

/** Whether ANSI color should be emitted on the given stream. */
export function colorEnabledFor(stream: NodeJS.WriteStream): boolean {
  return Boolean(stream.isTTY) && !process.env.NO_COLOR;
}

/** Style text destined for stdout, only when stdout accepts color. */
export function color(style: Style, text: string): string {
  return colorEnabledFor(process.stdout) ? styleText(style, text) : text;
}

/** Style text destined for stderr, only when stderr accepts color. */
export function colorErr(style: Style, text: string): string {
  return colorEnabledFor(process.stderr) ? styleText(style, text) : text;
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
  process.stderr.write(`${colorErr("red", label)}: ${message}\n`);
  if (options.fix) {
    process.stderr.write(`${colorErr("cyan", "fix")}: ${options.fix}\n`);
  }
}
