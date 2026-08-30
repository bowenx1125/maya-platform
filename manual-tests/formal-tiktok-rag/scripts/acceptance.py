#!/usr/bin/env python3
"""Deterministic Mock-only acceptance for the formal TikTok content packet.

This script intentionally performs no network request and never calls a model or a
Provider.  URL readability is recorded in the manifest after the source-link review;
the local check verifies that every reviewed URL is direct HTTPS metadata and that
the frozen bytes and claim map have not drifted.  Retrieval uses Maya's existing
``mock_lexical_anchor_v2`` and local Mock vector adapter so a content Gate exercises
the same deterministic relevance boundary as the Demo.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"


PACKET = ROOT / "manual-tests" / "formal-tiktok-rag"
MANIFEST_PATH = PACKET / "source-manifest.json"
TOPIC = "Should the United States ban TikTok's recommendation algorithm?"
ALLOWED_CLAIM_TYPES = {"factual", "interpretation", "value_judgement", "proposal"}
MARKER_RE = re.compile(r"\[(C\d{2})\]")
SECRET_RE = re.compile(
    r"(?:api[_-]?key|authorization\s*:\s*bearer|sk-[A-Za-z0-9]|password\s*=)",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def fail(message: str) -> None:
    raise AssertionError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def ensure_backend_import_path() -> None:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))


def safe_packet_path(relative: str) -> Path:
    candidate = (PACKET / relative).resolve()
    require(
        not Path(relative).is_absolute() and ".." not in Path(relative).parts,
        f"manifest path is not packet-relative: {relative!r}",
    )
    require(
        candidate.is_relative_to(PACKET.resolve()),
        f"manifest path escapes packet: {relative!r}",
    )
    return candidate


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_utf8(path: Path) -> str:
    raw = path.read_bytes()
    require(raw, f"empty fixture: {path.relative_to(ROOT)}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(f"fixture is not strict UTF-8: {path.relative_to(ROOT)} ({exc})")
    require("\x00" not in text, f"NUL byte in fixture: {path.relative_to(ROOT)}")
    return text


def load_manifest() -> dict[str, Any]:
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read source manifest: {exc}")
    require(isinstance(data, dict), "source manifest must be a JSON object")
    return data


def check_packet_metadata(manifest: dict[str, Any]) -> tuple[str, dict[str, str]]:
    required = {
        "manifest_version",
        "corpus_id",
        "content_path",
        "content_sha256",
        "sha256_manifest_path",
        "language",
        "evidence_freeze_date",
        "chunking_version",
        "topic",
        "scope",
        "url_review",
        "sources",
        "claims",
        "fixtures",
        "personas",
    }
    require(
        required <= manifest.keys(),
        "source manifest is missing required top-level fields",
    )
    require(manifest["language"] == "en", "formal corpus must be English")
    require(
        manifest["evidence_freeze_date"] == "2026-08-30",
        "unexpected evidence freeze date",
    )
    require(
        manifest["topic"] == TOPIC,
        "manifest topic drifted from fixed classroom question",
    )
    require(
        manifest["chunking_version"] == "markdown-heading-paragraph-v1",
        "chunking version is not the frozen formal-content version",
    )
    require(
        manifest["sha256_manifest_path"] == "SHA256SUMS",
        "unexpected SHA-256 manifest path",
    )
    content_path = safe_packet_path(str(manifest["content_path"]))
    content = read_utf8(content_path)
    actual_content_hash = sha256(content_path)
    require(
        manifest["content_sha256"] == actual_content_hash,
        f"content SHA-256 mismatch: manifest={manifest['content_sha256']} actual={actual_content_hash}",
    )
    require(len(content.split()) >= 900, "formal corpus is unexpectedly short")
    require("## 3. Youth protection" in content, "youth-protection section missing")
    require(
        "## 4. Expression, innovation, and cultural exchange" in content,
        "trade-off section missing",
    )
    require(
        "## 5. Compare policy options" in content, "policy comparison section missing"
    )
    require(
        "[FACT]" not in content,
        "use claim markers and prose labels; stale [FACT] marker found",
    )

    source_ids: set[str] = set()
    claims_by_id: dict[str, str] = {}
    sources = manifest["sources"]
    require(
        isinstance(sources, list) and len(sources) >= 5,
        "at least five sources are required",
    )
    for source in sources:
        require(isinstance(source, dict), "source manifest item must be an object")
        for key in (
            "source_id",
            "title",
            "publisher",
            "direct_url",
            "access_date",
            "license_or_usage_basis",
            "claim_ids",
            "readability_check",
        ):
            require(key in source, f"source is missing {key}: {source!r}")
        source_id = str(source["source_id"])
        require(source_id not in source_ids, f"duplicate source ID: {source_id}")
        source_ids.add(source_id)
        parsed = urlparse(str(source["direct_url"]))
        require(
            parsed.scheme == "https" and bool(parsed.netloc),
            f"direct URL is not HTTPS: {source_id}",
        )
        require(
            source["access_date"] == manifest["evidence_freeze_date"],
            f"source date drift: {source_id}",
        )
        require(
            "official" in str(source["readability_check"]).lower(),
            f"source not marked readable: {source_id}",
        )
        publication_date = source.get("publication_date")
        if publication_date is None:
            require(
                "undated" in str(source.get("publication_date_note", "")).lower()
                or "current official"
                in str(source.get("publication_date_note", "")).lower()
                or "published in 2023"
                in str(source.get("publication_date_note", "")).lower(),
                f"undated source needs an explicit date note: {source_id}",
            )
        else:
            require(
                re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(publication_date)) is not None,
                f"invalid publication date: {source_id}",
            )
        require(
            str(source["license_or_usage_basis"]).strip(),
            f"empty usage basis: {source_id}",
        )
        require(
            isinstance(source["claim_ids"], list) and source["claim_ids"],
            f"source has no claim mapping: {source_id}",
        )

    claims = manifest["claims"]
    require(
        isinstance(claims, list) and len(claims) == 14,
        "claim ledger must contain C01-C14",
    )
    for claim in claims:
        require(isinstance(claim, dict), "claim ledger item must be an object")
        for key in (
            "claim_id",
            "claim_type",
            "epistemic_status",
            "claim_text",
            "source_ids",
            "source_locator",
        ):
            require(key in claim, f"claim is missing {key}: {claim!r}")
        claim_id = str(claim["claim_id"])
        require(claim_id not in claims_by_id, f"duplicate claim ID: {claim_id}")
        require(
            claim["claim_type"] in ALLOWED_CLAIM_TYPES,
            f"unsupported claim type: {claim_id}",
        )
        require(str(claim["claim_text"]).strip(), f"empty claim text: {claim_id}")
        require(
            isinstance(claim["source_ids"], list) and claim["source_ids"],
            f"claim has no source: {claim_id}",
        )
        require(
            set(claim["source_ids"]) <= source_ids,
            f"claim maps to unknown source: {claim_id}",
        )
        claims_by_id[claim_id] = str(claim["claim_text"])
    require(
        set(claims_by_id) == {f"C{index:02d}" for index in range(1, 15)},
        "claim IDs must be exactly C01-C14",
    )

    markers = set(MARKER_RE.findall(content))
    require(
        markers == set(claims_by_id),
        "content claim markers must map exactly to C01-C14",
    )
    for source in sources:
        require(
            set(source["claim_ids"]) <= set(claims_by_id),
            f"source maps to unknown claim: {source['source_id']}",
        )
    for claim in claims:
        mapped = [
            source["source_id"]
            for source in sources
            if claim["claim_id"] in source["claim_ids"]
        ]
        require(mapped, f"claim is not mapped from any source: {claim['claim_id']}")
    return content, claims_by_id


def check_hash_manifest(manifest: dict[str, Any]) -> None:
    hash_manifest = safe_packet_path(str(manifest["sha256_manifest_path"]))
    lines = [
        line.strip() for line in read_utf8(hash_manifest).splitlines() if line.strip()
    ]
    entries: dict[str, str] = {}
    for line in lines:
        parts = line.split(maxsplit=1)
        require(len(parts) == 2, f"invalid SHA-256 manifest line: {line!r}")
        digest, relative = parts
        require(
            re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            f"invalid SHA-256 digest: {relative}",
        )
        require(relative not in entries, f"duplicate SHA-256 manifest path: {relative}")
        entries[relative] = digest
    expected_paths = {
        "source-manifest.json",
        str(manifest["content_path"]),
        *(str(item["path"]) for item in manifest["fixtures"]),
        *(str(item["path"]) for item in manifest["personas"]),
    }
    require(
        set(entries) == expected_paths,
        "SHA-256 manifest paths do not match packet contents",
    )
    expected_hashes = {
        "source-manifest.json": sha256(MANIFEST_PATH),
        str(manifest["content_path"]): str(manifest["content_sha256"]),
    }
    for item in (*manifest["fixtures"], *manifest["personas"]):
        relative = str(item["path"])
        expected_hashes[relative] = sha256(safe_packet_path(relative))
    for relative, expected in expected_hashes.items():
        require(
            entries[relative] == expected,
            f"SHA-256 mismatch for {relative}: manifest={entries[relative]} actual={expected}",
        )


def check_no_secret_or_pii(paths: list[Path]) -> None:
    for path in paths:
        text = read_utf8(path)
        require(
            not SECRET_RE.search(text),
            f"secret-like token found in {path.relative_to(ROOT)}",
        )
        require(
            not EMAIL_RE.search(text),
            f"email-like PII found in {path.relative_to(ROOT)}",
        )


def check_fixtures(manifest: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    ensure_backend_import_path()
    from app.modules.debates.generation.retrieval import SnapshotRetriever, TurnSubquery
    from app.modules.knowledge.markdown import (
        EMBEDDING_DIMENSION,
        EMBEDDING_KEY,
        mock_embedding,
    )
    from app.modules.knowledge.mock_lexical import MOCK_LEXICAL_ANCHOR_POLICY_ID
    from app.modules.knowledge.vector import MockVectorStore, StoredVectorRow

    fixture_rows: dict[str, tuple[str, ...]] = {}
    fixtures = manifest["fixtures"]
    require(
        isinstance(fixtures, list) and len(fixtures) == 3,
        "exactly relevant, adjacent, and unrelated fixtures are required",
    )
    expected_ids = {"relevant", "adjacent", "unrelated"}
    seen: set[str] = set()
    for fixture in fixtures:
        require(isinstance(fixture, dict), "fixture manifest item must be an object")
        for key in (
            "fixture_id",
            "path",
            "expected_retrieval_status",
            "expected_grounding_mode",
            "description",
        ):
            require(key in fixture, f"fixture is missing {key}: {fixture!r}")
        fixture_id = str(fixture["fixture_id"])
        require(
            fixture_id in expected_ids and fixture_id not in seen,
            f"unexpected/duplicate fixture ID: {fixture_id}",
        )
        seen.add(fixture_id)
        path = safe_packet_path(str(fixture["path"]))
        text = read_utf8(path)
        row = StoredVectorRow(
            chunk_id=f"formal-{fixture_id}",
            source_filename=path.name,
            chunk_text=text,
            blob=mock_embedding(text),
            dimension=EMBEDDING_DIMENSION,
            key=EMBEDDING_KEY,
            document_order=0,
            chunk_index=0,
        )
        snapshot_id = f"formal-{fixture_id}-snapshot"
        result = SnapshotRetriever(MockVectorStore((row,))).retrieve(
            snapshot_id,
            (TurnSubquery("viewpoint", TOPIC),),
            policy_id=MOCK_LEXICAL_ANCHOR_POLICY_ID,
            topic_anchor=TOPIC,
        )
        actual_status = "matched" if result.matched else "no_match"
        require(
            actual_status == fixture["expected_retrieval_status"],
            f"{fixture_id} retrieval expected {fixture['expected_retrieval_status']}, got {actual_status}",
        )
        if actual_status == "matched":
            require(result.receipts, f"{fixture_id} matched without a receipt")
            require(
                all(receipt.snapshot_id == snapshot_id for receipt in result.receipts),
                f"{fixture_id} receipt crossed snapshot boundary",
            )
            fixture_rows[fixture_id] = tuple(
                receipt.evidence_id for receipt in result.receipts
            )
        else:
            require(
                not result.receipts,
                f"{fixture_id} no-match unexpectedly exposed a source",
            )
            fixture_rows[fixture_id] = ()
    require(
        seen == expected_ids, "fixture set must be exactly relevant/adjacent/unrelated"
    )
    require(
        fixture_rows["relevant"],
        "relevant fixture must provide at least one Mock receipt",
    )
    require(
        not fixture_rows["adjacent"] and not fixture_rows["unrelated"],
        "negative fixtures must have zero receipts",
    )
    return fixture_rows


def check_personas(
    manifest: dict[str, Any], evidence_ids: tuple[str, ...]
) -> tuple[str, str]:
    personas = manifest["personas"]
    require(
        isinstance(personas, list) and len(personas) == 2,
        "exactly two contrasting personas are required",
    )
    texts: dict[str, str] = {}
    for persona in personas:
        require(isinstance(persona, dict), "persona manifest item must be an object")
        for key in ("persona_id", "path", "lens"):
            require(key in persona, f"persona is missing {key}")
        persona_id = str(persona["persona_id"])
        path = safe_packet_path(str(persona["path"]))
        text = read_utf8(path)
        require(
            "# Identity" in text and "# Evidence discipline" in text,
            f"persona contract sections missing: {persona_id}",
        )
        texts[persona_id] = text
    require(
        set(texts) == {"safety-first", "creator-culture"},
        "persona IDs must be safety-first and creator-culture",
    )
    require(
        texts["safety-first"] != texts["creator-culture"],
        "contrasting personas must differ",
    )
    require(
        "youth-safety" in texts["safety-first"], "safety-first persona lens drifted"
    )
    require(
        "creator-rights" in texts["creator-culture"],
        "creator-culture persona lens drifted",
    )
    require(evidence_ids, "persona comparison needs the shared relevant evidence")
    safety_preview = (
        "[Mock safety-first] Shared receipt(s) "
        + ", ".join(evidence_ids)
        + ": test age-appropriate safeguards, independent accountability, and remedies before accepting a restriction."
    )
    culture_preview = (
        "[Mock creator-culture] Shared receipt(s) "
        + ", ".join(evidence_ids)
        + ": test expression, newcomer discovery, and cultural diversity alongside proportionate safeguards."
    )
    require(
        safety_preview != culture_preview,
        "persona previews must preserve a deliberate lens contrast",
    )
    return safety_preview, culture_preview


def main() -> int:
    ensure_backend_import_path()
    from app.modules.knowledge.mock_lexical import frozen_latin_tokens_v2

    manifest = load_manifest()
    content, _claims = check_packet_metadata(manifest)
    check_hash_manifest(manifest)
    packet_paths = [
        PACKET / "tiktok-recommendation-governance.md",
        *(safe_packet_path(str(item["path"])) for item in manifest["fixtures"]),
        *(safe_packet_path(str(item["path"])) for item in manifest["personas"]),
    ]
    check_no_secret_or_pii(packet_paths)
    evidence = check_fixtures(manifest)
    safety_preview, culture_preview = check_personas(manifest, evidence["relevant"])
    require(len(frozen_latin_tokens_v2(TOPIC)) >= 2, "topic anchor unexpectedly empty")
    print("W4-CONTENT Mock acceptance passed")
    print(f"  corpus_sha256={manifest['content_sha256']}")
    print(
        f"  claim_markers={len(MARKER_RE.findall(content))} sources={len(manifest['sources'])}"
    )
    print("  retrieval=relevant:matched; adjacent:no_match; unrelated:no_match")
    print(f"  shared_receipts={','.join(evidence['relevant'])}")
    print(f"  {safety_preview}")
    print(f"  {culture_preview}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"W4-CONTENT Mock acceptance FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
