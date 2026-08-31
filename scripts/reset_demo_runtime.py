"""Quarantine the disposable local Demo runtime for a clean reseed.

The operation is intentionally recoverable: the runtime directory is renamed
to a timestamped sibling and is never recursively deleted. Stop containers
before invoking this script; the next backend startup recreates the baseline.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime
from pathlib import Path


def product_root(value: str | None) -> Path:
    root = (Path(value) if value else Path(__file__).resolve().parents[1]).resolve()
    if not (root / "docker-compose.yml").is_file():
        raise SystemExit("reset must run from the Maya product root")
    return root


def runtime_directory(root: Path, value: str | None) -> Path:
    supplied = Path(value) if value else root / "data"
    if not supplied.is_absolute():
        supplied = root / supplied
    expected = (root / "data").resolve()
    candidate = supplied.resolve()
    if candidate != expected:
        raise SystemExit("runtime directory must resolve to the product data directory")
    if _contains_symlink(supplied, root):
        raise SystemExit("refusing to reset a symlinked runtime directory")
    return candidate


def _contains_symlink(path: Path, stop: Path) -> bool:
    """Reject a symlink at any component of the requested runtime path."""

    current = path
    while True:
        if current.is_symlink():
            return True
        # ``/var`` is a symlink on macOS. Stop once the requested path has
        # reached the already-resolved product root so harmless system aliases
        # are not mistaken for a caller-provided runtime symlink.
        if current.resolve() == stop:
            return False
        parent = current.parent
        if parent == current:
            return False
        current = parent


def quarantine_runtime(root: Path, runtime: Path) -> Path | None:
    if not runtime.exists():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = root / f"data.quarantine-{stamp}"
    suffix = 1
    while destination.exists():
        destination = root / f"data.quarantine-{stamp}-{suffix}"
        suffix += 1
    shutil.move(str(runtime), str(destination))
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Maya product root (defaults to this repository)")
    parser.add_argument("--data-dir", help="exact runtime data directory (defaults to root/data)")
    args = parser.parse_args()
    root = product_root(args.root)
    runtime = runtime_directory(root, args.data_dir)
    destination = quarantine_runtime(root, runtime)
    if destination is None:
        print("Maya Demo runtime is already clean; the next startup will seed the baseline.")
    else:
        print(f"Quarantined disposable runtime at {destination.name}.")
        print("Start the Demo again to recreate the stable system baseline.")


if __name__ == "__main__":
    main()
