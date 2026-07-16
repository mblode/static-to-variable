import { existsSync, readFileSync } from "node:fs";
import nodePath from "node:path";

import { Ajv2020 } from "ajv/dist/2020.js";
import type { ErrorObject, ValidateFunction } from "ajv/dist/2020.js";

import schema from "../../../schemas/stv-config.schema.json" with { type: "json" };
import { CliError, ExitCode } from "./errors.js";

/**
 * Resolve which config to use: an explicit path, else `stv.config.json` in the
 * current directory. Throws a typed error (with a fix) when neither is found.
 */
export function resolveConfigPath(explicit?: string): string {
  if (explicit) {
    if (!existsSync(explicit)) {
      throw new CliError(
        "STV_CONFIG_NOT_FOUND",
        `Config not found: ${explicit}`,
        {
          fix: "Pass an existing --config path, or run `static-to-variable init` to create one.",
          exitCode: ExitCode.Usage,
        }
      );
    }
    return nodePath.resolve(explicit);
  }
  const cwdConfig = nodePath.resolve(process.cwd(), "stv.config.json");
  if (existsSync(cwdConfig)) {
    return cwdConfig;
  }
  throw new CliError(
    "STV_CONFIG_NOT_FOUND",
    "No stv.config.json in the current directory and no --config given.",
    {
      fix: "Run `static-to-variable init` to scaffold one, or pass --config <path>.",
      exitCode: ExitCode.Usage,
    }
  );
}

export interface ProjectConfigSummary {
  id: string;
  familyName: string;
  outputDir: string;
  releaseDir: string;
  styleKeys: string[];
  formats: string[];
}

/** The shape the schema guarantees for the fields the CLI reads. */
interface ValidatedConfig {
  version: number;
  id: string;
  family: { name: string };
  styles: Record<string, unknown>;
  output: { dir: string; releaseDir: string; formats: string[] };
}

// Compiled once per process; the schema is inlined into dist at build time, so
// the published CLI validates against the exact schema it was released with.
let compiledValidator: ValidateFunction | null = null;

function validator(): ValidateFunction {
  if (compiledValidator) {
    return compiledValidator;
  }
  const ajv = new Ajv2020({ allErrors: true });
  const compiled = ajv.compile(schema);
  compiledValidator = compiled;
  return compiled;
}

/** The first few schema violations as `path: message` lines. */
function formatSchemaErrors(
  errors: ErrorObject[] | null | undefined,
  limit = 5
): string {
  const lines = (errors ?? []).slice(0, limit).map((error) => {
    const at = error.instancePath || "(root)";
    const detail =
      error.keyword === "additionalProperties"
        ? `${error.message} ("${String(error.params.additionalProperty)}")`
        : error.message;
    return `${at}: ${detail}`;
  });
  const omitted = (errors?.length ?? 0) - lines.length;
  if (omitted > 0) {
    lines.push(`…and ${omitted} more`);
  }
  return lines.join("; ");
}

function invalidConfig(path: string, detail: string, fix: string): CliError {
  return new CliError("STV_CONFIG_INVALID", `${path}: ${detail}`, {
    exitCode: ExitCode.Usage,
    fix,
  });
}

/**
 * Read an stv.config.json (schema v3), validate it against the published JSON
 * schema, and expose the fields the CLI needs. Throws `STV_CONFIG_INVALID`
 * (exit 2) naming the offending path on any violation. Deeper semantic checks
 * (donor references, exactly one default master) live in the Python engine's
 * `variable_gen.config.load_config`.
 */
export function loadProjectConfig(path: string): ProjectConfigSummary {
  let contents: string;
  try {
    contents = readFileSync(path, "utf-8");
  } catch (error) {
    throw new CliError(
      "STV_CONFIG_NOT_FOUND",
      `${path}: config file not found`,
      {
        cause: error,
        exitCode: ExitCode.Usage,
        fix: "Pass an existing --config path, or run `static-to-variable init`.",
      }
    );
  }

  let raw: unknown;
  try {
    raw = JSON.parse(contents);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw invalidConfig(
      path,
      `invalid JSON: ${detail}`,
      "Fix the JSON syntax; a trailing comma or unquoted key is the usual culprit."
    );
  }

  const validate = validator();
  if (!validate(raw)) {
    throw invalidConfig(
      path,
      `config does not match the schema — ${formatSchemaErrors(validate.errors)}`,
      "See schemas/stv-config.schema.json for the full contract; examples/minimal/ has a small valid config."
    );
  }

  const config = raw as unknown as ValidatedConfig;
  return {
    familyName: config.family.name,
    formats: config.output.formats,
    id: config.id,
    outputDir: config.output.dir,
    releaseDir: config.output.releaseDir,
    styleKeys: Object.keys(config.styles).toSorted(),
  };
}
