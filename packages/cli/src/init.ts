/**
 * `static-to-variable init`: scaffold an stv.config.json.
 *
 * Interactive when stdin/stdout are TTYs and font files are found nearby: scan
 * the current directory for .ttf/.otf files, read each one's real weight and
 * names, confirm the selection, and write a config that builds without hand
 * editing. Otherwise (CI, agents, empty directory) fall back to the static
 * template in init-template.ts.
 */

import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import {
  cancel,
  intro,
  isCancel,
  multiselect,
  outro,
  text,
} from "@clack/prompts";

import { assertValidConfig } from "./config.js";
import { CliError, ExitCode } from "./errors.js";
import type { FontInfo } from "./font-inspect.js";
import { inspectFont } from "./font-inspect.js";
import { INIT_CONFIG_TEMPLATE } from "./init-template.js";
import { progress } from "./output.js";

/** A font file found near the working directory, with its parsed metadata. */
export interface FoundFont {
  /** Path relative to the working directory, as written into the config. */
  relPath: string;
  info: FontInfo;
}

const FONT_EXTENSIONS = new Set([".ttf", ".otf"]);
const SKIP_DIRS = new Set([".git", ".venv", "build", "dist", "node_modules"]);
const SCAN_DEPTH = 2;
const SCAN_CAP = 50;

/** Standard OS/2 weight-class names, used for master and instance names. */
const WEIGHT_NAMES: Record<number, string> = {
  100: "Thin",
  200: "ExtraLight",
  300: "Light",
  400: "Regular",
  500: "Medium",
  600: "SemiBold",
  700: "Bold",
  800: "ExtraBold",
  900: "Black",
};

function weightName(font: FoundFont): string {
  return WEIGHT_NAMES[font.info.weight] ?? font.info.style;
}

/**
 * Find .ttf/.otf files in `root` (two levels deep, skipping build and
 * dependency directories), parse each, and drop anything unreadable.
 */
export function scanFonts(root: string): FoundFont[] {
  const found: FoundFont[] = [];
  const walk = (dir: string, depth: number): void => {
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (found.length >= SCAN_CAP) {
        return;
      }
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (depth < SCAN_DEPTH && !SKIP_DIRS.has(entry.name)) {
          walk(full, depth + 1);
        }
        continue;
      }
      if (!FONT_EXTENSIONS.has(path.extname(entry.name).toLowerCase())) {
        continue;
      }
      try {
        found.push({
          info: inspectFont(readFileSync(full)),
          relPath: path.relative(root, full),
        });
      } catch {
        // Not a parseable font; leave it out rather than fail the scan.
      }
    }
  };
  walk(root, 0);
  return found.toSorted(
    (a, b) =>
      a.info.weight - b.info.weight || a.relPath.localeCompare(b.relPath)
  );
}

/** Weight of the master marked default: 400 when present, else closest to it. */
function defaultWeight(weights: number[]): number {
  let best = weights[0] ?? 400;
  for (const weight of weights) {
    if (Math.abs(weight - 400) < Math.abs(best - 400)) {
      best = weight;
    }
  }
  return best;
}

function styleBlock(id: string, key: string, fonts: FoundFont[]): object {
  const italic = key === "italic";
  const suffix = italic ? "-italic" : "";
  const fallback = defaultWeight(fonts.map((f) => f.info.weight));
  return {
    italic,
    donors: fonts.map((font) => ({
      id: `${key}-${weightName(font).toLowerCase()}`,
      name: path.basename(font.relPath, path.extname(font.relPath)),
      path: font.relPath.split(path.sep).join("/"),
      location: { wght: font.info.weight },
    })),
    source: `build/${id}${suffix}.glyphs`,
    masters: fonts.map((font) => ({
      name: weightName(font),
      donorId: `${key}-${weightName(font).toLowerCase()}`,
      location: { wght: font.info.weight },
      ...(font.info.weight === fallback ? { default: true } : {}),
    })),
    output: `build/${id}${suffix}-vf.ttf`,
  };
}

/**
 * Group fonts into roman/italic styles by their italic bit. Within a style,
 * duplicate weights keep the first file, and a style needs at least two
 * weights to interpolate; everything dropped lands in `skipped` with a reason.
 */
function groupFonts(fonts: FoundFont[]): {
  groups: Map<string, FoundFont[]>;
  skipped: string[];
} {
  const skipped: string[] = [];
  const groups = new Map<string, FoundFont[]>();
  for (const font of fonts) {
    const key = font.info.italic ? "italic" : "roman";
    const group = groups.get(key) ?? [];
    if (group.some((g) => g.info.weight === font.info.weight)) {
      skipped.push(`${font.relPath} (duplicate weight ${font.info.weight})`);
      continue;
    }
    group.push(font);
    groups.set(key, group);
  }
  for (const [key, group] of groups) {
    if (group.length < 2) {
      for (const font of group) {
        skipped.push(`${font.relPath} (${key} needs at least two weights)`);
      }
      groups.delete(key);
    }
  }
  return { groups, skipped };
}

