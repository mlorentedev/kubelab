"""The edge watcher's probe: one line per target on every run (NET-005 AC12).

The rule above it groups by node. A target that is missing from a run's output,
instead of reported down, is a series that stops; Grafana resolves a stopped
series as `MissingSeries`, so a silent probe would close the very alert it
exists to raise. These tests run the real `probe.sh` under `sh` against a fake
`nc` and read what it prints, which is what Vector ships to Loki.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
PROBE = REPO / "infra/k8s/base/services/edge-watcher/probe.sh"

# Stands in for busybox `nc -z -w <s> <address> <port>`. Behaviour per address
# from files in $FAKE_DIR: <address>.down refuses (exit 1), <address>.hang never
# answers. Otherwise the port is open. Every call is logged with its arguments.
FAKE_NC = r"""#!/bin/sh
echo "nc $*" >> "$FAKE_DIR/calls"
for last; do :; done
port="$last"
address=""
for arg; do [ "$arg" = "$port" ] && break; address="$arg"; done
[ -f "$FAKE_DIR/$address.down" ] && exit 1
[ -f "$FAKE_DIR/$address.hang" ] && exec sleep 30
exit 0
"""

# Documentation addresses (RFC 5737): nothing real is ever contacted.
TARGETS = {"rpi3": ("192.0.2.6", "22"), "rpi4": ("192.0.2.10", "22")}

# The image runs busybox `sh`, the host usually dash: run every case under both.
SHELLS = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])


@pytest.fixture(params=SHELLS, ids=lambda s: " ".join(s))
def edge(tmp_path: pathlib.Path, request):
    fake = tmp_path / "fake"
    fake.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    nc = bin_dir / "nc"
    nc.write_text(FAKE_NC)
    nc.chmod(0o755)
    targets = tmp_path / "targets.txt"
    targets.write_text(
        "# Generated header\n\n" + "".join(f"{node} {address} {port}\n" for node, (address, port) in TARGETS.items())
    )
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "EDGE_TARGETS": str(targets),
        "REACH_TIMEOUT": "1",
        "NC": str(nc),
    }

    class Edge:
        def __init__(self) -> None:
            self.fake = fake
            self.targets = targets
            self.env = env

        def run(self, **overrides: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [*request.param, str(PROBE)],
                env={**self.env, **overrides},
                capture_output=True,
                text=True,
                timeout=30,
            )

    return Edge()


def _lines(result: subprocess.CompletedProcess[str]) -> list[dict]:
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def _up(result: subprocess.CompletedProcess[str]) -> dict[str, int]:
    lines = _lines(result)
    nodes = [line["node"] for line in lines]
    assert len(nodes) == len(set(nodes)), f"a target was reported twice: {result.stdout}"
    for line in lines:
        assert line["metric"] == "edge_probe", line
        assert line["namespace"] == "kubelab", line
        assert line["up"] in (0, 1), line
    return {line["node"]: line["up"] for line in lines}


def test_every_target_that_answers_is_up(edge) -> None:
    result = edge.run()
    assert result.returncode == 0, result.stderr
    assert _up(result) == {"rpi3": 1, "rpi4": 1}


def test_it_knocks_on_each_target_s_address_and_port(edge) -> None:
    edge.run()
    calls = (edge.fake / "calls").read_text().splitlines()
    for address, port in TARGETS.values():
        assert f"nc -z -w 1 {address} {port}" in calls


def test_a_refused_target_is_down_and_the_others_are_not_masked(edge) -> None:
    (edge.fake / "192.0.2.10.down").touch()
    result = edge.run()
    assert result.returncode == 0, result.stderr
    assert _up(result) == {"rpi3": 1, "rpi4": 0}


def test_a_target_that_never_answers_is_down_within_the_timeout(edge) -> None:
    """busybox `nc -w` bounds the connect; `timeout` bounds an nc that ignores it."""
    (edge.fake / "192.0.2.6.hang").touch()
    started = time.monotonic()
    result = edge.run()
    assert time.monotonic() - started < 10
    assert _up(result) == {"rpi3": 0, "rpi4": 1}


def test_a_missing_nc_reports_every_target_down(edge) -> None:
    result = edge.run(NC=str(edge.fake / "no-such-nc"))
    assert _up(result) == {"rpi3": 0, "rpi4": 0}


def test_a_row_without_a_port_is_reported_down(edge) -> None:
    edge.targets.write_text("rpi3 192.0.2.6\nrpi4 192.0.2.10 22\n")
    result = edge.run()
    assert _up(result) == {"rpi3": 0, "rpi4": 1}


@pytest.mark.parametrize("content", [None, "# only a header\n\n"], ids=["missing", "empty"])
def test_no_targets_fails_the_job(edge, content: str | None) -> None:
    """Nothing to report is a broken render or mount, never a healthy edge."""
    if content is None:
        edge.targets.unlink()
    else:
        edge.targets.write_text(content)
    result = edge.run()
    assert result.returncode != 0
    assert _lines(result) == []
    assert "targets" in result.stderr
