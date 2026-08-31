"""Safety probes for the recoverable local-Demo runtime reset."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def _run(script: Path, root: Path, data_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), "--root", str(root), "--data-dir", str(data_dir)],
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> None:
    script = Path(__file__).with_name("reset_demo_runtime.py")
    with TemporaryDirectory(prefix="maya-reset-test-") as directory:
        root = (Path(directory) / "product").resolve()
        root.mkdir()
        (root / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
        runtime = root / "data"
        runtime.mkdir()
        (runtime / "maya.sqlite3").write_bytes(b"disposable")
        valid = _run(script, root, runtime)
        if valid.returncode != 0 or runtime.exists():
            raise AssertionError("the exact product data directory must be quarantined")

        external = root.parent / "unrelated" / "data"
        external.mkdir(parents=True)
        invalid_paths = (external, root, root.parent)
        for invalid in invalid_paths:
            result = _run(script, root, invalid)
            if result.returncode == 0:
                raise AssertionError(f"reset accepted an unsafe path: {invalid.name}")

        target = root.parent / "target-data"
        target.mkdir()
        linked = root / "data"
        linked.symlink_to(target, target_is_directory=True)
        result = _run(script, root, linked)
        if result.returncode == 0:
            raise AssertionError("reset accepted a symlinked runtime directory")

    print("reset_demo_runtime safety probe passed: exact path, containment, and symlink guards")


if __name__ == "__main__":
    main()
