"""The compose file the Headscale runbook shows is the one the role renders (OPS-047, #2701).

Section 1.2 of `docs/runbooks/headscale-setup.md` carried a hand-written compose
for months after the VPS moved from the `proxy` network to `kubelab` (ADR-020
Phase 2b) and the role began publishing 8080 on the public IP. Nothing connected
the two, so the runbook told an operator to build a file the role would overwrite
with a different one.

The role's template is the source of truth, so this renders it from the values
`deploy-vps.yml` feeds it and compares the result with the snippet. Two values
stay as `<placeholders>` in the runbook because they change without the file's
shape changing (the image tag, the public IP); everything else is compared as
rendered, so a renamed network or a new published port fails here.

Section 6.1 quotes the split DNS block of `config.yaml.j2` and is held the same way,
so a zone added to `networking.staging_zones` fails here until the runbook shows it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/headscale"
TEMPLATES = ROLE / "templates"
VALUES = REPO / "infra/config/values"
RUNBOOK = REPO / "docs/runbooks/headscale-setup.md"

# What the runbook shows in place of values that move without changing the file's shape.
IMAGE_PLACEHOLDER = "<apps.services.core.headscale.image>"
PUBLIC_IP_PLACEHOLDER = "<networking.vps.public_ip>"


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Ansible's `combine(recursive=True)`: the overriding mapping wins key by key."""
    out = dict(base)
    for key, value in over.items():
        out[key] = _merge(out[key], value) if isinstance(out.get(key), dict) and isinstance(value, dict) else value
    return out


def _prod_config() -> dict[str, Any]:
    """common.yaml with prod.yaml over it, which is what `deploy-vps.yml` calls `config`."""
    common = yaml.safe_load((VALUES / "common.yaml").read_text(encoding="utf-8"))
    prod = yaml.safe_load((VALUES / "prod.yaml").read_text(encoding="utf-8"))
    return _merge(common, prod)


def _rendered() -> dict[str, Any]:
    """`docker-compose.yml.j2` as the VPS play renders it, the two moving values left as placeholders."""
    config = _prod_config()
    headscale = config["apps"]["services"]["core"]["headscale"]
    # The role vars the headscale entry in deploy-vps.yml sets for this template.
    variables = {
        "headscale_image": IMAGE_PLACEHOLDER,
        "vps_public_ip": PUBLIC_IP_PLACEHOLDER,
        "headscale_listen_port": headscale["default_port"],
        "headscale_stun_port": headscale["stun_port"],
        "restart_policy": config["global"]["restart_policy"],
        "docker_network": config["networking"]["vps"]["docker_network"],
        "docker_dns_servers": config["networking"]["public_resolvers"],
    }
    env = ansible_env(str(TEMPLATES), trim_blocks=True)
    return yaml.safe_load(env.get_template("docker-compose.yml.j2").render(**variables))


def _runbook_compose() -> dict[str, Any]:
    """The first yaml block under the runbook's `### 1.2` heading."""
    text = RUNBOOK.read_text(encoding="utf-8")
    section = re.search(r"^### 1\.2 .*?(?=^### )", text, re.S | re.M)
    assert section, "the runbook has no section 1.2"
    block = re.search(r"```yaml\n(.*?)```", section.group(0), re.S)
    assert block, "section 1.2 of the runbook shows no compose file"
    return yaml.safe_load(block.group(1))


def test_the_runbook_shows_the_compose_the_role_renders() -> None:
    assert _runbook_compose() == _rendered()


def _rendered_split_dns() -> dict[str, Any]:
    """`dns.nameservers.split` of `config.yaml.j2` as the VPS play renders it."""
    config = _prod_config()
    headscale = config["apps"]["services"]["core"]["headscale"]
    rpi4 = config["networking"]["nodes"]["rpi4"]["tailscale_ip"]
    variables = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    variables.update(
        {
            "headscale_domain": headscale["domain"],
            "headscale_listen_port": headscale["default_port"],
            "tailscale_cidr": config["networking"]["tailscale_cidr"],
            # The "Build Headscale split DNS from staging zones" task in deploy-vps.yml.
            "headscale_dns_split": {zone: [rpi4] for zone in config["networking"]["staging_zones"]},
        }
    )
    env = ansible_env(str(TEMPLATES), trim_blocks=True)
    return yaml.safe_load(env.get_template("config.yaml.j2").render(**variables))["dns"]["nameservers"]["split"]


def _runbook_split_dns() -> dict[str, Any]:
    """The first yaml block under the runbook's `### 6.1` heading."""
    text = RUNBOOK.read_text(encoding="utf-8")
    section = re.search(r"^### 6\.1 .*?(?=^### )", text, re.S | re.M)
    assert section, "the runbook has no section 6.1"
    block = re.search(r"```yaml\n(.*?)```", section.group(0), re.S)
    assert block, "section 6.1 of the runbook shows no split DNS block"
    return yaml.safe_load(block.group(1))["dns"]["nameservers"]["split"]


def test_the_runbook_shows_the_split_dns_the_role_renders() -> None:
    rendered = _rendered_split_dns()
    assert rendered, "no zone rendered, so this compares nothing"
    assert _runbook_split_dns() == rendered


def test_the_runbook_numbers_its_headings_once() -> None:
    """Two sections both numbered 1.6 left every reference to one of them ambiguous."""
    text = RUNBOOK.read_text(encoding="utf-8")
    numbers = re.findall(r"^### (\d+\.\d+) ", text, re.M)
    assert numbers, "the pattern stopped matching the headings"
    assert len(numbers) == len(set(numbers)), f"repeated heading numbers: {sorted(n for n in set(numbers) if numbers.count(n) > 1)}"
