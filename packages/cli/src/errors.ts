/**
 * Typed, developer-facing errors for the CLI.
 *
 * Every failure the user can hit carries a stable code, a message that names
 * the cause and the offending value, and (where possible) a concrete fix. The
 * top-level handler prints `error [CODE]: <message>` and `fix: <fix>` to stderr
 * and never surfaces a raw stack unless --verbose is set.
 */

/** Process exit codes, by failure class. */
export const ExitCode = {
  /** Everything succeeded. */
  Success: 0,
  /** A pipeline stage or the engine exited non-zero. */
  Failure: 1,
  /** The user invoked the CLI incorrectly (bad flag, unknown stage). */
  Usage: 2,
  /** The environment is not ready (no Python, engine not bootstrapped). */
  Environment: 3,
  /** Interrupted (SIGINT). */
  Interrupted: 130,
} as const;

export type ExitCodeValue = (typeof ExitCode)[keyof typeof ExitCode];

/** Stable, documentable error codes surfaced to users. */
export type CliErrorCode =
  | "STV_UNKNOWN_STAGE"
  | "STV_STAGE_RANGE_EMPTY"
  | "STV_STATUS_REPORT_MISSING"
  | "STV_WORKSPACE_NOT_FOUND"
  | "STV_CONFIG_NOT_FOUND"
  | "STV_CONFIG_INVALID"
  | "STV_CONFIG_EXISTS"
  | "STV_INPUT_MISSING"
  | "STV_PYTHON_MISSING"
  | "STV_ENGINE_NOT_BOOTSTRAPPED"
  | "STV_ENGINE_BOOTSTRAP_FAILED"
  | "STV_INVALID_OPTION";

export interface CliErrorOptions {
  /** Actionable next step, e.g. a command to run or a URL. */
  fix?: string;
  /** Process exit code to use; defaults by convention to Failure. */
  exitCode?: ExitCodeValue;
  /** Underlying error, preserved for --verbose. */
  cause?: unknown;
}

/**
 * An error with a stable code, an actionable fix, and an exit code. Throw this
 * (not a bare Error) anywhere a user could reasonably hit the failure.
 */
export class CliError extends Error {
  readonly code: CliErrorCode;
  readonly fix?: string;
  readonly exitCode: ExitCodeValue;

  constructor(
    code: CliErrorCode,
    message: string,
    options: CliErrorOptions = {}
  ) {
    super(
      message,
      options.cause === undefined ? undefined : { cause: options.cause }
    );
    this.name = "CliError";
    this.code = code;
    this.fix = options.fix;
    this.exitCode = options.exitCode ?? ExitCode.Failure;
  }
}

/** True when the value is one of our typed CLI errors. */
export function isCliError(value: unknown): value is CliError {
  return value instanceof CliError;
}
