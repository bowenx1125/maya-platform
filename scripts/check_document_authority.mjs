import { createHash } from "node:crypto";
import { existsSync, lstatSync, readdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

const root = process.cwd();
const required = [
  "PROJECT.md",
  "PROJECT_STATUS.md",
  "ARCHITECTURE.md",
  "AGENTS.md",
  "docs/contracts/README.md",
  "docs/adr/README.md",
  "docs/gates/wave4/R0_GATE_PACKET.md",
  "docs/requirements/original.md",
  "docs/archive/PROJECT_MONOLITH_2026-08-30.md",
  "docs/archive/PROJECT_MONOLITH_2026-08-30.sha256",
];

const failures = [];
for (const relative of required) {
  if (!existsSync(resolve(root, relative)))
    failures.push(`missing required file: ${relative}`);
}
if (readdirSync(root).includes("Project.md")) {
  failures.push("legacy root Project.md must not exist");
}

const limits = new Map([
  ["PROJECT.md", 20_000],
  ["PROJECT_STATUS.md", 12_000],
]);
for (const [relative, maximum] of limits) {
  const absolute = resolve(root, relative);
  if (existsSync(absolute) && lstatSync(absolute).size > maximum) {
    failures.push(`${relative} exceeds ${maximum} bytes`);
  }
}

const activeMarkdown = [
  "PROJECT.md",
  "PROJECT_STATUS.md",
  "ARCHITECTURE.md",
  "AGENTS.md",
  "README.md",
  "docs/TASK_PACKET_TEMPLATE.md",
  "docs/RELEASE_POLICY.md",
  "docs/contracts/README.md",
  "docs/adr/README.md",
  "docs/adr/ADR-001-immutable-agent-version.md",
  "docs/adr/ADR-002-knowledge-snapshot.md",
  "docs/adr/ADR-003-manual-reconnect.md",
  "docs/adr/ADR-004-structured-persona.md",
  "docs/adr/ADR-005-claim-evidence-trace.md",
  "docs/adr/ADR-006-complete-history-prompt.md",
  "docs/gates/wave4/R0_GATE_PACKET.md",
  "docs/requirements/README.md",
];

const forbiddenActiveText = [
  "../Project.md",
  "../docs/pre-code-contracts",
  "M13-M15 and real providers remain unstarted",
  "53 implemented + 13 placeholders",
];
const markdownLink = /\[[^\]]*\]\(([^)]+)\)/g;
for (const relative of activeMarkdown) {
  const absolute = resolve(root, relative);
  if (!existsSync(absolute)) {
    failures.push(`active document missing: ${relative}`);
    continue;
  }
  const text = readFileSync(absolute, "utf8");
  for (const forbidden of forbiddenActiveText) {
    if (text.includes(forbidden))
      failures.push(`${relative} contains stale text: ${forbidden}`);
  }
  for (const match of text.matchAll(markdownLink)) {
    const target = match[1].trim();
    if (
      !target ||
      target.startsWith("#") ||
      /^[a-z][a-z0-9+.-]*:/i.test(target)
    )
      continue;
    const localTarget = decodeURIComponent(target.split("#", 1)[0]);
    if (!existsSync(resolve(dirname(absolute), localTarget))) {
      failures.push(`${relative} has missing link target: ${target}`);
    }
  }
}

const archiveRelative = "docs/archive/PROJECT_MONOLITH_2026-08-30.md";
const checksumRelative = "docs/archive/PROJECT_MONOLITH_2026-08-30.sha256";
if (
  existsSync(resolve(root, archiveRelative)) &&
  existsSync(resolve(root, checksumRelative))
) {
  const bytes = readFileSync(resolve(root, archiveRelative));
  const actual = createHash("sha256").update(bytes).digest("hex");
  const expected = readFileSync(resolve(root, checksumRelative), "utf8")
    .trim()
    .split(/\s+/, 1)[0];
  if (actual !== expected)
    failures.push("archived PROJECT monolith checksum mismatch");
}

if (failures.length) {
  for (const failure of failures)
    process.stderr.write(`DOC_AUTHORITY_ERROR: ${failure}\n`);
  process.exit(1);
}

process.stdout.write("DOCUMENT_AUTHORITY_OK\n");
