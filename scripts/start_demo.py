"""Start the local Maya Demo stack through its pinned Compose definition."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="reuse existing images instead of rebuilding source changes",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / "docker-compose.yml").is_file():
        raise SystemExit("start must run from the Maya product root")
    command = ["docker", "compose", "up", "-d"]
    if not args.no_build:
        command.append("--build")
    subprocess.run(command, cwd=root, check=True)
    print("Maya Demo started; backend startup will ensure the stable baseline Agent.")


if __name__ == "__main__":
    main()
