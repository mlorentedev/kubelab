"""The VPS firewall's inputs are rendered from common.yaml, and refuse to lock SSH out (SEC-006).

An attached Hetzner firewall drops everything it does not list, and Headscale
runs on the same host, so a rendered allow-list without 22/tcp is an operator
locked out with the VPN gone too. The renderer refuses before Terraform sees it.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from toolkit.features import vps_firewall_tfvars as fw

COMMON = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "infra" / "config" / "values" / "common.yaml").read_text(encoding="utf-8")
)


def _config(**firewall_overrides: object) -> dict:
    config = copy.deepcopy(COMMON)
    config["networking"]["firewall"].update(firewall_overrides)
    return config


def test_the_ssot_renders_every_rule_and_the_server_identity() -> None:
    out = fw.render(COMMON)
    rules = COMMON["networking"]["firewall"]["vps_inbound"]
    assert out.count("{ port = ") == len(rules)
    assert f'server_name        = "{COMMON["networking"]["vps"]["hetzner_server_name"]}"' in out
    assert f'expected_public_ip = "{COMMON["networking"]["vps"]["public_ip"]}"' in out


def test_an_empty_allow_list_is_refused() -> None:
    with pytest.raises(fw.RenderError, match="drops ALL"):
        fw.render(_config(vps_inbound=[]))


def test_an_allow_list_without_ssh_is_refused() -> None:
    with pytest.raises(fw.RenderError, match="22/tcp is absent"):
        fw.render(_config(vps_inbound=[{"port": 443, "proto": "tcp", "description": "https"}]))


def test_a_quoted_ssh_port_still_counts() -> None:
    out = fw.render(_config(vps_inbound=[{"port": "22", "proto": "TCP", "description": "ssh"}]))
    assert "port = 22," in out


@pytest.mark.parametrize("key", ["hetzner_server_name", "public_ip"])
def test_a_missing_server_identity_is_named(key: str) -> None:
    config = copy.deepcopy(COMMON)
    config["networking"]["vps"].pop(key)
    with pytest.raises(fw.RenderError, match=f"networking.vps.{key}"):
        fw.render(config)


def test_a_quote_in_a_description_cannot_break_the_hcl() -> None:
    out = fw.render(_config(vps_inbound=[{"port": 22, "proto": "tcp", "description": 'say "hi"'}]))
    assert 'description = "say \\"hi\\""' in out
