import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:net";

const command = process.argv[2] === "start" ? "start" : "dev";

async function main() {
  const args = hasPortless()
    ? ["portless", "static-to-variable", "next", command]
    : ["next", command, "-p", String(await findOpenPort(3333))];

  if (args[0] === "next") {
    console.warn(
      `portless not found; serving Static to Variable Studio at http://localhost:${args.at(-1)}`
    );
  } else {
    console.log(
      `serving Static to Variable Studio at https://static-to-variable.localhost`
    );
  }

  const child = spawn(args[0], args.slice(1), {
    env: process.env,
    stdio: "inherit",
  });

  child.on("error", (error) => {
    console.error(error.message);
    process.exit(1);
  });

  child.on("close", (code) => {
    process.exit(code ?? 1);
  });
}

function hasPortless(): boolean {
  const result = spawnSync("sh", ["-lc", "command -v portless"], {
    stdio: "ignore",
  });
  return result.status === 0;
}

async function findOpenPort(start: number): Promise<number> {
  for (let port = start; port < start + 100; port += 1) {
    if (await canListen(port)) {
      return port;
    }
  }
  throw new Error(
    `No open localhost port found from ${start} to ${start + 99}.`
  );
}

function canListen(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = createServer()
      .once("error", () => resolve(false))
      .once("listening", () => {
        server.close(() => resolve(true));
      })
      .listen(port);
  });
}

void main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
