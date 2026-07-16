import { existsSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

import {
  cancel,
  confirm,
  intro,
  isCancel,
  note,
  outro,
  select,
} from "@clack/prompts";
import { Command } from "commander";

import type { ProjectConfigSummary } from "./config.js";
import { loadProjectConfig, resolveConfigPath } from "./config.js";
import { CliError, ExitCode, isCliError } from "./errors.js";
import { INIT_CONFIG_TEMPLATE } from "./init-template.js";
import { emitJson, printError, progress } from "./output.js";
import type { EngineMode } from "./python.js";
import {
  hasCommand,
  inspectEngineEnv,
  pythonVersion,
  resolveEngine,
  resolvePythonEnv,
  runEngine,
} from "./python.js";
import {
  printPipelineStatus,
  readPipelineStatus,
  runStage,
  runStages,
  tryFindRepoRoot,
} from "./runner.js";
import {
  buildStagePlan,
  defaultStages,
  formatCommand,
  PIPELINE_STAGES,
  resolveStage,
  stageChoices,
} from "./stages.js";
import type {
  HandoffMode,
  PipelineStage,
  StagePlanOptions,
  StageRunResult,
  StatusPrintOptions,
} from "./types.js";

const pkg = createRequire(import.meta.url)("../package.json") as {
  version: string;
};

const program = new Command();

interface RunCommandOptions extends StagePlanOptions {
  continueOnFail?: boolean;
  dryRun?: boolean;
  failOnRed?: boolean;
  handoff?: HandoffMode;
  top?: number;
}

interface StepCommandOptions extends RunCommandOptions {
  yes?: boolean;
}

program
  .name("static-to-variable")
  .description(
    "Convert a family of static fonts into a variable font, guided by a config."
  )
  .version(pkg.version, "-V, --version")
  .action(async () => {
    if (process.stdin.isTTY) {
      const { results } = await stepPipeline({});
      process.exitCode = exitCodeFor(results);
      return;
    }
    // Non-TTY with no subcommand: don't block a pipe on a prompt.
    program.outputHelp();
    process.exitCode = ExitCode.Usage;
  });

program
  .command("list")
  .description("List available pipeline stages.")
  .action(() => {
    for (const stage of PIPELINE_STAGES) {
      const optional = stage.defaultEnabled === false ? " optional" : "";
      console.log(`${stage.id} (${stage.kind}${optional})`);
      console.log(`  ${stage.description}`);
      console.log(`  $ ${formatCommand(stage)}`);
      if (stage.artifact) {
        console.log(`  artifact: ${stage.artifact}`);
      }
    }
  });

program
  .command("run")
  .description("Run one stage or the default stage plan.")
  .argument("[stage]", "stage id, alias, or all", "all")
  .option("--from <stage>", "Start at a stage in the default plan.")
  .option("--to <stage>", "Stop at a stage in the default plan.")
  .option("--blocking-only", "Run only blocking gates plus final status.")
  .option("--skip-diagnostics", "Skip diagnostic stages.")
  .option(
    "--continue-on-fail",
    "Keep running later stages after a command exits non-zero."
  )
  .option("--dry-run", "Print commands without running them.")
  .option(
    "--fail-on-red",
    "Exit non-zero when final pipeline status verdict is fail."
  )
  .option(
    "--handoff <mode>",
    "Human handoff mode: prompt, auto, or off.",
    parseHandoff,
    "prompt"
  )
  .option(
    "--top <count>",
    "Number of review targets to print in the handoff block.",
    parseTop,
    5
  )
  .action(async (stageArg: string, options: RunCommandOptions) => {
    const stages = selectRunStages(stageArg, options);
    const results = await runStages(stages, options);
    const redFailure = options.dryRun
      ? false
      : printFinalStatusIfAvailable(stages, options);
    process.exitCode = exitCodeFor(
      results,
      Boolean(options.failOnRed) && redFailure
    );
  });

program
  .command("step")
  .description("Interactively step through the pipeline.")
  .option("--from <stage>", "Start at a stage in the default plan.")
  .option("--to <stage>", "Stop at a stage in the default plan.")
  .option("--blocking-only", "Run only blocking gates plus final status.")
  .option("--skip-diagnostics", "Skip diagnostic stages.")
  .option(
    "--continue-on-fail",
    "Keep prompting after a command exits non-zero."
  )
  .option("--dry-run", "Print commands without running them.")
  .option("--yes", "Run selected stages without per-stage confirmation.")
  .option(
    "--fail-on-red",
    "Exit non-zero when final pipeline status verdict is fail."
  )
  .option(
    "--handoff <mode>",
    "Human handoff mode: prompt, auto, or off.",
    parseHandoff,
    "prompt"
  )
  .option(
    "--top <count>",
    "Number of review targets to print in the handoff block.",
    parseTop,
    5
  )
  .action(async (options: StepCommandOptions) => {
    const { results, redFailure } = await stepPipeline(options);
    process.exitCode = exitCodeFor(
      results,
      Boolean(options.failOnRed) && redFailure
    );
  });

program
  .command("status")
  .description("Refresh and print the aggregate pipeline status report.")
  .option("--read", "Read the existing status report without regenerating it.")
  .option("--fail-on-red", "Exit non-zero when the pipeline verdict is fail.")
  .option(
    "--handoff <mode>",
    "Human handoff mode: prompt, auto, or off.",
    parseHandoff,
    "prompt"
  )
  .option(
    "--top <count>",
    "Number of review targets to print in the handoff block.",
    parseTop,
    5
  )
  .action(
    async (
      options: StatusPrintOptions & { failOnRed?: boolean; read?: boolean }
    ) => {
      if (!options.read) {
        const result = await runStage(resolveStage("pipeline_status"));
        if (result.code !== 0) {
          process.exitCode = result.code;
          return;
        }
      }
      const report = readPipelineStatus();
      printPipelineStatus(report, options);
      if (options.failOnRed && report.verdict !== "pass") {
        process.exitCode = 1;
      }
    }
  );

program
  .command("build")
  .description(
    "Build the variable font(s) from a config: rebuild -> normalize -> build."
  )
  .option(
    "--config <path>",
    "Path to stv.config.json (default: ./stv.config.json)."
  )
  .option("--style <key>", "Style key, or 'all'.", "all")
  .option("--check-only", "Skip building; only run the fidelity check.")
  .option(
    "--skip-rebuild",
    "Build from existing sources without re-deriving masters from donors."
  )
  .option("--json", "Emit a machine-readable build summary to stdout.")
  .action(async (options: BuildCommandOptions) => {
    const configPath = resolveConfigPath(options.config);
    const summary = loadProjectConfig(configPath);
    const style = options.style ?? "all";
    progress(
      `Building ${summary.familyName} [${style === "all" ? summary.styleKeys.join(", ") : style}]`
    );
    const env = resolveEngine().pythonEnv;
    // Matches the byte-parity-verified chain (build exports the designspace
    // internally, so it is not a separate step here).
    const steps = options.skipRebuild
      ? ["build"]
      : ["rebuild", "normalize", "build"];
    const stepResults: { step: string; code: number }[] = [];
    for (const step of steps) {
      const args = [step, "--config", configPath, "--style", style];
      if (step === "build" && options.checkOnly) {
        args.push("--check-only");
      }
      progress(`-> ${step}`);
      const code = await runEngine(args, env);
      stepResults.push({ code, step });
      if (code !== 0) {
        process.exitCode = code;
        break;
      }
    }
    if (options.json) {
      emitJson(engineRunSummary(summary, configPath, style, stepResults));
    }
  });

program
  .command("release")
  .description("Finalize metadata and emit the release TTF + WOFF2.")
  .option(
    "--config <path>",
    "Path to stv.config.json (default: ./stv.config.json)."
  )
  .option("--style <key>", "Style key, or 'all'.", "all")
  .option("--json", "Emit a machine-readable release summary to stdout.")
  .action(
    async (options: { config?: string; style?: string; json?: boolean }) => {
      const configPath = resolveConfigPath(options.config);
      const summary = loadProjectConfig(configPath);
      const style = options.style ?? "all";
      progress(
        `Releasing ${summary.familyName} [${style === "all" ? summary.styleKeys.join(", ") : style}]`
      );
      const code = await runEngine([
        "release",
        "--config",
        configPath,
        "--style",
        style,
      ]);
      if (code !== 0) {
        process.exitCode = code;
      }
      if (options.json) {
        emitJson(
          engineRunSummary(summary, configPath, style, [
            { code, step: "release" },
          ])
        );
      }
    }
  );

program
  .command("doctor")
  .description("Report environment readiness: node, python, uv, config.")
  .option("--json", "Emit a JSON report to stdout.")
  .action((options: { json?: boolean }) => {
    const report = doctorReport();
    if (options.json) {
      emitJson(report);
    } else {
      progress(`node:   ${report.node}`);
      progress(`mode:   ${report.mode}`);
      progress(`python: ${report.python ?? "not found"}`);
      progress(`uv:     ${report.uv ? "present" : "not found"}`);
      if (report.mode === "standalone" && report.engine) {
        progress(`engine: ${report.engine.dir}`);
        progress(
          `venv:   ${report.engine.venvDir} (${report.engine.provisioned ? "provisioned" : "not provisioned"})`
        );
      }
      progress(`config: ${report.config ?? "no ./stv.config.json"}`);
    }
    process.exitCode = report.usable ? ExitCode.Success : ExitCode.Environment;
  });

program
  .command("init")
  .description("Scaffold a starter stv.config.json in the current directory.")
  .option("--force", "Overwrite an existing stv.config.json.")
  .action((options: { force?: boolean }) => {
    scaffoldConfig(Boolean(options.force));
  });

// Register BEFORE parsing so rejections during command execution are caught —
// top-level await suspends module evaluation, so anything registered after
// parseAsync() would only exist once every command had already finished.
process.on("unhandledRejection", (error) => {
  reportError(error);
});

try {
  await program.parseAsync();
} catch (error) {
  reportError(error);
}

async function stepPipeline(
  options: StepCommandOptions
): Promise<{ results: StageRunResult[]; redFailure: boolean }> {
  intro("static-to-variable");

  const mode = await chooseMode(options);
  const planOptions = await optionsForMode(mode, options);
  const stages = buildStagePlan(planOptions);
  note(
    stages.map((stage) => `${stage.id} (${stage.kind})`).join("\n"),
    "Stage plan"
  );

  const shouldRun = options.yes
    ? true
    : await confirm({ initialValue: true, message: "Run this stage plan?" });
  if (isCancel(shouldRun) || !shouldRun) {
    cancel("No stages run.");
    return { redFailure: false, results: [] };
  }

  const results: StageRunResult[] = [];
  for (const stage of stages) {
    const confirmed = await confirmStage(stage, options);
    if (!confirmed) {
      continue;
    }

    const result = await runStage(stage, options);
    results.push(result);
    if (result.code !== 0 && !options.continueOnFail) {
      break;
    }
  }

  const redFailure = options.dryRun
    ? false
    : printFinalStatusIfAvailable(stages, options);
  outro("Pipeline stepper finished.");
  return { redFailure, results };
}

function selectRunStages(
  stageArg: string,
  options: RunCommandOptions
): PipelineStage[] {
  if (stageArg !== "all" && (options.from || options.to)) {
    throw new Error(
      "Use either a single stage argument or --from/--to, not both."
    );
  }
  if (stageArg === "all") {
    return buildStagePlan(options);
  }
  return [resolveStage(stageArg)];
}

async function chooseMode(options: StepCommandOptions): Promise<string> {
  if (options.blockingOnly) {
    return "blocking";
  }
  if (options.skipDiagnostics) {
    return "skip-diagnostics";
  }
  if (options.from || options.to) {
    return "range";
  }

  const mode = await select({
    message: "Choose a stage plan",
    options: [
      {
        hint: "Includes diagnostics and final status.",
        label: "Full default pipeline",
        value: "full",
      },
      {
        hint: "Inventory, repair, residuals, forge, status.",
        label: "Blocking gates only",
        value: "blocking",
      },
      {
        hint: "Refresh the aggregate status report.",
        label: "Status only",
        value: "status",
      },
      {
        hint: "Pick a stage and run forward from there.",
        label: "Start from stage",
        value: "from-stage",
      },
    ],
  });

  if (isCancel(mode)) {
    cancel("Cancelled.");
    process.exit(ExitCode.Interrupted);
  }
  return mode;
}

async function confirmStage(
  stage: PipelineStage,
  options: StepCommandOptions
): Promise<boolean> {
  if (options.yes) {
    return true;
  }

  const details = [
    stage.description,
    "",
    `$ ${formatCommand(stage)}`,
    stage.artifact ? `artifact: ${stage.artifact}` : undefined,
  ]
    .filter(Boolean)
    .join("\n");
  note(details, stage.title);

  if (stage.mutatesSources) {
    const mutate = await confirm({
      initialValue: false,
      message: `${stage.id} mutates glyph sources and build artifacts. Continue?`,
    });
    if (isCancel(mutate) || !mutate) {
      return false;
    }
  }

  const run = await confirm({
    initialValue: true,
    message: `Run ${stage.id}?`,
  });
  if (isCancel(run)) {
    cancel("Cancelled.");
    process.exit(ExitCode.Interrupted);
  }
  return run;
}

async function optionsForMode(
  mode: string,
  options: StepCommandOptions
): Promise<StagePlanOptions> {
  if (mode === "blocking") {
    return { ...options, blockingOnly: true };
  }
  if (mode === "skip-diagnostics") {
    return { ...options, skipDiagnostics: true };
  }
  if (mode === "status") {
    return { from: "pipeline_status", to: "pipeline_status" };
  }
  if (mode === "from-stage") {
    const defaultStageIds = new Set(defaultStages().map((stage) => stage.id));
    const stage = await select({
      message: "Start from which stage?",
      options: stageChoices().filter((choice) =>
        defaultStageIds.has(choice.value)
      ),
    });
    if (isCancel(stage)) {
      cancel("Cancelled.");
      process.exit(ExitCode.Interrupted);
    }
    return { from: stage };
  }
  return options;
}

/**
 * Print the aggregate status when the plan included the reporting stage.
 * Returns whether the pipeline verdict was red, so callers can decide the
 * exit code — this function never mutates `process.exitCode` itself.
 */
function printFinalStatusIfAvailable(
  stages: PipelineStage[],
  options: StatusPrintOptions
): boolean {
  if (!stages.some((stage) => stage.id === "pipeline_status")) {
    return false;
  }
  const report = readPipelineStatus();
  printPipelineStatus(report, options);
  return report.verdict !== "pass";
}

function exitCodeFor(results: StageRunResult[], redFailure = false): number {
  const failedCommand = results.find((result) => result.code !== 0);
  if (failedCommand) {
    return failedCommand.code;
  }
  return redFailure ? ExitCode.Failure : ExitCode.Success;
}

function parseHandoff(value: string): HandoffMode {
  if (value === "prompt" || value === "auto" || value === "off") {
    return value;
  }
  throw new CliError("STV_INVALID_OPTION", `Invalid handoff mode "${value}".`, {
    fix: "Use one of: prompt, auto, off.",
    exitCode: ExitCode.Usage,
  });
}

function parseTop(value: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) {
    throw new CliError(
      "STV_INVALID_OPTION",
      `Invalid --top count "${value}".`,
      {
        fix: "Use a positive integer.",
        exitCode: ExitCode.Usage,
      }
    );
  }
  return parsed;
}

