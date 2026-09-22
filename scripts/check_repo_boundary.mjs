import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, relative, resolve } from "node:path";
import { tmpdir } from "node:os";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const forbiddenDirectories = new Set([
  ".git",
  "node_modules",
  ".next",
  ".venv",
  "__pycache__",
  ".mypy_cache",
  ".ruff_cache",
  ".pnpm-store",
  "coverage",
  "out",
  "cache",
  "build",
  "dist",
  "vendor",
]);
const forbiddenTrackedName =
  /(^|\/)(?:\.env$|[^/]*\.(?:sqlite3?|db(?:-[^/]*)?|wav|mp3|m4a|aac|ogg|pem|key))$/i;
const privateCredentialName =
  /(^|\/)(?:demo[_-]?users|[^/]*(?:credential|secret|private)[^/]*)\.(?:json|ya?ml|toml|ini|env)$/i;
// These files are intentionally generated local runtime state. They are
// ignored by Git/Docker and may contain the developer's session secret or
// Demo credentials, so inspect them through explicit existence/permission
// checks rather than treating their values as repository content.
const ignoredRuntimeFiles = new Set([
  ".env",
  "backend/config/demo-accounts/accounts.private.md",
  "backend/config/demo_users.yaml",
]);
const forbiddenReference =
  /(?:Document Validation Agent|agent-core-private|OpenMAIC-main|parallax-main|OpenAvatarChat-main|TalkingHead-main|motion-engine-main|RomanticSimulation)/i;
const supplierUrlPattern =
  /https?:\/\/[^\s"']*(?:aliyuncs\.com|dashscope|api-free\.deepl\.com|openai\.com|deepgram\.com)[^\s"']*/i;
const secretPatterns = [
  /\b(?:sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})\b/,
  /\bBearer\s+[A-Za-z0-9._-]{20,}\b/i,
  /-----BEGIN [^-]*PRIVATE KEY-----/,
];
const assignmentPattern =
  /^[ \t]*(?:DASHSCOPE_API_KEY|DEEPL_API_KEY|OPENAI_API_KEY|SESSION_SECRET|SECRET_KEY|API_KEY)[ \t]*[=:][ \t]*([^\r\n]*)$/gm;
