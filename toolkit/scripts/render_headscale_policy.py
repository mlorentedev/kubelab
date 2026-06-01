"""Render the Headscale ACL policy (policy.hujson) from the networking SSOT, and
optionally validate it with the real ``headscale policy check`` binary via Docker.

Single source of truth for rendering the policy, shared by three consumers:
  - the deploy-time render (mirrors the ``deploy-vps.yml`` ``set_fact`` host build),
  - the CI syntax gate (``make check-headscale-policy`` → ADR-041 / VPN-ACL-002 AC2),
  - the unit tests (``tests/test_headscale_role.py``).

On v0.28 ``policy check`` is SYNTAX-ONLY (the runtime ``tests`` block is v0.29.0),
so this gate proves the policy parses — reachability is proven by the external
probe (VPN-ACL-002) until the v0.29 upgrade (VPN-ACL-006).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

REPO = Path(__file__).resolve().parents[2]
TEMPLATES = REPO / "infra/ansible/roles/headscale/templates"
COMMON_YAML = REPO / "infra/config/values/common.yaml"


def _networking(common_yaml: Path = COMMON_YAML) -> dict[str, Any]:
    return yaml.safe_load(common_yaml.read_text())["networking"]


def build_hosts(common_yaml: Path = COMMON_YAML) -> dict[str, str]:
    """ACL host aliases (name -> Tailscale IP / CIDR), mirroring deploy-vps.yml set_fact."""
    net = _networking(common_yaml)
    hosts = {name: node["tailscale_ip"] for name, node in net["nodes"].items()}
    hosts["vps"] = net["vps"]["tailscale_ip"]
    hosts["aws1"] = net["aws"]["tailscale_ip"]
    hosts["lan-rpi4"] = net["lan_cidr"]
    return hosts


def render_policy(hosts: dict[str, str] | None = None) -> str:
    """Render policy.hujson.j2. trim_blocks matches Ansible's default render."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("policy.hujson.j2").render(headscale_policy_hosts=hosts or build_hosts())


def headscale_image(common_yaml: Path = COMMON_YAML) -> str:
    """Headscale image:tag from the SSOT — keeps the gate on the deployed version."""
    cfg = yaml.safe_load(common_yaml.read_text())
    return cfg["apps"]["services"]["core"]["headscale"]["image"]


def policy_check(text: str, image: str | None = None) -> int:
    """Run the real ``headscale policy check`` on rendered text via Docker. Returns exit code.

    Pipes the policy through stdin (``--file /dev/stdin``) rather than a bind mount:
    inside a dockerized CI runner (Docker-in-Docker), a ``-v <hostpath>`` would resolve
    against the Docker host's filesystem, not the runner container's, so the file would
    be missing. stdin is DinD-safe.
    """
    image = image or headscale_image()
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", image, "policy", "check", "--file", "/dev/stdin"],
        input=text,
        capture_output=True,
        text=True,
    )
    sys.stdout.write(result.stdout or result.stderr)
    return result.returncode
