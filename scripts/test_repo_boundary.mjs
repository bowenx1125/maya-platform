import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { execFileSync, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { tmpdir } from "node:os";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const checker = resolve(root, "scripts/check_repo_boundary.mjs");
const result = spawnSync(process.execPath, [checker, "--probe-generated"], {
  cwd: root,
  encoding: "utf8",
  env: { ...process.env, CI: "true" },
});

if (result.status !== 0) {
  throw new Error(
    result.stderr || result.stdout || "repository boundary probe failed",
  );
}

console.log(
  "repository boundary probe passed: generated API source is included in the secret scan",
);

const forceTrackedRoot = mkdtempSync(
  resolve(tmpdir(), "maya-boundary-force-tracked-"),
);
try {
  const probeRepo = resolve(forceTrackedRoot, "maya-platform");
  const probeScripts = resolve(probeRepo, "scripts");
  mkdirSync(probeScripts, { recursive: true });
  copyFileSync(checker, resolve(probeScripts, "check_repo_boundary.mjs"));
  mkdirSync(resolve(probeRepo, "backend/config"), { recursive: true });
  writeFileSync(
    resolve(probeRepo, ".gitignore"),
    "backend/config/demo_users.yaml\nbackend/config/credentials.json\n",
    "utf8",
  );
  writeFileSync(
    resolve(probeRepo, "backend/config/demo_users.yaml"),
    "users: []\n",
    "utf8",
  );
  writeFileSync(
    resolve(probeRepo, "backend/config/credentials.json"),
    "{}\n",
    "utf8",
  );
  execFileSync("git", ["init", "--quiet", probeRepo], { encoding: "utf8" });
  execFileSync("git", ["-C", probeRepo, "add", ".gitignore"], {
    encoding: "utf8",
  });
  execFileSync(
    "git",
    [
      "-C",
      probeRepo,
      "add",
      "-f",
      "backend/config/demo_users.yaml",
      "backend/config/credentials.json",
    ],
    { encoding: "utf8" },
  );
  const beforeIndex = execFileSync("git", ["-C", probeRepo, "write-tree"], {
    encoding: "utf8",
  }).trim();
  const forceTracked = spawnSync(
    process.execPath,
    [resolve(probeScripts, "check_repo_boundary.mjs")],
    { cwd: probeRepo, encoding: "utf8", env: { ...process.env, CI: "true" } },
  );
  const afterIndex = execFileSync("git", ["-C", probeRepo, "write-tree"], {
    encoding: "utf8",
  }).trim();
  if (forceTracked.status === 0)
    throw new Error(
      "force-tracked private credential probe unexpectedly passed",
    );
  const output = `${forceTracked.stdout}\n${forceTracked.stderr}`;
  for (const path of [
    "backend/config/demo_users.yaml",
    "backend/config/credentials.json",
  ])
    if (!output.includes(path))
      throw new Error(
        `force-tracked credential probe did not name ${path}:\n${output}`,
      );
  if (beforeIndex !== afterIndex)
    throw new Error(
      "force-tracked credential probe changed its temporary Git index",
    );
  console.log(
    "force-tracked credential probe passed: private credential paths are rejected before content scanning and the temporary index is unchanged",
  );
} finally {
  rmSync(forceTrackedRoot, { recursive: true, force: true });
}
