/**
 * Resolves the Python interpreter that runs the font engine and invokes engine
 * subcommands (`python -m variable_gen.cli ...`).
 *
 * Two modes:
 * - checkout: inside a static-to-variable monorepo. The engine lives in
 *   packages/variable-gen and runs via the repo's uv-managed .venv (or
 *   `uv run` as a fallback), from the repo root.
 * - standalone: a globally installed CLI. The engine is bundled under ./engine
 *   (sibling of dist/) and provisioned into a managed venv under the user's
 *   data dir on first run; the engine runs from the user's current directory.
 */
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { CliError, ExitCode } from "./errors.js";
import { progress } from "./output.js";
import { spawnInherit } from "./proc.js";
import { tryFindRepoRoot } from "./runner.js";

export interface PythonEnv {
  /** Executable to spawn. */
  command: string;
  /** Args that precede the module invocation (e.g. `run python` for uv). */
  baseArgs: string[];
  /** Working directory the engine runs from. */
  cwd: string;
}

export type EngineMode = "checkout" | "standalone";

export interface ResolvedEngine {
  mode: EngineMode;
  pythonEnv: PythonEnv;
}

/** Bump when the bundled engine layout or install command changes. */
const ENGINE_MARKER_VERSION = "1";

/** True if `<cmd> --version` runs successfully. */
export function hasCommand(cmd: string): boolean {
  try {
    return spawnSync(cmd, ["--version"], { stdio: "ignore" }).status === 0;
  } catch {
    return false;
  }
}

/**
 * Resolve the interpreter for a repo checkout. Prefers the repo's `.venv`, falls
 * back to `uv run python`. Throws a typed environment error when neither is
 * present. (Standalone installs use {@link resolveEngine} instead.)
 */
export function resolvePythonEnv(): PythonEnv {
  const root = tryFindRepoRoot();
  if (!root) {
    // Not in a checkout: defer to standalone resolution.
    return resolveEngine().pythonEnv;
  }
  return checkoutPythonEnv(root);
}

function checkoutPythonEnv(root: string): PythonEnv {
  const repoVenv = path.join(
    root,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python"
  );
  if (existsSync(repoVenv)) {
    return { command: repoVenv, baseArgs: [], cwd: root };
  }
  if (hasCommand("uv")) {
    return { command: "uv", baseArgs: ["run", "python"], cwd: root };
  }
  throw new CliError(
    "STV_PYTHON_MISSING",
    "No Python environment found: the repo .venv is missing and `uv` is not on PATH.",
    {
      fix: "Run `npm run setup:python` (uv sync) from the repo root, or install uv (https://docs.astral.sh/uv/).",
      exitCode: ExitCode.Environment,
    }
  );
}

/**
 * Resolve the engine for the current context. In a checkout, uses the repo
 * .venv / uv. Standalone, locates the bundled engine and provisions (or reuses)
 * a managed venv, returning the interpreter inside it.
 */
export function resolveEngine(): ResolvedEngine {
  const root = tryFindRepoRoot();
  if (root) {
    return { mode: "checkout", pythonEnv: checkoutPythonEnv(root) };
  }
  const python = ensureEngineEnv();
  return {
    mode: "standalone",
    pythonEnv: { command: python, baseArgs: [], cwd: process.cwd() },
  };
}

/** Absolute path to the bundled engine dir (sibling of dist/). */
export function bundledEngineDir(): string {
  const moduleDir = path.dirname(fileURLToPath(import.meta.url));
  return path.join(moduleDir, "../engine");
}

/** Root of the managed-venv cache: $XDG_DATA_HOME/static-to-variable/envs. */
function engineDataRoot(): string {
  if (process.platform === "win32") {
    const base =
      process.env.LOCALAPPDATA ?? path.join(homedir(), "AppData", "Local");
    return path.join(base, "static-to-variable", "envs");
  }
  const base =
    process.env.XDG_DATA_HOME ?? path.join(homedir(), ".local", "share");
  return path.join(base, "static-to-variable", "envs");
}

/** Interpreter path inside a managed venv directory. */
function venvPython(venvDir: string): string {
  return path.join(
    venvDir,
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python"
  );
}

/**
 * Cache key for the bundled engine: a content hash of every engine source file
 * (.py / .toml) plus a marker version, so ANY engine change — not just a
 * pyproject bump — provisions a fresh venv and never reuses stale code.
 * Exported for tests.
 */
