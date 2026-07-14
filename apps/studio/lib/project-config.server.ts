import { readFileSync } from "node:fs";
import path from "node:path";

/**
 * Minimal reader for the v3 stv.config.json. The studio only needs the per-style
 * donor sources and glyphs source to map uploaded files onto workspace targets,
 * so this deliberately parses a narrow slice of the config rather than the full
 * schema the Python loader validates.
 */

interface RawDonor {
  id: string;
  name: string;
  path: string;
  location: Record<string, number>;
}

interface RawStyle {
  italic?: boolean;
  source: string;
  output: string;
  donors: RawDonor[];
}

export interface ProjectConfig {
  id: string;
  styles: Record<string, RawStyle>;
}

export function getProjectConfigPath(repoRoot: string): string {
  const configured = process.env.STV_CONFIG;
  if (configured) {
    return path.isAbsolute(configured)
      ? configured
      : path.resolve(repoRoot, configured);
  }
  return path.join(repoRoot, "examples", "glide", "stv.config.json");
}

export function loadProjectConfig(repoRoot: string): ProjectConfig {
  const configPath = getProjectConfigPath(repoRoot);
  return JSON.parse(readFileSync(configPath, "utf-8")) as ProjectConfig;
}
