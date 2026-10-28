"""A Corefile change must reach clients when the deploy says it did (lesson-560).

Clients ask Pi-hole, and Pi-hole caches each answer CoreDNS gave it for the
record's TTL. The CoreDNS `hosts` plugin answers with a TTL of 3600s, so after a
deploy that moved `status.kubelab.live`, CoreDNS answered the new address and
Pi-hole kept serving the old one, with 710s still to run, measured 2026-10-11.

The first fix restarted Pi-hole on every Corefile change. Since ADR-075 that
Pi-hole is the LAN's resolver, and a restart is about ten seconds in which no
lab client resolves anything (#2716). A Corefile-only change now empties the
cache in the running process instead (lesson-639).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest
import yaml

from tests.ansible_jinja import task_runs

ROLE = Path(__file__).resolve().parent.parent / "infra/ansible/roles/coredns"
TASKS = ROLE / "tasks/main.yml"
FLUSH = "Empty Pi-hole's cache on a Corefile change"
RESTART = "Restart Pi-hole on config change"
# The container the role runs Pi-hole in; the flush task execs into it.
EXEC_PREFIX = "docker exec pihole "


def _tasks() -> list[dict]:
    play = yaml.safe_load(TASKS.read_text())
    return [task for block in play for task in block.get("block", [block])]


def _task(name: str) -> dict:
    found = [t for t in _tasks() if t.get("name") == name]
    assert len(found) == 1, f"expected one task named {name!r}"
    return found[0]


def _changes(corefile: bool, forwarding: bool) -> dict:
    return {"corefile": {"changed": corefile}, "pihole_conf": {"changed": forwarding}}


def test_the_change_flags_are_the_templates_registers() -> None:
    assert _task("Template Corefile")["register"] == "corefile"
    assert _task("Template pihole-forwarding.conf")["register"] == "pihole_conf"


@pytest.mark.parametrize(
    ("corefile", "forwarding", "restarts"),
    [(True, False, False), (False, True, True), (True, True, True), (False, False, False)],
)
def test_only_a_forwarding_change_restarts_pihole(corefile: bool, forwarding: bool, restarts: bool) -> None:
    """v6 reloads no dnsmasq config without a restart; nothing else needs one."""
    assert task_runs(_task(RESTART), _changes(corefile, forwarding)) is restarts


@pytest.mark.parametrize(
    ("corefile", "forwarding", "flushes"),
    # A restart already empties the cache, so the flush runs only without one.
    [(True, False, True), (True, True, False), (False, True, False), (False, False, False)],
)
def test_a_corefile_only_change_empties_the_cache(corefile: bool, forwarding: bool, flushes: bool) -> None:
    assert task_runs(_task(FLUSH), _changes(corefile, forwarding)) is flushes


def test_the_flush_runs_in_the_pihole_container() -> None:
    assert _task(FLUSH)["command"].startswith(EXEC_PREFIX)


def test_the_flush_runs_once_coredns_and_pihole_answer() -> None:
    """Earlier, Pi-hole could cache the old CoreDNS's answers again; the resolve
    wait after it is what proves a client gets an answer."""
    names = [t.get("name") for t in _tasks()]
    flush = names.index(FLUSH)
    assert names.index("Restart CoreDNS on config change") < flush
    assert names.index("Wait for CoreDNS") < flush
    assert names.index("Wait for Pi-hole") < flush
    assert flush < names.index("Wait for Pi-hole to resolve through CoreDNS")


def test_pihole_restarts_after_coredns() -> None:
    """A regression guard, not evidence for the fix: the order predates it. Pi-hole
    restarting before CoreDNS would cache the old answers again."""
    names = [t.get("name") for t in _tasks()]
    assert names.index("Restart CoreDNS on config change") < names.index(RESTART)


# --- The flush, measured on the images the role deploys -----------------------

OLD, NEW, NAME = "10.9.9.1", "10.9.9.2", "moved.example.test"


def _docker(*args: str, check: bool = True) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, timeout=300).stdout.strip()


def _corefile(path: Path, address: str) -> None:
    # Rewritten in place: a single-file bind mount follows the inode, not the name.
    path.write_text(f"example.test {{\n  hosts {{\n    {address} {NAME}\n    ttl 3600\n  }}\n}}\n")


def _answer(container: str, server: str = "127.0.0.1") -> tuple[int, str] | None:
    """(TTL, address) of the A record, or None while nothing answers it."""
    out = _docker("exec", container, "dig", f"@{server}", NAME, "+noall", "+answer", "+time=1", "+tries=1", check=False)
    fields = out.split()
    return (int(fields[1]), fields[4]) if len(fields) == 5 and fields[3] == "A" else None


def _until(probe, expected: str, timeout: float = 120) -> tuple[int, str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        answer = probe()
        if answer and answer[1] == expected:
            return answer
        time.sleep(1)
    pytest.fail(f"{NAME} never answered {expected}, last answer {answer}")


@pytest.mark.integration
def test_the_flush_serves_a_moved_record_without_restarting_pihole(docker_mount_dir: Path) -> None:
    if shutil.which("docker") is None:
        if os.environ.get("CI"):
            pytest.fail("docker not on PATH in CI: the Pi-hole flush went untested")
        pytest.skip("docker not on PATH: cannot run Pi-hole (a skip is CANNOT CHECK, not OK)")
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    flush = _task(FLUSH)["command"].removeprefix(EXEC_PREFIX).split()
    tag = uuid.uuid4().hex[:8]
    network, coredns, pihole = f"dns007-{tag}", f"dns007-coredns-{tag}", f"dns007-pihole-{tag}"
    corefile, forwarding = docker_mount_dir / "Corefile", docker_mount_dir / "forwarding.conf"
    _corefile(corefile, OLD)
    try:
        _docker("network", "create", network)
        _docker("run", "-d", "--name", coredns, "--network", network,
                "-v", f"{corefile}:/etc/coredns/Corefile:ro",
                defaults["coredns_image"], "-conf", "/etc/coredns/Corefile")  # fmt: skip
        coredns_ip = _docker("inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", coredns)
        forwarding.write_text(f"server=/example.test/{coredns_ip}#53\n")
        _docker("run", "-d", "--name", pihole, "--network", network,
                "-e", "FTLCONF_misc_etc_dnsmasq_d=true",
                "-v", f"{forwarding}:/etc/dnsmasq.d/forwarding.conf:ro",
                defaults["pihole_image"])  # fmt: skip
        _until(lambda: _answer(pihole), OLD)

        _corefile(corefile, NEW)
        _docker("restart", coredns)
        _until(lambda: _answer(pihole, server=coredns_ip), NEW)
        # The old address while CoreDNS answers the new one can only come from the
        # cache. Without this the check is vacuous: a Pi-hole that never cached passes it.
        answer = _answer(pihole)
        assert answer and answer[1] == OLD, f"Pi-hole did not serve the cached answer: {answer}"

        ftl = _docker("exec", pihole, "pidof", "pihole-FTL")
        _docker("exec", pihole, *flush)

        # Seconds, against the up to 3600 the cached answer had left.
        _until(lambda: _answer(pihole), NEW, timeout=10)
        assert _docker("exec", pihole, "pidof", "pihole-FTL") == ftl, "the flush restarted FTL"
    finally:
        _docker("rm", "-f", coredns, pihole, check=False)
        _docker("network", "rm", network, check=False)
