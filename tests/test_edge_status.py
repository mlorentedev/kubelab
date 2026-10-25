"""The edge reports its uplink as up, behind a portal, or dead (NET-005 AC5, ADR-075 D3).

At a hotel the uplink is captive until someone logs in, and the RPi4 has no screen.
The status script runs on the edge and asks a connectivity check over the uplink:
`204` is up, any other HTTP answer is a portal, and no answer is dead. Each state
has its own exit code, so a script can tell them apart. It also says whether a
public resolver and the lease's resolver answer, which decides the login mode
(task 31), and whether the uplink's MAC is the one in SOPS, which the portal's
entitlement is bound to, without printing either MAC.

The script runs under dash against the role's own resolver and `.link` renders,
with fake `curl` and `dig` fed recorded answers. `make edge-status` runs it over
SSH to the edge's LAN address: the tailnet rides on the uplink being reported on.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra" / "ansible" / "roles" / "gateway"
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
DEFAULTS: dict[str, Any] = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
NETWORKING = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())["networking"]
SCRIPT = ROLE / "files" / "edge-status.sh"
UPLINK = NETWORKING["edge"]["uplink"]["interface"]
SHELL = shutil.which("dash") or "/bin/sh"
CHECK_HOST = "connectivitycheck.gstatic.com"
# Documentation ranges (RFC 5737) and a locally administered MAC: none is a lab address.
UPLINK_MAC = "02:00:5E:10:00:01"
OTHER_MAC = "02:00:5e:10:00:02"
LEASE_ADDRESS = "198.51.100.23"
LEASE_DNS = "198.51.100.1"
CHECK_IP = "192.0.2.204"
PORTAL_IP = "192.0.2.80"
IFINDEX = "7"
UP, PORTAL, DEAD = 0, 2, 3


def _render(name: str, **variables: Any) -> str:
    env = ansible_env(str(ROLE / "templates"), trim_blocks=True, lstrip_blocks=True)
    return env.get_template(f"{name}.j2").render(**{**DEFAULTS, **variables})


def _task_dest(src: str) -> str:
    (task,) = [t for t in TASKS if (t.get("template") or t.get("copy") or {}).get("src") == src]
    return (task.get("template") or task.get("copy"))["dest"]


PUBLIC_RESOLVERS = DEFAULTS["gateway_dns_servers"].split(",")
CURL = """echo "curl $*" >>"$FAKE/calls"
code=$(cat "$FAKE/http_code" 2>/dev/null || echo 000)
printf '%s' "$code"
[ "$code" = 000 ] && exit 28
exit 0
"""
DIG = """echo "dig $*" >>"$FAKE/calls"
for arg in "$@"; do case $arg in @*) server=${arg#@} ;; esac; done
[ -f "$FAKE/dns_$server" ] || exit 9
cat "$FAKE/dns_$server"
"""


@dataclass
class Edge:
    """The edge as the status script sees it: sysfs, the lease, the role's files."""

    root: Path
    calls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in ("fake", "bin", "leases", "etc"):
            (self.root / name).mkdir()
        for name, body in (("curl", CURL), ("dig", DIG)):
            (self.root / "bin" / name).write_text(f"#!/bin/sh\n{body}")
            (self.root / "bin" / name).chmod(0o755)
        device = self.root / "net" / UPLINK
        device.mkdir(parents=True)
        (device / "ifindex").write_text(f"{IFINDEX}\n")
        self.mac(UPLINK_MAC.lower())
        (self.root / "etc" / "link").write_text(
            _render("uplink.link", gateway_uplink_mac=UPLINK_MAC, gateway_uplink_interface=UPLINK)
        )
        (self.root / "etc" / "resolv.conf").write_text(_render("resolv.conf"))
        self.lease(dns=LEASE_DNS)

    def mac(self, value: str) -> None:
        (self.root / "net" / UPLINK / "address").write_text(f"{value}\n")

    def lease(self, *, dns: str | None) -> None:
        lines = ["# This is private data. Do not parse.", f"ADDRESS={LEASE_ADDRESS}"]
        if dns:
            lines.append(f"DNS={dns} 198.51.100.2")
        (self.root / "leases" / IFINDEX).write_text("\n".join(lines) + "\n")

    def no_lease(self) -> None:
        (self.root / "leases" / IFINDEX).unlink()

    def answers(self, server: str, address: str) -> None:
        (self.root / "fake" / f"dns_{server}").write_text(f"{CHECK_HOST}.\n{address}\n")

    def http(self, code: str) -> None:
        (self.root / "fake" / "http_code").write_text(code)

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        calls = self.root / "fake" / "calls"
        calls.unlink(missing_ok=True)
        env = {
            "PATH": f"{self.root / 'bin'}:/usr/bin:/bin",
            "FAKE": str(self.root / "fake"),
            "EDGE_SYS_NET": str(self.root / "net"),
            "EDGE_LEASES_DIR": str(self.root / "leases"),
            "EDGE_LINK_FILE": str(self.root / "etc" / "link"),
            "EDGE_RESOLV_CONF": str(self.root / "etc" / "resolv.conf"),
        }
        result = subprocess.run(
            [SHELL, str(SCRIPT), *(args or (UPLINK,))], capture_output=True, text=True, env=env, check=False
        )
        self.calls = calls.read_text().splitlines() if calls.exists() else []
        return result


def _report(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    return dict(line.split(": ", 1) for line in result.stdout.splitlines() if ": " in line)


@pytest.fixture
def edge(tmp_path: Path) -> Edge:
    edge = Edge(tmp_path)
    edge.answers(PUBLIC_RESOLVERS[0], CHECK_IP)
    edge.answers(LEASE_DNS, CHECK_IP)
    return edge


# ------------------------------------------------------------- the three states


def test_a_204_over_the_uplink_is_up(edge: Edge) -> None:
    edge.http("204")
    result = edge.run()
    assert result.returncode == UP, result.stderr
    assert _report(result)["uplink"] == "up"


@pytest.mark.parametrize("code", ["302", "200", "511", "403"])
def test_any_other_http_answer_is_a_portal(edge: Edge, code: str) -> None:
    """A portal redirects, serves its page in place, or says 511 (RFC 6585)."""
    edge.http(code)
    result = edge.run()
    assert result.returncode == PORTAL
    assert _report(result)["uplink"].startswith("portal")
    assert code in _report(result)["uplink"]


def test_no_http_answer_is_dead(edge: Edge) -> None:
    edge.http("000")
    result = edge.run()
    assert result.returncode == DEAD
    assert _report(result)["uplink"].startswith("dead")


def test_no_lease_is_dead_without_asking(edge: Edge) -> None:
    edge.no_lease()
    result = edge.run()
    assert result.returncode == DEAD
    assert "lease" in _report(result)["uplink"]
    assert not [call for call in edge.calls if call.startswith("curl")]


def test_no_adapter_is_dead_without_asking(edge: Edge) -> None:
    shutil.rmtree(edge.root / "net" / UPLINK)
    result = edge.run()
    assert result.returncode == DEAD
    assert "adapter" in _report(result)["uplink"]
    assert _report(result)["uplink MAC"] == "unreadable"
    assert not edge.calls


def test_no_resolver_answering_is_dead(edge: Edge) -> None:
    for answer in (edge.root / "fake").glob("dns_*"):
        answer.unlink()
    edge.http("204")
    result = edge.run()
    assert result.returncode == DEAD
    assert "resolver" in _report(result)["uplink"]


def test_the_three_states_have_distinct_codes() -> None:
    assert len({UP, PORTAL, DEAD}) == 3
    assert 0 not in (PORTAL, DEAD)


def test_usage(edge: Edge) -> None:
    assert edge.run(UPLINK, "extra").returncode == 64


# ------------------------------------------------------------ how it asks


def test_the_check_goes_out_the_uplink(edge: Edge) -> None:
    """Bound to the uplink, so a tailnet route or the LAN cannot answer for it."""
    edge.http("204")
    edge.run()
    (curl,) = [call for call in edge.calls if call.startswith("curl")]
    assert f"--interface {UPLINK}" in curl
    assert f"http://{CHECK_HOST}/generate_204" in curl
    assert "--max-time" in curl
    assert "--location" not in curl and " -L" not in curl, "a followed redirect would hide the portal"


def test_the_check_uses_the_public_answer_when_there_is_one(edge: Edge) -> None:
    edge.answers(LEASE_DNS, PORTAL_IP)
    edge.http("204")
    edge.run()
    (curl,) = [call for call in edge.calls if call.startswith("curl")]
    assert f"--resolve {CHECK_HOST}:80:{CHECK_IP}" in curl


def test_the_check_falls_back_to_the_lease_resolver(edge: Edge) -> None:
    """Before the login, a portal often answers DNS only from its own resolver."""
    (edge.root / "fake" / f"dns_{PUBLIC_RESOLVERS[0]}").unlink()
    edge.answers(LEASE_DNS, PORTAL_IP)
    edge.http("302")
    result = edge.run()
    (curl,) = [call for call in edge.calls if call.startswith("curl")]
    assert f"--resolve {CHECK_HOST}:80:{PORTAL_IP}" in curl
    assert result.returncode == PORTAL


# -------------------------------------------------------------- what it reports


@pytest.mark.parametrize(
    ("public", "lease", "expected"),
    [
        (True, True, ("answers", "answers")),
        (False, True, ("no answer", "answers")),
        (True, False, ("answers", "no answer")),
        (False, False, ("no answer", "no answer")),
    ],
)
def test_it_reports_which_resolvers_answer(edge: Edge, public: bool, lease: bool, expected: tuple[str, str]) -> None:
    """B3 reads this before the first login: it decides the login mode (task 31)."""
    if not public:
        (edge.root / "fake" / f"dns_{PUBLIC_RESOLVERS[0]}").unlink()
    if not lease:
        (edge.root / "fake" / f"dns_{LEASE_DNS}").unlink()
    edge.http("302")
    report = _report(edge.run())
    assert (report["public resolver"], report["lease resolver"]) == expected


def test_every_public_resolver_is_asked_before_saying_no(edge: Edge) -> None:
    assert len(PUBLIC_RESOLVERS) > 1
    (edge.root / "fake" / f"dns_{PUBLIC_RESOLVERS[0]}").unlink()
    edge.answers(PUBLIC_RESOLVERS[-1], CHECK_IP)
    edge.http("204")
    assert _report(edge.run())["public resolver"] == "answers"


def test_a_lease_without_a_resolver_says_so(edge: Edge) -> None:
    edge.lease(dns=None)
    edge.http("204")
    assert _report(edge.run())["lease resolver"] == "none offered"


@pytest.mark.parametrize(
    ("current", "expected"), [(UPLINK_MAC.lower(), "matches SOPS"), (OTHER_MAC, "differs from SOPS")]
)
def test_it_compares_the_uplink_mac_with_sops(edge: Edge, current: str, expected: str) -> None:
    """The portal authorizes the MAC on the air; the `.link` file holds the one in SOPS."""
    edge.mac(current)
    edge.http("204")
    assert _report(edge.run())["uplink MAC"] == expected


def test_an_unreadable_mac_is_not_a_match(edge: Edge) -> None:
    (edge.root / "etc" / "link").unlink()
    edge.http("204")
    assert _report(edge.run())["uplink MAC"] == "unreadable"


@pytest.mark.parametrize("code", ["204", "302", "000"])
def test_it_prints_no_site_data(edge: Edge, code: str) -> None:
    """Its output lands in a terminal and a spec's evidence: no MAC, no site address."""
    edge.mac(OTHER_MAC)
    edge.http(code)
    result = edge.run()
    text = (result.stdout + result.stderr).lower()
    for value in (UPLINK_MAC, OTHER_MAC, LEASE_ADDRESS, LEASE_DNS, CHECK_IP):
        assert value.lower() not in text
    assert not re.search(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", text)


# ------------------------------------------------------------------ the role


def test_the_script_reads_the_files_the_role_writes() -> None:
    text = SCRIPT.read_text()
    assert f"EDGE_LINK_FILE:-{_task_dest('uplink.link.j2')}" in text
    assert f"EDGE_RESOLV_CONF:-{_task_dest('resolv.conf.j2')}" in text


def test_the_role_installs_the_script_and_what_it_runs() -> None:
    install = [t for t in TASKS if (t.get("copy") or {}).get("src") == SCRIPT.name]
    assert [t["copy"]["dest"] for t in install] == ["{{ gateway_status_path }}"]
    assert install[0]["copy"]["mode"] == "0755"
    (packages,) = [t for t in TASKS if t.get("name") == "Install gateway packages"]
    assert {"curl", "bind9-dnsutils"} <= set(packages["apt"]["name"])


# ----------------------------------------------------------- the operator's side


def test_make_edge_status_runs_the_script_over_the_lan() -> None:
    """The tailnet rides on the uplink this reports on, so it would go down with it. The
    LAN address answers from the switch and, through the edge, from the lab Wi-Fi."""
    from toolkit.features.edge_status import STATUS_PATH, status_command

    (edge_name,) = [n for n, node in NETWORKING["nodes"].items() if "gateway" in (node.get("ansible_groups") or [])]
    node = NETWORKING["nodes"][edge_name]
    command = status_command(NETWORKING)
    assert command[0] == "ssh"
    assert "BatchMode=yes" in command
    assert f"HostKeyAlias={node['tailscale_ip']}" in command, "the key the tailnet session pinned"
    assert command[-3:] == [f"{NETWORKING['ssh_users']['homelab']}@{node['lan_ip']}", STATUS_PATH, UPLINK]
    assert STATUS_PATH == DEFAULTS["gateway_status_path"]


@pytest.mark.parametrize("edges", [0, 2])
def test_the_target_refuses_anything_but_one_edge(edges: int) -> None:
    from toolkit.features.edge_status import EdgeNotDeclaredError, status_command

    networking = {**NETWORKING, "nodes": {}}
    for i in range(edges):
        networking["nodes"][f"edge{i}"] = {"lan_ip": "x", "ansible_groups": ["gateway"]}
    with pytest.raises(EdgeNotDeclaredError):
        status_command(networking)


@pytest.mark.parametrize("code", [UP, PORTAL, DEAD, 255])
def test_the_command_exits_with_the_edges_code(code: int) -> None:
    from typer.testing import CliRunner

    from toolkit.cli.infra import app

    with mock.patch("toolkit.features.edge_status.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], code)
        result = CliRunner().invoke(app, ["edge", "status"])
    assert result.exit_code == code
    (args,), _ = run.call_args
    assert args[0] == "ssh"


def test_the_makefile_target_calls_the_command() -> None:
    makefile = (REPO / "Makefile").read_text()
    target = re.search(r"^edge-status:.*\n((?:\t.*\n)+)", makefile, re.M)
    assert target, "no edge-status target"
    assert "infra edge status" in target.group(1)