export function engineKey(engineDir: string): string {
  const hash = createHash("sha256").update(ENGINE_MARKER_VERSION).update("\0");
  let entries: string[] = [];
  try {
    entries = (readdirSync(engineDir, { recursive: true }) as string[])
      .filter((rel) => rel.endsWith(".py") || rel.endsWith(".toml"))
      .toSorted();
  } catch {
    // Engine dir missing/unreadable — fall back to a stable marker.
    return hash.update(engineDir).digest("hex").slice(0, 16);
  }
  for (const rel of entries) {
    const full = path.join(engineDir, rel);
    hash.update(rel).update("\0");
    try {
      hash.update(readFileSync(full));
    } catch {
      // Skip directories / unreadable entries.
    }
    hash.update("\0");
  }
  return hash.digest("hex").slice(0, 16);
}

export interface EngineEnvInfo {
  engineDir: string;
  venvDir: string;
  python: string;
  provisioned: boolean;
  uvPresent: boolean;
  engineBundled: boolean;
}

/** Report the standalone engine state without provisioning anything. */
export function inspectEngineEnv(): EngineEnvInfo {
  const engineDir = bundledEngineDir();
  const engineBundled = existsSync(
    path.join(engineDir, "variable-gen/pyproject.toml")
  );
  const venvDir = path.join(
    engineDataRoot(),
    engineBundled ? engineKey(engineDir) : "unbundled"
  );
  return {
    engineBundled,
    engineDir,
    provisioned:
      existsSync(path.join(venvDir, ".stv-ready")) &&
      existsSync(venvPython(venvDir)),
    python: venvPython(venvDir),
    uvPresent: hasCommand("uv"),
    venvDir,
  };
}

/**
 * Ensure a managed venv with the bundled engine installed, returning the
 * interpreter path. Reuses an existing provisioned venv; otherwise creates one
 * with `uv venv` + `uv pip install`. Idempotent and safe to call repeatedly.
 */
export function ensureEngineEnv(): string {
  const info = inspectEngineEnv();
  if (!info.engineBundled) {
    throw new CliError(
      "STV_ENGINE_NOT_BOOTSTRAPPED",
      `Bundled engine not found at ${info.engineDir}.`,
      {
        fix: "Reinstall static-to-variable; the package should ship an ./engine directory.",
        exitCode: ExitCode.Environment,
      }
    );
  }
  if (info.provisioned) {
    return info.python;
  }
  if (!info.uvPresent) {
    throw new CliError(
      "STV_PYTHON_MISSING",
      "`uv` is required to provision the Python engine on first run, but it is not on PATH.",
      {
        fix: "Install uv (https://docs.astral.sh/uv/), then rerun.",
        exitCode: ExitCode.Environment,
      }
    );
  }

  progress("Provisioning Python engine (first run)…");
  mkdirSync(path.dirname(info.venvDir), { recursive: true });

  runBootstrapStep("uv", ["venv", info.venvDir], "create the managed venv");
  runBootstrapStep(
    "uv",
    [
      "pip",
      "install",
      "--python",
      info.python,
      path.join(info.engineDir, "variable-gen"),
      path.join(info.engineDir, "glyph-forge-engine"),
    ],
    "install the engine into the managed venv"
  );

  writeFileSync(
    path.join(info.venvDir, ".stv-ready"),
    `${ENGINE_MARKER_VERSION}\n`
  );
  progress("Python engine ready.");
  return info.python;
}

function runBootstrapStep(command: string, args: string[], what: string): void {
  const result = spawnSync(command, args, {
    encoding: "utf-8",
    // Stream install progress to our stderr; keep stdout clean.
    stdio: ["ignore", "inherit", "pipe"],
  });
  if (result.status !== 0) {
    if (result.stderr) {
      process.stderr.write(result.stderr);
    }
    const tail = (result.stderr ?? "").trim().split("\n").slice(-8).join("\n");
    throw new CliError(
      "STV_ENGINE_BOOTSTRAP_FAILED",
      `Failed to ${what} (\`${command} ${args.join(" ")}\` exited ${result.status ?? "?"}).`,
      {
        cause: tail || undefined,
        exitCode: ExitCode.Environment,
        fix: "Check that uv can reach PyPI and build the engine's native deps, then rerun.",
      }
    );
  }
}

/** The interpreter's reported version string (e.g. "3.12.4"), or null. */
export function pythonVersion(env: PythonEnv): string | null {
  const result = spawnSync(env.command, [...env.baseArgs, "--version"], {
    cwd: env.cwd,
    encoding: "utf-8",
  });
  if (result.status !== 0) {
    return null;
  }
  const text = `${result.stdout ?? ""}${result.stderr ?? ""}`.trim();
  return text.replace(/^Python\s+/, "") || null;
}

/** Run an engine subcommand, inheriting stdio. Resolves to the exit code. */
export function runEngine(
  subcommand: string[],
  env: PythonEnv = resolveEngine().pythonEnv
): Promise<number> {
  return spawnInherit(
    env.command,
    [...env.baseArgs, "-m", "variable_gen.cli", ...subcommand],
    env.cwd
  );
}
