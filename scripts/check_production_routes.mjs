// The production build contains no demo-only page (PR D).
//
// Run after `pnpm --filter @maya/frontend build`. Demo pages are named
// page.demo.tsx and only built under `next dev` or DEMO_PAGES=true.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const appDir = join(root, "frontend", "app");
const manifest = join(
  root,
  "frontend",
  ".next",
  "app-path-routes-manifest.json",
);

function demoRoutes(directory) {
  const found = [];
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) found.push(...demoRoutes(path));
    else if (name === "page.demo.tsx")
      found.push(`/${relative(appDir, directory).split("\\").join("/")}`);
  }
  return found;
}

if (!existsSync(manifest)) {
  throw new Error("Build the frontend first: no app-path-routes-manifest.json");
}
if (process.env.DEMO_PAGES === "true") {
  throw new Error("Unset DEMO_PAGES: this check is about the production build");
}
const built = new Set(
  Object.values(JSON.parse(readFileSync(manifest, "utf8"))),
);
const demos = demoRoutes(appDir);
const leaked = demos.filter((route) => built.has(route));
if (demos.length === 0) throw new Error("No page.demo.tsx found to check");
if (leaked.length > 0) {
  throw new Error(`Demo pages in the production build: ${leaked.join(", ")}`);
}
console.log(
  `production build has no demo pages (${demos.join(", ")} excluded)`,
);
