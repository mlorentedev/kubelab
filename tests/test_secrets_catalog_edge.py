"""The lab edge's secrets are catalogued, prod only (NET-005, ADR-075 D1).

The RPi4 is provisioned with `ENV=prod`, so `envs=("prod",)` is where the audit
looks for them. `SecretSpec` has no optional flag, so the catalog registers the
keys the current uplink `kind` needs and no others: a key no site uses would be
a permanent gap in `make secrets-audit`. The uplink PSK lands with the first
`wifi_psk` site, and `portal_domains` with the login mode (NET-005 task 31).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from toolkit.features.secrets_manager import SECRET_CATALOG, SecretKind

REPO = Path(__file__).resolve().parents[1]
EDGE = "networking.edge"

# What each uplink kind needs from SOPS. An open Wi-Fi is joined by name, a
# PSK one by name and key, and an Ethernet port by neither.
UPLINK_KEYS_BY_KIND = {
    "wifi_open": ("ssid",),
    "wifi_psk": ("ssid", "psk"),
    "ethernet": (),
}
# Needed at every site: the lab's own Wi-Fi, and the MAC the portal authorized.
ALWAYS = (f"{EDGE}.lab_wifi.ssid", f"{EDGE}.lab_wifi.psk", f"{EDGE}.uplink.mac")

_BY_KEY = {spec.key_path: spec for spec in SECRET_CATALOG}


def _kind() -> str:
    common = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())
    return common["networking"]["edge"]["uplink"]["kind"]


def test_the_kinds_here_are_the_kinds_the_ssot_allows() -> None:
    assert _kind() in UPLINK_KEYS_BY_KIND


@pytest.mark.parametrize("key", ALWAYS)
def test_the_keys_every_site_needs_are_catalogued_for_prod(key: str) -> None:
    spec = _BY_KEY.get(key)
    assert spec is not None, f"{key} is not in SECRET_CATALOG"
    assert spec.envs == ("prod",)


def test_the_current_uplink_kind_has_every_key_it_needs() -> None:
    for leaf in UPLINK_KEYS_BY_KIND[_kind()]:
        key = f"{EDGE}.uplink.{leaf}"
        assert key in _BY_KEY, f"uplink kind {_kind()!r} needs {key} in SECRET_CATALOG"
        assert _BY_KEY[key].envs == ("prod",)


def test_no_edge_key_is_registered_for_another_env() -> None:
    for spec in SECRET_CATALOG:
        if spec.key_path.startswith(f"{EDGE}."):
            assert spec.envs == ("prod",), spec.key_path


def test_no_edge_key_is_one_the_toolkit_mints_on_its_own() -> None:
    """`secrets init` and `credentials generate` fill minted kinds unasked.

    A lab PSK minted that way reaches the AP at the next provision and locks out
    rpi3, whose only network is that Wi-Fi. Every edge key is EXTERNAL; the PSK
    changes only through the rotation target, which re-keys rpi3 first (AC10).
    """
    edge_specs = [spec for spec in SECRET_CATALOG if spec.key_path.startswith(f"{EDGE}.")]
    assert edge_specs
    for spec in edge_specs:
        assert spec.kind == SecretKind.EXTERNAL, spec.key_path
