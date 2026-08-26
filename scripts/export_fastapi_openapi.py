"""Export the currently composed FastAPI OpenAPI document for route comparison."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.main import app


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: export_fastapi_openapi.py OUTPUT_JSON")
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"exported FastAPI OpenAPI to {output}")


if __name__ == "__main__":
    main()
