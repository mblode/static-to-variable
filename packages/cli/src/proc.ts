import { spawn } from "node:child_process";

/**
 * Spawn a child process, resolving to its exit code. Rejects on spawn failure
 * (e.g. command not found). Shared by the pipeline stage runner and the Python
 * engine invoker so exit-code semantics stay identical everywhere.
 *
 * The child's stdout is routed to OUR stderr: everything a stage or the engine
 * prints is human progress, and the CLI's own stdout must stay clean for
 * machine output (--json, the status report).
 */
export function spawnInherit(
  command: string,
  args: readonly string[],
  cwd: string
): Promise<number> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, [...args], {
      cwd,
      env: process.env,
      stdio: ["inherit", 2, "inherit"],
    });
    child.on("error", reject);
    child.on("close", (code) => resolve(code ?? 1));
  });
}
