/** A static font the user dropped in, as detected client-side. */
export interface DetectedFont {
  fileName: string;
  family: string;
  style: string;
  weight: number;
  italic: boolean;
}

/** One step of the server-side build, for progress UI. */
export interface BuildStage {
  id: string;
  title: string;
  status: "pending" | "running" | "succeeded" | "failed";
}

/** A file produced by the build (variable font, report, etc.). */
export interface ResultFile {
  name: string;
  format: string;
  bytes: number;
  url: string;
}

/** The successful output of a build. */
export interface BuildResult {
  files: ResultFile[];
  axis: { min: number; def: number; max: number };
  instances: { name: string; wght: number }[];
  /** Glyph names pinned because they couldn't interpolate cleanly. */
  frozen: string[];
}

/** A failed build. */
export interface BuildError {
  code: string;
  message: string;
}
