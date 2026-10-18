"""infra/autoheal.sh restarts a backend that stays unhealthy, and only then.

Docker restarts a container whose process exits, never one that hangs and
is merely marked unhealthy. A stub ``docker`` on PATH replays one
``docker ps`` answer per check and records restarts.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra" / "autoheal.sh"

STUB = """#!/bin/sh
dir="$(dirname "$0")"
case "$1" in
  ps)
    echo "$*" >>"$dir/ps-args.log"
    line=$(head -n 1 "$dir/schedule" 2>/dev/null)
    tail -n +2 "$dir/schedule" >"$dir/schedule.next" 2>/dev/null
    mv "$dir/schedule.next" "$dir/schedule"
    [ "$line" = "-" ] || echo "$line"
    ;;
  inspect) echo "/maya-production-backend-1" ;;
  restart) echo "$4" >>"$dir/restarts.log" ;;
esac
"""


def _run(tmp_path: Path, schedule: list[str], **env: str) -> tuple[str, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "docker"
    stub.write_text(STUB)
    stub.chmod(0o755)
    (bin_dir / "schedule").write_text("\n".join(schedule) + "\n")
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "AUTOHEAL_INTERVAL_SECONDS": "0",
        "AUTOHEAL_CONFIRM_CHECKS": "3",
        "AUTOHEAL_COOLDOWN_SECONDS": "300",
        "AUTOHEAL_MAX_LOOPS": str(len(schedule)),
        "AUTOHEAL_STATE_DIR": str(tmp_path / "state"),
        **env,
    }
    result = subprocess.run(
        ["sh", str(SCRIPT)], env=environment, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    restarts_log = bin_dir / "restarts.log"
    restarts = restarts_log.read_text().split() if restarts_log.exists() else []
    return result.stdout, restarts


def test_restarts_only_after_three_unhealthy_checks_in_a_row(tmp_path: Path) -> None:
    output, restarts = _run(tmp_path, ["abc123", "abc123", "abc123"])
    assert restarts == ["abc123"]
    assert "check=1/3" in output and "check=2/3" in output
    assert "restarting name=maya-production-backend-1 after 3 unhealthy checks" in output
    args = (tmp_path / "bin" / "ps-args.log").read_text()
    # Only opted-in containers that Docker itself reports unhealthy.
    assert "--filter label=com.maya.autoheal=true --filter health=unhealthy" in args


def test_a_recovery_resets_the_count(tmp_path: Path) -> None:
    _output, restarts = _run(tmp_path, ["abc123", "abc123", "-", "abc123", "abc123"])
    assert restarts == []


def test_cooldown_prevents_a_restart_loop(tmp_path: Path) -> None:
    output, restarts = _run(tmp_path, ["abc123"] * 7)
    assert restarts == ["abc123"]  # restarted once, then held off for 300 s
    assert "restart skipped" in output


def test_dry_run_restarts_nothing(tmp_path: Path) -> None:
    output, restarts = _run(tmp_path, ["abc123"] * 3, AUTOHEAL_DRY_RUN="true")
    assert restarts == []
    assert "dry-run would restart name=maya-production-backend-1" in output


class _ComposeLoader(yaml.SafeLoader):
    """Read Compose's ``!override`` / ``!reset`` tags as plain values."""


def _compose_tag(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> object:
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)  # type: ignore[arg-type]


_ComposeLoader.add_multi_constructor("!", _compose_tag)


def test_production_compose_wires_the_watcher_to_the_backend_only() -> None:
    compose = yaml.load(  # noqa: S506 - SafeLoader subclass
        (ROOT / "docker-compose.production.yml").read_text(), Loader=_ComposeLoader
    )
    services = compose["services"]
    assert services["backend"]["labels"] == {"com.maya.autoheal": "true"}
    assert all("labels" not in services[name] for name in ("gateway", "frontend", "postgres"))
    watcher = services["autoheal"]
    assert watcher["image"].startswith("docker:") and watcher["image"].endswith("-cli")
    assert watcher["restart"] == "unless-stopped"
    assert watcher["network_mode"] == "none"
    assert "./infra/autoheal.sh:/autoheal.sh:ro" in watcher["volumes"]
    assert watcher["environment"]["AUTOHEAL_LABEL"] == "com.maya.autoheal=true"
