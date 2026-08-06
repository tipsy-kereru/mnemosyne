import { build, context } from "esbuild";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.dirname(fileURLToPath(import.meta.url));
const watch = process.argv.includes("--watch");
const options = {
  entryPoints: [path.join(root, "main.ts")],
  bundle: true,
  external: ["obsidian", "electron"],
  format: "cjs",
  platform: "node",
  target: "es2020",
  sourcemap: false,
  outfile: path.join(root, "main.js"),
  logLevel: "info"
};

if (watch) {
  const buildContext = await context(options);
  await buildContext.watch();
  console.log("Watching Mnemosyne Sync plugin");
} else {
  await build(options);
}
