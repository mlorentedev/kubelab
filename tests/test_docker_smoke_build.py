"""The run that upgrades the CI engine proves it can still build (#2722).

On 2026-10-27 a provision moved the Beelink's Docker, and BuildKit sessions began
dropping 5 s into a build. A dropped session leaves the build waiting with no error,
so the job held the runner until its 3 h timeout. The engine now moves only in a
provision that releases it, and that run smoke-builds an image under a timeout, so
a hang fails the play instead of the next job.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ansible_jinja import ansible_env, task_runs

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra/ansible/roles/docker"
BEE_PLAY = REPO / "infra/ansible/playbooks/provision-bee.yml"
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
SMOKE = "Smoke-build an image on this engine"
VERIFY = "Verify the smoke build finished"
# The session failed 5 s into the build and fatally 5 s later.
SESSION_DROP_SECONDS = 10


def _task(name: str) -> dict[str, Any]:
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))
    return next(t for t in tasks if t.get("name") == name)


def _bee_smoke_flag(**extra: Any) -> bool:
    plays = yaml.safe_load(BEE_PLAY.read_text(encoding="utf-8"))
    roles = next(p["roles"] for p in plays if "roles" in p)
    docker = next(r for r in roles if r["role"].endswith("/docker"))
    rendered = ansible_env(".").from_string(docker["vars"]["docker_smoke_build"]).render(**extra)
    return rendered == "True"


@pytest.mark.parametrize(
    ("extra", "expected"),
    [({}, False), ({"base_system_release_holds": False}, False), ({"base_system_release_holds": "true"}, True)],
)
def test_the_beelink_smoke_builds_only_in_the_run_that_releases_its_engine(extra: dict, expected: bool) -> None:
    assert _bee_smoke_flag(**extra) is expected


@pytest.mark.parametrize("name", [SMOKE, VERIFY])
def test_the_smoke_build_is_off_by_default_and_in_check_mode(name: str) -> None:
    task = _task(name)
    assert not task_runs(task, {"docker_smoke_build": DEFAULTS["docker_smoke_build"], "ansible_check_mode": False})
    assert not task_runs(task, {"docker_smoke_build": True, "ansible_check_mode": True})
    assert task_runs(task, {"docker_smoke_build": True, "ansible_check_mode": False})


DOCKER_STUBS = {
    "hang": "sleep 30",
    "error": "echo 'ERROR: failed to solve: busybox: not found' >&2; exit 1",
    "ok": 'cat > "$DOCKERFILE"; echo "$@" > "$ARGS"; exit 0',
}


def _run_smoke(tmp_path: Path, behaviour: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(f"#!/bin/sh\n{DOCKER_STUBS[behaviour]}\n", encoding="utf-8")
    (bin_dir / "docker").chmod(0o755)
    script = (
        ansible_env(".")
        .from_string(_task(SMOKE)["shell"])
        .render(docker_smoke_build_image=DEFAULTS["docker_smoke_build_image"], docker_smoke_build_timeout_seconds=2)
    )
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "DOCKERFILE": str(tmp_path / "Dockerfile"),
        "ARGS": str(tmp_path / "args"),
    }
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=30, check=False)


def test_a_build_that_makes_no_progress_is_cut_at_the_timeout(tmp_path: Path) -> None:
    assert _run_smoke(tmp_path, "hang").returncode == 124


def test_a_build_that_errors_reports_its_own_exit_code(tmp_path: Path) -> None:
    assert _run_smoke(tmp_path, "error").returncode == 1


def test_the_build_outlives_the_window_the_session_dropped_in(tmp_path: Path) -> None:
    assert _run_smoke(tmp_path, "ok").returncode == 0
    dockerfile = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.startswith(f"FROM {DEFAULTS['docker_smoke_build_image']}\n"), dockerfile
    sleep = re.search(r"^RUN sleep (\d+)$", dockerfile, re.M)
    assert sleep and SESSION_DROP_SECONDS < int(sleep[1]) < DEFAULTS["docker_smoke_build_timeout_seconds"], dockerfile
    args = (tmp_path / "args").read_text(encoding="utf-8").split()
    # A cached step would finish at once and never hold a session open.
    assert "--no-cache" in args
    # The Dockerfile comes on stdin, and the result is discarded rather than loaded.
    assert args[-1] == "-" and "type=cacheonly" in args, args


def test_a_client_that_ignores_the_term_is_killed() -> None:
    """A buildx client blocked on the dead session may ignore SIGTERM, and the play would hang."""
    assert re.search(r"\btimeout --kill-after=\d+ ", _task(SMOKE)["shell"]), _task(SMOKE)["shell"]


@pytest.mark.parametrize(("rc", "passes"), [(0, True), (1, False), (124, False), (137, False)])
def test_only_a_build_that_finished_passes(rc: int, passes: bool) -> None:
    smoke, verify = _task(SMOKE), _task(VERIFY)
    # The shell must not fail first: the assert is what says why.
    assert smoke["failed_when"] is False
    that = verify["assert"]["that"]
    assert smoke["register"] in that and smoke["register"] in verify["assert"]["fail_msg"]
    rendered = ansible_env(".").from_string("{{ (" + that + ") }}").render({smoke["register"]: {"rc": rc}})
    assert rendered == str(passes), rendered


@pytest.mark.parametrize(
    ("result", "says"),
    [
        ({"rc": 124, "stderr_lines": []}, "no progress"),
        ({"rc": 137, "stderr_lines": []}, "no progress"),
        ({"rc": 1, "stderr_lines": ["#1 load", "ERROR: failed to solve: busybox: not found"]}, "failed to solve"),
    ],
)
def test_the_failure_names_a_hang_apart_from_an_error(result: dict, says: str) -> None:
    message = (
        ansible_env(".")
        .from_string(_task(VERIFY)["assert"]["fail_msg"])
        .render(_docker_smoke_build=result, docker_smoke_build_timeout_seconds=180)
    )
    assert says in message, message
    assert ("#2722" in message) is (result["rc"] in (124, 137)), message
