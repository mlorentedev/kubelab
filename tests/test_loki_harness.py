"""The Loki harness says why Docker could not start its container (#2792).

A `docker run` that exits 125 failed before any container existed: a pull refused
or rate-limited, or a daemon error. Docker's stderr is the one line that says
which, and a bare `CalledProcessError` carries it where pytest's report does not
print it, so 15 rule tests erred in CI with no cause anywhere in the log.
"""

from __future__ import annotations

import shutil

import pytest

from tests.loki_harness import run_loki


def test_a_failed_docker_run_fails_the_test_with_dockers_stderr(tmp_path, monkeypatch):
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/bin/sh\necho 'toomanyrequests: You have reached your pull rate limit' >&2\nexit 125\n", encoding="utf-8"
    )
    docker.chmod(0o755)
    # The fake alone on PATH: a host Docker must not answer in its place.
    monkeypatch.setenv("PATH", str(tmp_path))
    assert shutil.which("docker") == str(docker)
    with pytest.raises(pytest.fail.Exception, match=r"exited 125: toomanyrequests: You have reached"):
        next(run_loki())
