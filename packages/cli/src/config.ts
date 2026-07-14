import { existsSync, readFileSync } from "node:fs";
import nodePath from "node:path";

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

interface RawConfig {
  version?: unknown;
  id?: unknown;
  family?: { name?: unknown };
  styles?: Record<string, unknown>;
  output?: { dir?: unknown; releaseDir?: unknown; formats?: unknown };
}

function requireString(value: unknown, label: string, path: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${path}: ${label} must be a non-empty string`);
  }
  return value;
}

/**
 * Read an stv.config.json (schema v3) and expose the fields the CLI needs.
 * Dependency-free and read-only; throws Error with a clear message on any
 * missing file or invalid field.
 */
export function loadProjectConfig(path: string): ProjectConfigSummary {
  let contents: string;
  try {
    contents = readFileSync(path, "utf-8");
  } catch (error) {
    throw new Error(`${path}: config file not found`, { cause: error });
  }

  let raw: RawConfig;
  try {
    raw = JSON.parse(contents) as RawConfig;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`${path}: invalid JSON: ${detail}`, { cause: error });
  }

  if (raw.version !== 3) {
    throw new Error(
      `${path}: expected version 3, got ${JSON.stringify(raw.version)}`
    );
  }

  const id = requireString(raw.id, "id", path);
  const familyName = requireString(raw.family?.name, "family.name", path);

  if (typeof raw.styles !== "object" || raw.styles === null) {
    throw new Error(`${path}: styles must be an object`);
  }
  const styleKeys = Object.keys(raw.styles).toSorted();
  if (styleKeys.length === 0) {
    throw new Error(`${path}: at least one style is required`);
  }

  if (typeof raw.output !== "object" || raw.output === null) {
    throw new Error(`${path}: output must be an object`);
  }
  const outputDir = requireString(raw.output.dir, "output.dir", path);
  const releaseDir = requireString(
    raw.output.releaseDir,
    "output.releaseDir",
    path
  );
  if (!Array.isArray(raw.output.formats) || raw.output.formats.length === 0) {
    throw new Error(`${path}: output.formats must be a non-empty array`);
  }
  const formats = raw.output.formats.map((fmt, index) =>
    requireString(fmt, `output.formats[${index}]`, path)
  );

  return { id, familyName, outputDir, releaseDir, styleKeys, formats };
}