const genericSecretAssignmentPattern =
  /^[ \t]*["']?(?:api[_-]+key|access[_-]+token|secret(?:[_-]+key)?|provider[_-]+key|external[_-]+voice[_-]+id)["']?[ \t]*[=:][ \t]*["']?([^"',\r\n}{\[]*)/gim;

const gitRoot = execFileSync(
  "git",
  ["-C", root, "rev-parse", "--show-toplevel"],
  { encoding: "utf8" },
).trim();
if (resolve(gitRoot) !== root) {
  throw new Error(
    "Git root must be exactly the product directory that contains this boundary checker; parent workspaces must never be scanned as the product repository",
  );
}

const tracked = execFileSync(
  "git",
  ["-C", root, "ls-files", "-co", "--exclude-standard", "-z"],
  { encoding: "buffer" },
)
  .toString("utf8")
  .split("\0")
  .filter(Boolean);
const boundaryFailures = [];
for (const file of tracked) {
  const normalized = file.replaceAll("\\", "/");
  if (normalized.startsWith("../") || normalized.includes("/../"))
    boundaryFailures.push(`parent path tracked: ${normalized}`);
  if (
    forbiddenTrackedName.test(normalized) ||
    privateCredentialName.test(normalized)
  )
    boundaryFailures.push(
      `forbidden runtime/secret file tracked: ${normalized}`,
    );
  if (forbiddenReference.test(normalized))
    boundaryFailures.push(`reference/private path tracked: ${normalized}`);
}

function walk(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (forbiddenDirectories.has(entry.name)) continue;
    const absolute = resolve(directory, entry.name);
    const relativePath = relative(root, absolute).replaceAll("\\", "/");
    if (entry.isDirectory()) {
      if (entry.name === ".git")
        boundaryFailures.push(`nested Git directory found: ${relativePath}`);
      else walk(absolute);
      continue;
    }
    if (!entry.isFile()) continue;
    if (ignoredRuntimeFiles.has(relativePath)) continue;
    let bytes;
    try {
      bytes = readFileSync(absolute);
    } catch {
      boundaryFailures.push(
        `could not inspect repository file: ${relativePath}`,
      );
      continue;
    }
    if (bytes.includes(0)) continue;
    const text = bytes.toString("utf8");
    for (const match of text.matchAll(assignmentPattern)) {
      const value = match[1].trim();
      if (
        !value ||
        value.startsWith("#") ||
        value.startsWith("${") ||
        value === '""' ||
        value === "''"
      )
        continue;
      boundaryFailures.push(
        `possible secret assignment/token in ${relativePath}`,
      );
      break;
    }
    if (
      boundaryFailures.some((failure) => failure.endsWith(`in ${relativePath}`))
    )
      continue;
    if (/\.(?:env|json|ya?ml|toml|ini)$/i.test(relativePath)) {
      for (const match of text.matchAll(genericSecretAssignmentPattern)) {
        const value = match[1].trim();
        if (
          !value ||
          value.startsWith("#") ||
          value.startsWith("$") ||
          /^(?:example|fixture|hidden|mock|safe|supplier|test|placeholder)$/i.test(
            value,
          )
        )
          continue;
        boundaryFailures.push(
          `possible secret assignment/token in ${relativePath}`,
        );
        break;
      }
    }
    if (
      boundaryFailures.some((failure) => failure.endsWith(`in ${relativePath}`))
    )
      continue;
    for (const pattern of secretPatterns) {
      if (pattern.test(text)) {
        boundaryFailures.push(
          `possible secret assignment/token in ${relativePath}`,
        );
        break;
      }
    }
    const supplierUrlAllowed =
      relativePath === "backend/app/providers/dashscope.py" ||
      relativePath === "backend/app/providers/control.py" ||
      relativePath === "backend/app/modules/knowledge/providers/adapters.py" ||
      relativePath === "backend/tests/test_wave1b_voices.py" ||
      relativePath === "backend/tests/test_wave4_llm_adapter.py" ||
      relativePath === "backend/tests/test_wave4_llm_runtime.py" ||
      relativePath === "backend/tests/test_real_report_provider.py" ||
      relativePath === "docs/contracts/DEBATE_GENERATION_CONTRACTS.md" ||
      // The operator has to record the exact endpoint they reviewed, so the
      // policy templates name it on purpose.
      relativePath === "docs/templates/llm-policy.template.json" ||
      relativePath === "docs/templates/embedding-policy.template.json" ||
      // A reviewed policy records the exact endpoint it was reviewed for.
      // These files are the operator's, git-ignored and mode 0600; the scan
      // still reads them for credentials, it just does not treat the endpoint
      // they exist to record as a leak.
      relativePath.startsWith("backend/config/provider-policies/");
    if (!supplierUrlAllowed && supplierUrlPattern.test(text))
      boundaryFailures.push(
        `supplier endpoint outside its allow-list in ${relativePath}`,
      );
  }
}
walk(root);

if (process.argv.includes("--probe-generated")) {
  const probeRoot = mkdtempSync(resolve(tmpdir(), "maya-boundary-probe-"));
  try {
    const generatedDir = resolve(probeRoot, "frontend/lib/api/generated");
    mkdirSync(generatedDir, { recursive: true });
    writeFileSync(
      resolve(generatedDir, "simulated-leak.ts"),
      `export const simulatedKey = "${"sk-" + "probe".repeat(8)}";\nexport const supplier = "${"https://" + "dashscope.aliyuncs.com/api"}";\n`,
      "utf8",
    );
    const probeFailures = [];
    // A schema property describes a write-only field, not a secret value.
    // Nested scalar assignments must still be caught by the same scanner.
    writeFileSync(
      resolve(probeRoot, "schema.json"),
      JSON.stringify(
        {
          properties: {
            api_key: { type: "string", format: "password", writeOnly: true },
          },
        },
        null,
        2,
      ),
    );
    writeFileSync(
      resolve(probeRoot, "credential.json"),
      JSON.stringify(
        {
          nested: { api_key: "unapproved-scalar-value" },
        },
        null,
        2,
      ),
    );
    const originalFailures = [...boundaryFailures];
    boundaryFailures.length = 0;
    walk(probeRoot);
    probeFailures.push(...boundaryFailures);
    boundaryFailures.length = 0;
    boundaryFailures.push(...originalFailures);
    if (probeFailures.length === 0)
      throw new Error(
        "generated-source secret probe did not detect the simulated key/supplier URL",
      );
    if (
      probeFailures.some((value) => value.endsWith("/schema.json")) ||
      !probeFailures.some((value) => value.endsWith("/credential.json"))
    ) {
      throw new Error(
        "schema metadata and nested credential values were not distinguished",
      );
    }
    console.log(
      "generated-source secret probe passed: simulated key and supplier URL were detected without touching product files",
    );
  } finally {
    rmSync(probeRoot, { recursive: true, force: true });
  }
}

if (boundaryFailures.length) {
  throw new Error(
    `product repository boundary check failed:\n- ${boundaryFailures.join("\n- ")}`,
  );
}

console.log(
  `product boundary passed: Git root maya-platform; inspected ${tracked.length} candidate tracked files; no tracked secrets, runtime artifacts, private references, or supplier keys`,
);
