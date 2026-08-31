"""Print safe local Demo readiness, composition and dirty-work summary."""

from __future__ import annotations

import argparse
import json
from urllib.error import URLError
from urllib.request import Request, urlopen


def fetch(base_url: str, path: str) -> object:
    request = Request(f"{base_url.rstrip('/')}{path}", headers={"Accept": "application/json"})
    with urlopen(request, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8080")
    args = parser.parse_args()
    try:
        readiness = fetch(args.url, "/health/ready")
        status = fetch(args.url, "/api/v1/demo/status")
    except (OSError, URLError, ValueError) as exc:
        print(f"Maya Demo unavailable: {type(exc).__name__}")
        raise SystemExit(1) from None
    if not isinstance(status, dict) or not isinstance(readiness, dict):
        print("Maya Demo returned an invalid safe status payload.")
        raise SystemExit(1)
    print(f"Readiness: {readiness.get('status', 'unknown')}")
    baseline = status.get("baseline")
    if isinstance(baseline, dict):
        print(f"Baseline: {'ready' if baseline.get('usable') else 'needs reseed'}")
    composition = status.get("composition")
    if isinstance(composition, dict):
        for component in composition.get("components", []):
            if isinstance(component, dict):
                print(f"{component.get('label', 'component')}: {component.get('mode', 'unknown')}")
    print(
        "Dirty work: "
        f"Agents={status.get('dirty_agents', 0)} "
        f"Debates={status.get('dirty_debates', 0)} "
        f"Interactions={status.get('dirty_interactions', 0)}"
    )


if __name__ == "__main__":
    main()
