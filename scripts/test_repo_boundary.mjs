import {
  chmodSync,
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

const rootDockerignore = readFileSync(resolve(root, ".dockerignore"), "utf8");
const backendDockerignore = readFileSync(
  resolve(root, "backend/.dockerignore"),
  "utf8",
);
for (const [source, patterns, label] of [
  [
    rootDockerignore,
    [
      "**/*.private.md",
      "backend/config/provider-policies/",
      "backend/.env",
      "backend/.env.*",
      "!backend/.env.example",
    ],
    ".dockerignore",
  ],
  [
    backendDockerignore,
    [
      "**/*.private.md",
      "config/provider-policies/",
      ".env",
      ".env.*",
      "!.env.example",
    ],
    "backend/.dockerignore",
  ],
]) {
  for (const pattern of patterns)
    if (!source.split(/\r?\n/).includes(pattern))
      throw new Error(`${label} is missing private-input rule ${pattern}`);
}

const ignoreRuleRoot = mkdtempSync(
  resolve(tmpdir(), "maya-boundary-ignore-rules-"),
);
try {
  copyFileSync(
    resolve(root, ".gitignore"),
    resolve(ignoreRuleRoot, ".gitignore"),
  );
  execFileSync("git", ["init", "--quiet", ignoreRuleRoot], {
    encoding: "utf8",
  });
  for (const path of [
    ".env",
    ".env.production",
    "backend/.env",
    "backend/.env.production",
    "backend/config/production-accounts/accounts.private.md",
    "backend/config/production-accounts/alternate.private.md",
    "backend/config/provider-policies/llm.json",
  ]) {
    const absolute = resolve(ignoreRuleRoot, path);
    mkdirSync(dirname(absolute), { recursive: true });
    writeFileSync(absolute, "private probe\n", "utf8");
    const ignored = spawnSync(
      "git",
      ["-C", ignoreRuleRoot, "check-ignore", "--quiet", "--no-index", path],
      { encoding: "utf8" },
    );
    if (ignored.status !== 0)
      throw new Error(`Git ignore rules do not protect private input ${path}`);
  }
  for (const path of [
    ".env.example",
    "backend/.env.example",
    "backend/config/production-accounts/accounts.example.md",
  ]) {
    const absolute = resolve(ignoreRuleRoot, path);
    mkdirSync(dirname(absolute), { recursive: true });
    writeFileSync(absolute, "placeholder example\n", "utf8");
    const ignored = spawnSync(
      "git",
      ["-C", ignoreRuleRoot, "check-ignore", "--quiet", "--no-index", path],
      { encoding: "utf8" },
    );
    if (ignored.status === 0)
      throw new Error(`Git ignore rules hide public example ${path}`);
  }
} finally {
  rmSync(ignoreRuleRoot, { recursive: true, force: true });
}
console.log(
  "private-input ignore probe passed: production catalogs, private policies and environment files are ignored while public examples remain visible",
);

const forceTrackedRoot = mkdtempSync(
  resolve(tmpdir(), "maya-boundary-force-tracked-"),
);
try {
  const probeRepo = resolve(forceTrackedRoot, "maya-platform");
  const probeScripts = resolve(probeRepo, "scripts");
  mkdirSync(probeScripts, { recursive: true });
  copyFileSync(checker, resolve(probeScripts, "check_repo_boundary.mjs"));
  copyFileSync(resolve(root, ".gitignore"), resolve(probeRepo, ".gitignore"));
  mkdirSync(resolve(probeRepo, "backend/config"), { recursive: true });
  const privateTrackedPaths = [
    "backend/config/demo_users.yaml",
    "backend/config/credentials.json",
    "backend/config/production-accounts/accounts.private.md",
    "backend/config/production-accounts/alternate.private.md",
    "backend/config/provider-policies/llm.json",
    "backend/.env",
  ];
  for (const path of privateTrackedPaths) {
    const absolute = resolve(probeRepo, path);
    mkdirSync(dirname(absolute), { recursive: true });
    writeFileSync(absolute, "SENTINEL_PRIVATE_CREDENTIAL_CONTENT\n", "utf8");
  }
  execFileSync("git", ["init", "--quiet", probeRepo], { encoding: "utf8" });
  execFileSync("git", ["-C", probeRepo, "add", ".gitignore"], {
    encoding: "utf8",
  });
  execFileSync("git", ["-C", probeRepo, "add", "-f", ...privateTrackedPaths], {
    encoding: "utf8",
  });
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
  for (const path of privateTrackedPaths)
    if (!output.includes(path))
      throw new Error(
        `force-tracked credential probe did not name ${path}:\n${output}`,
      );
  if (output.includes("SENTINEL_PRIVATE_CREDENTIAL_CONTENT"))
    throw new Error("boundary diagnostics exposed private credential contents");
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

const permissionRoot = mkdtempSync(
  resolve(tmpdir(), "maya-boundary-private-permissions-"),
);
try {
  const probeRepo = resolve(permissionRoot, "maya-platform");
  const probeScripts = resolve(probeRepo, "scripts");
  mkdirSync(probeScripts, { recursive: true });
  copyFileSync(checker, resolve(probeScripts, "check_repo_boundary.mjs"));
  copyFileSync(resolve(root, ".gitignore"), resolve(probeRepo, ".gitignore"));
  mkdirSync(resolve(probeRepo, "backend/config"), { recursive: true });
  execFileSync("git", ["init", "--quiet", probeRepo], { encoding: "utf8" });

  const privatePaths = [
    ".env",
    "backend/.env",
    "backend/config/production-accounts/accounts.private.md",
    "backend/config/provider-policies/llm.json",
  ];
  for (const path of privatePaths) {
    const absolute = resolve(probeRepo, path);
    mkdirSync(dirname(absolute), { recursive: true });
    writeFileSync(absolute, "SENTINEL_PRIVATE_CREDENTIAL_CONTENT\n", {
      encoding: "utf8",
      mode: 0o644,
    });
    chmodSync(absolute, 0o644);
  }

  const permissions = spawnSync(
    process.execPath,
    [resolve(probeScripts, "check_repo_boundary.mjs")],
    { cwd: probeRepo, encoding: "utf8", env: { ...process.env, CI: "true" } },
  );
  if (permissions.status === 0)
    throw new Error(
      "broadly readable private runtime inputs unexpectedly passed",
    );
  const permissionOutput = `${permissions.stdout}\n${permissions.stderr}`;
  for (const path of privatePaths)
    if (!permissionOutput.includes(path))
      throw new Error(`permission probe did not name ${path}`);
  if (permissionOutput.includes("SENTINEL_PRIVATE_CREDENTIAL_CONTENT"))
    throw new Error(
      "permission diagnostics exposed private credential contents",
    );
  if (permissionOutput.includes("possible secret assignment/token"))
    throw new Error(
      "credential content scanner inspected private source values",
    );

  for (const path of privatePaths) chmodSync(resolve(probeRepo, path), 0o600);
  const protectedFiles = spawnSync(
    process.execPath,
    [resolve(probeScripts, "check_repo_boundary.mjs")],
    { cwd: probeRepo, encoding: "utf8", env: { ...process.env, CI: "true" } },
  );
  if (protectedFiles.status !== 0)
    throw new Error(
      protectedFiles.stderr || "owner-only private runtime inputs did not pass",
    );
  console.log(
    "private-input permission probe passed: unsafe modes are rejected without scanning or printing credential contents",
  );
} finally {
  rmSync(permissionRoot, { recursive: true, force: true });
}
