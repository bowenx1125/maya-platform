import { createHash } from "node:crypto";
import { existsSync, lstatSync, readdirSync, readFileSync } from "node:fs";
import { dirname, relative, resolve, sep } from "node:path";

const root = process.cwd();

function exactCasePathExists(absolute) {
  const relativePath = relative(root, absolute);
  if (!relativePath || relativePath === ".") return true;
  if (relativePath === ".." || relativePath.startsWith(`..${sep}`))
    return false;
  let cursor = root;
  for (const segment of relativePath.split(sep)) {
    if (!readdirSync(cursor).includes(segment)) return false;
    cursor = resolve(cursor, segment);
  }
  return true;
}

// docs/PROJECT.md is the single product and progress authority; AGENTS.md is
// the single working agreement and CLAUDE.md only points at it. The separate
// status documents, worklogs, completed plans and task-packet templates stay
// removed so progress cannot drift across several files again. The repository root deliberately
// holds only README.md, AGENTS.md and CLAUDE.md; every other document is
// under docs/.
const required = [
  "README.md",
  "AGENTS.md",
  "CLAUDE.md",
  "docs/PROJECT.md",
  "docs/ARCHITECTURE.md",
  "docs/contracts/README.md",
  "docs/adr/README.md",
  "docs/requirements/README.md",
];

const failures = [];
for (const relative of required) {
  const absolute = resolve(root, relative);
  if (!existsSync(absolute) || !exactCasePathExists(absolute))
    failures.push(`missing required file: ${relative}`);
}
const projectCaseVariants = readdirSync(resolve(root, "docs")).filter(
  (name) => name.toLocaleLowerCase("en-US") === "project.md",
);
if (
  projectCaseVariants.length !== 1 ||
  projectCaseVariants[0] !== "PROJECT.md"
) {
  failures.push(
    `authority must be exactly docs/PROJECT.md; found: ${projectCaseVariants.join(", ") || "none"}`,
  );
}

if (!exactCasePathExists(resolve(root, "docs/PROJECT.md"))) {
  failures.push("exact-case docs/PROJECT.md self-test failed");
}
if (exactCasePathExists(resolve(root, "docs/Project.md"))) {
  failures.push("case-variant docs/Project.md negative self-test failed");
}
// The root must not regrow a second authority.
if (exactCasePathExists(resolve(root, "PROJECT.md"))) {
  failures.push("PROJECT.md must live under docs/, not the repository root");
}
if (exactCasePathExists(resolve(root, "docs/ADR/README.md"))) {
  failures.push("case-variant nested path negative self-test failed");
}

const limits = new Map([["docs/PROJECT.md", 20_000]]);
for (const [relative, maximum] of limits) {
  const absolute = resolve(root, relative);
  if (
    existsSync(absolute) &&
    exactCasePathExists(absolute) &&
    lstatSync(absolute).size > maximum
  ) {
    failures.push(`${relative} exceeds ${maximum} bytes`);
  }
}

const activeMarkdown = [
  "docs/PROJECT.md",
  "docs/ARCHITECTURE.md",
  "docs/REAL_PROVIDER_SETUP.md",
  "docs/contracts/DEBATE_GENERATION_CONTRACTS.md",
  "AGENTS.md",
  "CLAUDE.md",
  "README.md",
  "docs/RELEASE_POLICY.md",
  "docs/contracts/README.md",
  "docs/adr/README.md",
  "docs/adr/ADR-001-immutable-agent-version.md",
  "docs/adr/ADR-002-knowledge-snapshot.md",
  "docs/adr/ADR-003-manual-reconnect.md",
  "docs/adr/ADR-004-structured-persona.md",
  "docs/adr/ADR-005-claim-evidence-trace.md",
  "docs/adr/ADR-006-complete-history-prompt.md",
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
  if (!existsSync(absolute) || !exactCasePathExists(absolute)) {
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
    const resolvedTarget = resolve(dirname(absolute), localTarget);
    if (!existsSync(resolvedTarget) || !exactCasePathExists(resolvedTarget)) {
      failures.push(`${relative} has missing link target: ${target}`);
    }
  }
}

if (failures.length) {
  for (const failure of failures)
    process.stderr.write(`DOC_AUTHORITY_ERROR: ${failure}\n`);
  process.exit(1);
}

process.stdout.write("DOCUMENT_AUTHORITY_OK\n");
