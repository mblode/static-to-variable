import { defineConfig } from "tsdown";

// Dual build: the CLI binary (with a shebang, no d.ts) and the typed library
// entry (d.ts, no shebang). These must stay two separate configs — merging them
// would either double the shebang or drop the library types.
export default defineConfig([
  {
    banner: { js: "#!/usr/bin/env node" },
    clean: true,
    entry: { cli: "src/cli.ts" },
    format: ["esm"],
    outExtensions: () => ({ js: ".js" }),
    sourcemap: true,
    target: "node24",
  },
  {
    dts: true,
    entry: { index: "src/index.ts" },
    format: ["esm"],
    outExtensions: () => ({ js: ".js" }),
    sourcemap: true,
    target: "node24",
  },
]);
