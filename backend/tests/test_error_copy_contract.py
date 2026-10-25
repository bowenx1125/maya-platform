"""Every error code the backend can send has English copy in the frontend (PR D3).

Codes are found statically: the first argument of ``PlatformError``,
``conflict``, ``unprocessable`` and other ``*Error`` calls, and string values
given to ``safe_error_code`` / ``code`` / ``error_code`` or held in ``*CODE*``
constants. Copy is either a specific i18n message (``errorCodeKeys`` in
``frontend/lib/i18n.ts``) or an entry in ``frontend/lib/error-copy.json``.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
CATALOG = ROOT / "frontend" / "lib" / "error-copy.json"
I18N = ROOT / "frontend" / "lib" / "i18n.ts"
CODE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
CODE_FIELDS = {"safe_error_code", "code", "error_code"}
RAISERS = {"PlatformError", "conflict", "unprocessable"}
CJK = re.compile(r"[一-鿿]")


def _code(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and CODE.match(node.value):
        return node.value
    return None


def backend_codes() -> set[str]:
    codes: set[str] = set()
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None) or ""
                if (name in RAISERS or name.endswith("Error")) and node.args:
                    if found := _code(node.args[0]):
                        codes.add(found)
                for keyword in node.keywords:
                    if keyword.arg in CODE_FIELDS and (found := _code(keyword.value)):
                        codes.add(found)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    name = getattr(target, "id", None) or getattr(target, "attr", None) or ""
                    if name in CODE_FIELDS and (found := _code(node.value)):
                        codes.add(found)
                    if name.isupper() and "CODE" in name:
                        codes.update(
                            found for item in ast.walk(node.value) if (found := _code(item))
                        )
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value in CODE_FIELDS
                        and (found := _code(value))
                    ):
                        codes.add(found)
    return codes


def specific_codes() -> set[str]:
    source = I18N.read_text(encoding="utf-8")
    block = source[
        source.index("const errorCodeKeys") : source.index("export function errorCopyFor")
    ]
    return set(re.findall(r"^\s+([a-z][a-z0-9_]+):\s*\"", block, re.MULTILINE))


def catalog() -> dict[str, dict[str, object]]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def test_every_backend_error_code_has_copy() -> None:
    copied = specific_codes() | set(catalog()["codes"])
    missing = sorted(backend_codes() - copied)
    assert missing == [], (
        "Add copy for these codes to frontend/lib/error-copy.json "
        f"(or a specific message in errorCodeKeys): {missing}"
    )


def test_the_catalog_holds_only_codes_the_backend_sends() -> None:
    stale = sorted(set(catalog()["codes"]) - backend_codes())
    assert stale == [], f"Remove copy for codes the backend no longer sends: {stale}"


def test_specific_copy_is_not_repeated_in_the_catalog() -> None:
    assert sorted(specific_codes() & set(catalog()["codes"])) == []


def test_every_message_has_english_copy_only() -> None:
    data = catalog()
    messages = data["messages"]
    assert isinstance(messages, dict)
    for code, key in data["codes"].items():  # type: ignore[union-attr]
        assert key in messages, f"{code} names a missing message {key}"
    for key, copy in messages.items():
        # The UI is English only (owner decision 2026-10-25).
        assert set(copy) == {"en"}, key
        assert copy["en"].strip() and not CJK.search(copy["en"]), key
