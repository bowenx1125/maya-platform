import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { execFileSync, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { tmpdir } from "node:os";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const checker = resolve(root, "scripts/check_repo_boundary.mjs");
const policy = resolve(root, "config/repository-data-policy.json");

function runChecker(cwd, extraArgs = []) {
  return spawnSync(
    process.execPath,
    [resolve(cwd, "scripts/check_repo_boundary.mjs"), ...extraArgs],
    {
      cwd,
      encoding: "utf8",
      env: { ...process.env, CI: "true" },
    },
  );
}

const current = runChecker(root, ["--probe-generated"]);
if (current.status !== 0) {
  throw new Error(
    current.stderr || current.stdout || "current repository boundary check failed",
  );
}

const probeRoot = mkdtempSync(resolve(tmpdir(), "maya-boundary-policy-"));
try {
  const repo = resolve(probeRoot, "maya-platform");
  mkdirSync(resolve(repo, "scripts"), { recursive: true });
  mkdirSync(resolve(repo, "config"), { recursive: true });
  mkdirSync(resolve(repo, "backend/config/demo-accounts"), { recursive: true });
  mkdirSync(resolve(repo, "private-inputs/voice"), { recursive: true });
  mkdirSync(resolve(repo, "frontend/lib/api/generated"), { recursive: true });
  mkdirSync(resolve(repo, "data"), { recursive: true });

  copyFileSync(checker, resolve(repo, "scripts/check_repo_boundary.mjs"));
  copyFileSync(policy, resolve(repo, "config/repository-data-policy.json"));
  writeFileSync(
    resolve(repo, ".env.example"),
    "DASHSCOPE_API_KEY=\nSESSION_SECRET=replace-with-at-least-32-random-characters\n",
  );
  writeFileSync(
    resolve(repo, "backend/config/demo-accounts/accounts.private.md"),
    "# approved private Demo accounts\n",
  );
  writeFileSync(resolve(repo, "backend/config/demo_users.yaml"), "users: []\n");
  writeFileSync(
    resolve(repo, "private-inputs/voice/test.m4a"),
    Buffer.from([0, 1, 2, 3]),
  );
  writeFileSync(resolve(repo, "frontend/index.ts"), "export const safe = true;\n");

  execFileSync("git", ["init", "--quiet", repo]);
  execFileSync("git", ["-C", repo, "add", "."]);

  const allowed = runChecker(repo);
  if (allowed.status !== 0) {
    throw new Error(
      `approved-private-file probe failed:\n${allowed.stdout}\n${allowed.stderr}`,
    );
  }

  const simulatedKey = `sk-${"reject".repeat(6)}`;
  writeFileSync(
    resolve(repo, ".env"),
    `DASHSCOPE_API_KEY=${simulatedKey}\n`,
  );
  writeFileSync(resolve(repo, "data/maya.sqlite3"), Buffer.from([0, 1, 2, 3]));
  writeFileSync(
    resolve(repo, "frontend/lib/api/generated/leak.ts"),
    `export const key = "${simulatedKey}";\n`,
  );
  execFileSync("git", [
    "-C",
    repo,
    "add",
    "-f",
    ".env",
    "data/maya.sqlite3",
    "frontend/lib/api/generated/leak.ts",
  ]);

  const rejected = runChecker(repo);
  if (rejected.status === 0) {
    throw new Error("forbidden runtime/secret probe unexpectedly passed");
  }
  const output = `${rejected.stdout}\n${rejected.stderr}`;
  for (const expected of [
    ".env",
    "data/maya.sqlite3",
    "frontend/lib/api/generated/leak.ts",
  ]) {
    if (!output.includes(expected)) {
      throw new Error(`forbidden probe did not name ${expected}`);
    }
  }

  console.log(
    "repository boundary tests passed: approved Demo credentials/voice are allowed; .env, runtime DB, and generated frontend secret are rejected",
  );
} finally {
  rmSync(probeRoot, { recursive: true, force: true });
}
