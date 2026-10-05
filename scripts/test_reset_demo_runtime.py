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
        sentinel = target / "sentinel.txt"
        sentinel.write_text("external target remains untouched", encoding="utf-8")
        quarantines_before_link_check = {
            item.name
            for item in root.iterdir()
            if item.name.startswith("data.quarantine-")
        }
        linked = root / "data"
        if linked.exists():
            linked.rmdir()
        try:
            linked.symlink_to(target, target_is_directory=True)
        except OSError as error:
            if sys.platform != "win32" or getattr(error, "winerror", None) != 1314:
                raise
            # Creating a symbolic link requires a Windows privilege unless
            # Developer Mode is enabled. A junction exercises the same
            # directory-redirection safety rule without that privilege.
            junction = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(linked), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if junction.returncode != 0:
                raise AssertionError(
                    "could not create the junction safety fixture"
                ) from error
            if not linked.is_junction():
                raise AssertionError("the Windows fallback fixture must be a junction")
        result = _run(script, root, linked)
        if (
            result.returncode == 0
            or "refusing to reset a symlinked runtime directory" not in result.stderr
        ):
            raise AssertionError("reset did not reject a redirected runtime directory")
        if not sentinel.is_file() or sentinel.read_text(encoding="utf-8") != (
            "external target remains untouched"
        ):
            raise AssertionError(
                "reset changed the external target behind a rejected link"
            )
        quarantines_after_link_check = {
            item.name
            for item in root.iterdir()
            if item.name.startswith("data.quarantine-")
        }
        if quarantines_after_link_check != quarantines_before_link_check:
            raise AssertionError(
                "reset created a quarantine directory for a rejected link"
            )

    print("reset_demo_runtime safety probe passed: exact path, containment, and symlink guards")


if __name__ == "__main__":
    main()
