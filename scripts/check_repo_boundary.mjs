import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, relative, resolve } from "node:path";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const policyPath = resolve(root, "config/repository-data-policy.json");
const policy = JSON.parse(readFileSync(policyPath, "utf8"));

function normalize(value) {
  return value.replaceAll("\\", "/");
}

function isAllowedPrivatePath(path) {
  return (
    policy.allowed_private_files.includes(path) ||
    policy.allowed_private_prefixes.some((prefix) => path.startsWith(prefix))
  );
}

function isForbiddenByPolicy(path) {
  if (policy.forbidden_tracked_files.includes(path)) return true;
  if (policy.forbidden_tracked_prefixes.some((prefix) => path.startsWith(prefix)))
    return true;
  if (/^\.env(?:\.|$)/.test(path) && path !== ".env.example") return true;
  if (/\.(?:sqlite3?|db)(?:-(?:wal|shm|journal))?$/i.test(path)) return true;
  if (/\.(?:wav|mp3|m4a|aac|ogg|flac)$/i.test(path) && !isAllowedPrivatePath(path))
    return true;
  if (
    /(^|\/)(?:[^/]*(?:credential|secret|private)[^/]*)\.(?:json|ya?ml|toml|ini|env)$/i.test(
      path,
    ) &&
    !isAllowedPrivatePath(path)
  )
    return true;
  return false;
}

const secretPatterns = [
  /\bsk-[A-Za-z0-9._-]{20,}\b/,
  /\bAKIA[0-9A-Z]{16}\b/,
  /\bAIza[0-9A-Za-z_-]{30,}\b/,
  /\bBearer\s+[A-Za-z0-9._-]{20,}\b/i,
  /-----BEGIN [^-]*PRIVATE KEY-----/,
];

const assignmentPattern =
  /^[ \t]*(?:DASHSCOPE_API_KEY|DEEPL_API_KEY|OPENAI_API_KEY|SESSION_SECRET|SECRET_KEY|API_KEY)[ \t]*[=:][ \t]*([^\r\n]*)$/gm;

const browserSupplierUrlPattern =
  /https?:\/\/[^\s"']*(?:aliyuncs\.com|dashscope|api-free\.deepl\.com|openai\.com|deepgram\.com)[^\s"']*/i;

function nonPlaceholderAssignment(text) {
  for (const match of text.matchAll(assignmentPattern)) {
    const value = match[1].trim().replace(/^['"]|['"]$/g, "");
    if (
      !value ||
      value.startsWith("#") ||
      value.startsWith("${") ||
      value.startsWith("replace-") ||
      /^(?:example|fixture|hidden|mock|safe|supplier|test|placeholder)$/i.test(value)
    )
      continue;
    return true;
  }
  return false;
}

function containsSecret(text) {
  return nonPlaceholderAssignment(text) || secretPatterns.some((pattern) => pattern.test(text));
}

const gitRoot = execFileSync(
  "git",
  ["-C", root, "rev-parse", "--show-toplevel"],
  { encoding: "utf8" },
).trim();
if (resolve(gitRoot) !== root) {
  throw new Error(
    "Git root must be exactly the Maya product directory; parent workspaces must not be scanned as product source.",
  );
}

const tracked = execFileSync("git", ["-C", root, "ls-files", "-z"], {
  encoding: "buffer",
})
  .toString("utf8")
  .split("\0")
  .filter(Boolean)
  .map(normalize);

const failures = [];
let scannedTextFiles = 0;
let allowedPrivateFiles = 0;

for (const path of tracked) {
  if (path.startsWith("../") || path.includes("/../")) {
    failures.push(`parent path tracked: ${path}`);
    continue;
  }
  if (isForbiddenByPolicy(path)) {
    failures.push(`forbidden runtime/private artifact tracked: ${path}`);
    continue;
  }
  if (isAllowedPrivatePath(path)) {
    allowedPrivateFiles += 1;
    continue;
  }

  let bytes;
  try {
    bytes = readFileSync(resolve(root, path));
  } catch {
    failures.push(`could not inspect tracked file: ${path}`);
    continue;
  }
  if (bytes.includes(0)) continue;

  const text = bytes.toString("utf8");
  scannedTextFiles += 1;
  if (containsSecret(text)) {
    failures.push(`possible secret assignment/token in ${path}`);
    continue;
  }

  const browserFacing =
    path.startsWith("frontend/") ||
    path.startsWith("contracts/") ||
    path.startsWith("infra/");
  if (browserFacing && browserSupplierUrlPattern.test(text)) {
    failures.push(`supplier URL leaked into browser-facing source: ${path}`);
  }
}

if (process.argv.includes("--probe-generated")) {
  const simulated = `export const key = "${"sk-" + "probe".repeat(8)}";\n`;
  if (!containsSecret(simulated)) {
    throw new Error("generated-source secret probe did not detect a simulated key");
  }
  console.log("generated-source secret probe passed");
}

if (failures.length > 0) {
  throw new Error(`repository boundary check failed:\n- ${failures.join("\n- ")}`);
}

console.log(
  `repository boundary passed: ${tracked.length} tracked files; ${scannedTextFiles} text files scanned; ${allowedPrivateFiles} approved private-team files skipped by exact policy`,
);
