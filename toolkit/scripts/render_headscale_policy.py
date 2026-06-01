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

import argparse
import subprocess
import sys
import tempfile
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
    """Run the real ``headscale policy check`` on rendered text via Docker. Returns exit code."""
    image = image or headscale_image()
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "policy.hujson"
        f.write_text(text)
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{f}:/policy.hujson:ro",
                image,
                "policy",
                "check",
                "--file",
                "/policy.hujson",
            ],
            capture_output=True,
            text=True,
        )
        sys.stdout.write(result.stdout or result.stderr)
        return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Render / validate the Headscale ACL policy.")
    parser.add_argument("--check", action="store_true", help="validate via `headscale policy check` (Docker)")
    args = parser.parse_args()

    rendered = render_policy()
    if not args.check:
        sys.stdout.write(rendered)
        return 0
    return policy_check(rendered)


if __name__ == "__main__":
    raise SystemExit(main())