/** Build a schema-valid config from detected fonts (see `groupFonts`). */
export function buildInitConfig(
  fonts: FoundFont[],
  familyName: string
): { config: object; skipped: string[] } {
  const { groups, skipped } = groupFonts(fonts);
  const kept = [...groups.values()].flat();
  if (kept.length === 0) {
    throw new CliError(
      "STV_INVALID_OPTION",
      "Need at least two font files with different weights to build a variable font.",
      {
        exitCode: ExitCode.Usage,
        fix: "Select two or more weights of the same family (e.g. Thin + Regular + Bold).",
      }
    );
  }

  const id =
    familyName.toLowerCase().replaceAll(/[^a-z0-9]/g, "") || "myfamily";
  const weights = [...new Set(kept.map((f) => f.info.weight))].toSorted(
    (a, b) => a - b
  );
  const namedInstances: Record<string, string> = {};
  for (const font of kept) {
    namedInstances[String(font.info.weight)] ??= weightName(font);
  }
  const meta = kept.find((f) => !f.info.italic) ?? kept[0];

  const config = {
    $schema:
      "https://github.com/mblode/static-to-variable/schemas/stv-config.schema.json",
    version: 3,
    id,
    family: {
      name: familyName,
      version: "1.000",
      vendor: meta?.info.vendor ?? "Unknown",
      designer: meta?.info.designer ?? "Unknown",
      designerUrl: meta?.info.designerUrl ?? "https://example.com",
      vendorUrl: meta?.info.vendorUrl ?? "https://example.com",
    },
    axes: [
      {
        tag: "wght",
        name: "Weight",
        minimum: weights[0],
        default: defaultWeight(weights),
        maximum: weights.at(-1),
        namedInstances,
      },
    ],
    styles: Object.fromEntries(
      [...groups.entries()].map(([key, group]) => [
        key,
        styleBlock(id, key, group),
      ])
    ),
    output: {
      dir: "build",
      releaseDir: "build/release",
      formats: ["ttf", "woff2"],
    },
  };
  assertValidConfig(config, "generated config");
  return { config, skipped };
}

function label(font: FoundFont): string {
  const italic = font.info.italic ? " italic" : "";
  return `${font.relPath}  (${font.info.family} ${font.info.style}, weight ${font.info.weight}${italic})`;
}

function bail(): never {
  cancel("Cancelled. Nothing written.");
  process.exit(ExitCode.Interrupted);
}

/**
 * Prompt over the detected fonts and write the generated config to `target`.
 */
async function interactiveInit(
  target: string,
  fonts: FoundFont[]
): Promise<void> {
  intro("static-to-variable init");
  const selectedPaths = await multiselect({
    message: "Build the variable font from these files?",
    options: fonts.map((font) => ({ label: label(font), value: font.relPath })),
    initialValues: fonts.map((font) => font.relPath),
  });
  if (isCancel(selectedPaths)) {
    bail();
  }
  const selected = fonts.filter((font) => selectedPaths.includes(font.relPath));

  const detected = selected[0]?.info.family;
  const familyName = await text({
    message: "Family name for the variable font",
    initialValue: detected && detected !== "Unknown" ? detected : "",
    validate: (value) => (value?.trim() ? undefined : "Give it a name."),
  });
  if (isCancel(familyName)) {
    bail();
  }

  const { config, skipped } = buildInitConfig(selected, familyName.trim());
  writeFileSync(target, `${JSON.stringify(config, null, 2)}\n`);
  for (const line of skipped) {
    progress(`skipped: ${line}`);
  }
  outro(`Wrote ${target}. Next: static-to-variable build`);
}

/**
 * Entry point for the init command. Interactive when possible; otherwise
 * writes the static template.
 */
export async function runInit(force: boolean): Promise<void> {
  const target = path.resolve(process.cwd(), "stv.config.json");
  if (!force && existsSync(target)) {
    throw new CliError(
      "STV_CONFIG_EXISTS",
      `stv.config.json already exists at ${target}.`,
      {
        fix: "Edit it, or pass --force to overwrite.",
        exitCode: ExitCode.Usage,
      }
    );
  }
  const interactive = Boolean(process.stdin.isTTY && process.stdout.isTTY);
  const fonts = interactive ? scanFonts(process.cwd()) : [];
  if (fonts.length > 0) {
    await interactiveInit(target, fonts);
    return;
  }
  writeFileSync(target, INIT_CONFIG_TEMPLATE);
  progress(`Wrote ${target}`);
  if (interactive) {
    progress(
      "No font files found here, so this is a starter template. Set the donor paths and weights, then run `static-to-variable build`."
    );
  } else {
    progress(
      "Edit family metadata, donor paths, and axis/masters, then run `static-to-variable build`."
    );
  }
  progress(
    "Schema + a full worked example: schemas/stv-config.schema.json and examples/glide/."
  );
}