interface EngineStepResult {
  step: string;
  code: number;
}

/** The machine-readable summary emitted by `build --json` / `release --json`. */
function engineRunSummary(
  summary: ProjectConfigSummary,
  configPath: string,
  style: string,
  steps: EngineStepResult[]
): Record<string, unknown> {
  return {
    config: configPath,
    family: summary.familyName,
    id: summary.id,
    ok: steps.every((entry) => entry.code === 0),
    outputDir: summary.outputDir,
    releaseDir: summary.releaseDir,
    steps,
    style,
    styles: summary.styleKeys,
  };
}

interface BuildCommandOptions {
  config?: string;
  style?: string;
  checkOnly?: boolean;
  skipRebuild?: boolean;
  json?: boolean;
}

interface DoctorReport {
  node: string;
  mode: EngineMode;
  python: string | null;
  /** Whether the engine can run (or be provisioned) in this environment. */
  usable: boolean;
  uv: boolean;
  config: string | null;
  engine?: {
    dir: string;
    bundled: boolean;
    venvDir: string;
    provisioned: boolean;
  };
}

function doctorReport(): DoctorReport {
  const uv = hasCommand("uv");
  let config: string | null = null;
  try {
    config = resolveConfigPath();
  } catch {
    config = null;
  }
  const repoRoot = tryFindRepoRoot();
  if (repoRoot) {
    let python: string | null = null;
    try {
      python = pythonVersion(resolvePythonEnv());
    } catch {
      python = null;
    }
    return {
      config,
      mode: "checkout",
      node: process.version,
      python,
      usable: python !== null,
      uv,
    };
  }

  // Standalone: report the bundled engine + managed venv without provisioning.
  const info = inspectEngineEnv();
  const python = info.provisioned
    ? pythonVersion({
        baseArgs: [],
        command: info.python,
        cwd: process.cwd(),
      })
    : null;
  return {
    config,
    engine: {
      bundled: info.engineBundled,
      dir: info.engineDir,
      provisioned: info.provisioned,
      venvDir: info.venvDir,
    },
    mode: "standalone",
    node: process.version,
    python,
    // Usable if already provisioned, or bundled + uv available to provision.
    usable: info.provisioned || (info.engineBundled && uv),
    uv,
  };
}

function scaffoldConfig(force: boolean): void {
  const target = path.resolve(process.cwd(), "stv.config.json");
  if (existsSync(target) && !force) {
    throw new CliError(
      "STV_CONFIG_EXISTS",
      `stv.config.json already exists at ${target}.`,
      {
        fix: "Edit it, or pass --force to overwrite.",
        exitCode: ExitCode.Usage,
      }
    );
  }
  writeFileSync(target, INIT_CONFIG_TEMPLATE);
  progress(`Wrote ${target}`);
  progress(
    "Edit family metadata, donor paths, and axis/masters, then run `static-to-variable build`."
  );
  progress(
    "Schema + a full worked example: schemas/stv-config.schema.json and examples/glide/."
  );
}

function reportError(error: unknown): void {
  if (isCliError(error)) {
    printError(error.message, { code: error.code, fix: error.fix });
    process.exitCode = error.exitCode;
    if (process.env.STV_VERBOSE && error.cause) {
      console.error(error.cause);
    }
    return;
  }
  printError(error instanceof Error ? error.message : String(error));
  process.exitCode = ExitCode.Failure;
}
