"""The run that upgrades the CI engine proves it can still build (#2722).

On 2026-10-27 a provision moved the Beelink's Docker, and BuildKit sessions began
dropping 5 s into a build. A dropped session leaves the build waiting with no error,
so the job held the runner until its 3 h timeout. The engine now moves only in a
provision that releases it, and that run smoke-builds an image under a timeout, so
a hang fails the play instead of the next job.

The build runs on the engine's own BuildKit, and its base image is pulled first under
its own timeout. The first live run did neither: it built on the Beelink's
docker-container builder, which had to pull its BuildKit image over the lab's uplink,
and it timed out reporting the engine's failure (lesson-649).
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
PULL = "Pull the smoke build's base image"
PULL_VERIFY = "Verify the smoke build's base image pulled"
SMOKE = "Smoke-build an image on this engine"
VERIFY = "Verify the smoke build finished"
# The session failed 5 s into the build and fatally 5 s later.
SESSION_DROP_SECONDS = 10


def _tasks() -> list[dict[str, Any]]:
    return yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))


def _task(name: str) -> dict[str, Any]:
    return next(t for t in _tasks() if t.get("name") == name)


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


def test_the_smoke_build_runs_after_the_role_that_upgrades_the_engine() -> None:
    """Before the upgrade, it would build on the engine the run is about to replace."""
    plays = yaml.safe_load(BEE_PLAY.read_text(encoding="utf-8"))
    roles = [r["role"].rsplit("/", 1)[-1] for r in next(p["roles"] for p in plays if "roles" in p)]
    assert roles.index("base_system") < roles.index("docker"), roles


@pytest.mark.parametrize("name", [PULL, PULL_VERIFY, SMOKE, VERIFY])
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


def _run(tmp_path: Path, behaviour: str, script: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(f"#!/bin/sh\n{DOCKER_STUBS[behaviour]}\n", encoding="utf-8")
    (bin_dir / "docker").chmod(0o755)
    rendered = (
        ansible_env(".")
        .from_string(script)
        .render(docker_smoke_build_image=DEFAULTS["docker_smoke_build_image"], docker_smoke_build_timeout_seconds=2)
    )
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "DOCKERFILE": str(tmp_path / "Dockerfile"),
        "ARGS": str(tmp_path / "args"),
    }
    return subprocess.run(
        ["bash", "-c", rendered],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _run_smoke(tmp_path: Path, behaviour: str) -> subprocess.CompletedProcess[str]:
    return _run(tmp_path, behaviour, _task(SMOKE)["shell"])


def _run_pull(tmp_path: Path, behaviour: str) -> subprocess.CompletedProcess[str]:
    return _run(tmp_path, behaviour, _task(PULL)["command"])


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


def test_the_build_runs_on_the_engines_own_buildkit(tmp_path: Path) -> None:
    """The jobs build on `default`; the current builder is whatever root last selected."""
    assert _run_smoke(tmp_path, "ok").returncode == 0
    args = (tmp_path / "args").read_text(encoding="utf-8").split()
    assert "--builder" in args and args[args.index("--builder") + 1] == "default", args


def test_the_base_image_is_pulled_before_the_build() -> None:
    names = [t.get("name") for t in _tasks()]
    assert names.index(PULL) < names.index(PULL_VERIFY) < names.index(SMOKE), names


def test_a_pull_that_makes_no_progress_is_cut_at_the_timeout(tmp_path: Path) -> None:
    assert _run_pull(tmp_path, "hang").returncode == 124


def test_the_pull_fetches_the_pinned_image(tmp_path: Path) -> None:
    assert _run_pull(tmp_path, "ok").returncode == 0
    args = (tmp_path / "args").read_text(encoding="utf-8").split()
    assert args == ["pull", DEFAULTS["docker_smoke_build_image"]], args


@pytest.mark.parametrize(
    ("result", "says"),
    [
        ({"rc": 124, "stderr_lines": []}, "the registry or the uplink"),
        ({"rc": 1, "stderr_lines": ["Error response from daemon: manifest unknown"]}, "manifest unknown"),
    ],
)
def test_a_failed_pull_blames_the_path_to_the_registry_not_the_engine(result: dict, says: str) -> None:
    pull, verify = _task(PULL), _task(PULL_VERIFY)
    assert pull["failed_when"] is False
    assert pull["register"] in verify["assert"]["that"]
    message = (
        ansible_env(".")
        .from_string(verify["assert"]["fail_msg"])
        .render(
            {pull["register"]: result},
            docker_smoke_build_image=DEFAULTS["docker_smoke_build_image"],
            docker_smoke_build_timeout_seconds=180,
        )
    )
    assert says in message and "#2722" not in message, message


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
        # A hang names its evidence instead of asserting the cause, and shows where it stopped.
        ({"rc": 124, "stderr_lines": ["#5 [2/2] RUN sleep 20"]}, "session healthcheck failed"),
        ({"rc": 124, "stderr_lines": ["#5 [2/2] RUN sleep 20"]}, "RUN sleep 20"),
        # A kill is the timeout's only past the timeout: the OOM killer also answers 137.
        ({"rc": 137, "stderr_lines": [], "delta": "0:03:30.020000"}, "killed after 0:03:30"),
        ({"rc": 137, "stderr_lines": [], "delta": "0:00:41.500000"}, "OOM killer"),
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
