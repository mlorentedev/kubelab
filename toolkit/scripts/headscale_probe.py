"""External connectivity probe for the Headscale mesh (ADR-041 / VPN-ACL-002).

After a policy reload, assert the PRESERVED flows still work (ADR-041 C1):
admin→nodes SSH, ArgoCD hub→spoke :6443, rpi4 subnet route 172.16.1.0/24,
intra-K3s (spoke API), and monitoring. The deploy role runs this immediately
after the SIGHUP reload and AUTO-REVERTS the policy on a non-zero exit.

On v0.28 `headscale policy check` is syntax-only, so reachability must be proven
by this EXTERNAL active probe. The FLOWS list is authored as (src, dst, port)
tuples so it migrates 1:1 into the Headscale v0.29 in-engine `tests` block
(VPN-ACL-006). Flows whose source node is powered off (on-demand homelab) are
SKIPPED with a logged note (no silent caps), never failed.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

REPO = Path(__file__).resolve().parents[2]
COMMON_YAML = REPO / "infra/config/values/common.yaml"

_CONNECT_TIMEOUT = 4


@dataclass(frozen=True)
class Flow:
    """One preserved mesh flow: `src` reaches `dst`:`port`. src='controller' runs locally."""

    name: str
    src: str
    dst: str
    port: int
    required: bool = True


def preserved_flows(net: dict[str, Any]) -> list[Flow]:
    """The ADR-041 C1 preserved flows, resolved from the networking SSOT."""
    # dst endpoints are literal addresses; src is a node NAME, resolved to an SSH
    # target by _ssh_target at runtime (so aws1/rpi3 need no IP local here).
    nodes = net["nodes"]
    vps = net["vps"]["tailscale_ip"]
    ace1 = nodes["ace1"]["tailscale_ip"]
    ace1_lan = nodes["ace1"]["lan_ip"]
    return [
        # always-on (required): these must hold for the policy to be accepted
        Flow("admin->vps SSH", "controller", vps, 22),
        Flow("hub->spoke :6443 (prod)", "aws1", vps, 6443),
        Flow("monitoring rpi3->vps :443", "rpi3", vps, 443),
        # homelab on-demand (optional): probed when the source node is up, else skip+log
        Flow("admin->ace1 SSH", "controller", ace1, 22, required=False),
        Flow("hub->spoke :6443 (staging)", "aws1", ace1, 6443, required=False),
        # rpi4 advertises 172.16.1.0/24; only route-accepting remotes (the workstation /
        # VPS) reach the LAN through it — aws1 does NOT accept routes (CLAUDE.md), so the
        # controller is the correct source to assert the route is preserved.
        Flow("rpi4 route 172.16.1.0/24 (controller->ace1 LAN)", "controller", ace1_lan, 22, required=False),
        Flow("intra-K3s spoke API (ace1 self :6443)", "ace1", ace1, 6443, required=False),
    ]


def _ssh_target(net: dict[str, Any], node: str) -> str:
    """user@tailscale_ip for a node, using the SSOT ssh_users (cloud vs homelab)."""
    users = net["ssh_users"]
    if node in ("vps", "aws1", "aws"):
        ip = net["vps"]["tailscale_ip"] if node == "vps" else net["aws"]["tailscale_ip"]
        return f"{users['cloud']}@{ip}"
    return f"{users['homelab']}@{net['nodes'][node]['tailscale_ip']}"


def _tcp_probe_cmd(dst: str, port: int) -> str:
    return f"timeout {_CONNECT_TIMEOUT} bash -c '</dev/tcp/{dst}/{port}'"


def check_flow(flow: Flow, net: dict[str, Any], runner: Callable[[list[str]], int]) -> str:
    """Return 'pass' | 'fail' | 'skip'. `runner` executes a command and returns its exit code."""
    probe = _tcp_probe_cmd(flow.dst, flow.port)
    if flow.src == "controller":
        return "pass" if runner(["bash", "-c", probe]) == 0 else "fail"
    target = _ssh_target(net, flow.src)
    ssh_base = ["ssh", "-o", f"ConnectTimeout={_CONNECT_TIMEOUT}", "-o", "BatchMode=yes", target]
    # if the source node itself is unreachable (homelab powered off), skip optional flows
    if runner(ssh_base + ["true"]) != 0:
        return "skip"
    return "pass" if runner(ssh_base + [probe]) == 0 else "fail"


def _default_runner(cmd: list[str]) -> int:
    return subprocess.run(cmd, capture_output=True, text=True).returncode


def run_probe(net: dict[str, Any] | None = None, runner: Callable[[list[str]], int] = _default_runner) -> int:
    """Probe all preserved flows. Returns 0 if every REQUIRED flow passes, else 1."""
    if net is None:
        net = yaml.safe_load(COMMON_YAML.read_text())["networking"]
    failed = False
    for flow in preserved_flows(net):
        verdict = check_flow(flow, net, runner)
        marker = {"pass": "ok  ", "fail": "FAIL", "skip": "skip"}[verdict]
        note = "" if flow.required else " (optional)"
        sys.stdout.write(f"  [{marker}] {flow.name}{note}\n")
        if verdict == "fail" and flow.required:
            failed = True
        elif verdict == "skip" and flow.required:
            sys.stdout.write(f"        ^ REQUIRED source '{flow.src}' unreachable — failing\n")
            failed = True
        elif verdict == "fail":
            # optional flows depend on homelab power state + route-acceptance nuances;
            # log a broken one for visibility but do NOT trigger an auto-revert on it.
            sys.stdout.write("        ^ optional flow down — logged, not failing the gate\n")
        elif verdict == "skip":
            sys.stdout.write(f"        ^ source '{flow.src}' unreachable — skipped, not failed\n")
    if failed:
        sys.stdout.write("PROBE FAILED: a required preserved flow is down — policy will be reverted\n")
        return 1
    sys.stdout.write("PROBE OK: all required preserved flows hold\n")
    return 0
