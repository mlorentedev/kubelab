"""The console image starts as the pod runs it, measured on the built image (#3443).

`sha-7df897b` went to staging and crash-looped: `nginx: [emerg] open() "/tmp/nginx.pid" failed
(13: Permission denied)`. The Dockerfile's `RUN nginx -t` ran as root, so it left a root-owned
`/tmp/nginx.pid` in the image layer, and the runtime user (uid 101) cannot open that file for
writing. Nothing static shows it: the nginx config is valid and the Dockerfile builds, and only
starting the image as its own user fails. So this test builds the image and starts it.

Two ways to run it, because the Dockerfile promises both: as the generated Deployment runs it
(a writable root, no tmpfs), and with a read-only root and a tmpfs at /tmp.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

CONTEXT = Path(__file__).resolve().parent.parent / "apps" / "console"


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], check=check, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


@pytest.fixture(scope="module")
def image() -> Iterator[str]:
    if not _docker_ready():
        if os.environ.get("CI"):
            pytest.fail("docker is required in CI to run the built console image")
        pytest.skip("docker not available: cannot run the console image (a skip is CANNOT CHECK, not OK)")
    tag = f"console-test:{uuid.uuid4().hex[:8]}"
    _docker("build", "-q", "-t", tag, str(CONTEXT))
    try:
        yield tag
    finally:
        _docker("rmi", "-f", tag, check=False)


def _serves_index(name: str) -> bool:
    return _docker("exec", name, "wget", "-qO-", "http://127.0.0.1:8080/", check=False).returncode == 0


@pytest.mark.parametrize(
    "flags",
    [
        pytest.param([], id="as-the-deployment-runs-it"),
        pytest.param(["--read-only", "--tmpfs", "/tmp"], id="read-only-root-with-a-tmpfs"),  # noqa: S108
    ],
)
def test_the_image_starts_as_its_own_user_and_serves_the_page(image: str, flags: list[str]) -> None:
    name = f"console-test-{uuid.uuid4().hex[:8]}"
    _docker("run", "-d", "--name", name, *flags, image)
    try:
        for _ in range(60):
            if _serves_index(name):
                return
            if _docker("inspect", "-f", "{{.State.Running}}", name).stdout.strip() != "true":
                break
            time.sleep(0.25)
        pytest.fail(f"the console image did not serve `/`; its log:\n{_docker('logs', name, check=False).stderr[-600:]}")
    finally:
        _docker("rm", "-f", name, check=False)
