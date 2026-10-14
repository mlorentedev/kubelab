"""Render the VPS cloud firewall's inputs from common.yaml (SEC-006).

Plaintext policy, which ports prod accepts from the internet, so it belongs in a
reviewable diff. The Hetzner token is a secret and travels separately, as
`TF_VAR_hetzner_api_token` in the child process's environment.
"""

from __future__ import annotations

from typing import Any


class RenderError(ValueError):
    """The SSOT cannot be rendered; the message names the key to fix."""


def _is_ssh(rule: dict[str, Any]) -> bool:
    # int() rather than ==22: YAML quoting the port ("22") would make an identity
    # check false and refuse a correct allow-list. It fails safe, but on a message
    # about SSH being absent when it is present -- the operator then goes looking
    # for the wrong thing.
    try:
        return int(rule.get("port", 0)) == 22 and str(rule.get("proto", "")).lower() == "tcp"
    except (TypeError, ValueError):
        return False


def render(config: dict[str, Any]) -> str:
    networking = config.get("networking") or {}
    rules = (networking.get("firewall") or {}).get("vps_inbound") or []

    if not rules:
        raise RenderError(
            "networking.firewall.vps_inbound is empty or absent in common.yaml. "
            "Refusing to render: an attached firewall with no rules drops ALL "
            "inbound traffic, SSH included."
        )
    # Fail here rather than let Terraform's validation catch it, so the message
    # names the SSOT the operator has to edit rather than the generated file.
    if not any(_is_ssh(r) for r in rules):
        raise RenderError(
            "22/tcp is absent from networking.firewall.vps_inbound. Applying "
            "this would lock every operator out of the VPS, and Headscale runs "
            "on the same host, so the VPN is not a way back in."
        )

    # The Hetzner account's name for the server, NOT networking.vps.hostname --
    # that is the OS hostname and the two differ. Terraform has no default for
    # either of these on purpose: the original lookup used `hostname` as a
    # plausible-looking fallback and resolved to nothing, so a missing value must
    # stop here, naming the SSOT key, rather than reaching Terraform as a guess.
    vps = networking.get("vps") or {}
    for key in ("hetzner_server_name", "public_ip"):
        if not vps.get(key):
            raise RenderError(
                f"networking.vps.{key} is empty or absent in common.yaml. The firewall "
                "module needs it to identify the running server, and to refuse attaching "
                "to the wrong one. Refusing to render."
            )

    lines = [
        "# SSOT: networking.{firewall.vps_inbound,vps} in infra/config/values/common.yaml",
        f'server_name        = "{vps["hetzner_server_name"]}"',
        f'expected_public_ip = "{vps["public_ip"]}"',
        "inbound_rules = [",
    ]
    for r in rules:
        desc = str(r.get("description", "")).replace('"', '\\"')
        lines.append(f'  {{ port = {int(r["port"])}, proto = "{r["proto"]}", description = "{desc}" }},')
    lines.append("]")
    return "\n".join(lines) + "\n"
