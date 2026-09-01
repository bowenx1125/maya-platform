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
        if valid.returncode != 0:
            raise AssertionError("the exact product data directory must be quarantined")
        quarantined = [item for item in root.iterdir() if item.name.startswith("data.quarantine-")]
        if len(quarantined) != 1:
            raise AssertionError("exactly one recoverable quarantine copy must exist")
        if (quarantined[0] / "maya.sqlite3").read_bytes() != b"disposable":
            raise AssertionError("the quarantine copy must retain the disposable runtime")
        # The runtime path is recreated empty so a host-side policy import does
        # not fail opaquely, and so a stale container bind mount on the renamed
        # inode is visible rather than silently shadowing this directory.
        if not runtime.is_dir() or any(runtime.iterdir()):
            raise AssertionError("the reset must leave an empty runtime directory in place")
        if "docker compose down" not in valid.stdout:
            raise AssertionError("the reset must tell the operator to recreate the containers")

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
        if linked.exists():
            linked.rmdir()
        linked.symlink_to(target, target_is_directory=True)
        result = _run(script, root, linked)
        if result.returncode == 0:
            raise AssertionError("reset accepted a symlinked runtime directory")

    print("reset_demo_runtime safety probe passed: exact path, containment, and symlink guards")


if __name__ == "__main__":
    main()
