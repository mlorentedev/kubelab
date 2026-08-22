"""A monitor for a node whose address rotates must not be pinned to an address.

Both Argo CD hubs are watched by Uptime Kuma, and they must be watched
DIFFERENTLY, for a reason that is a property of the infrastructure rather than a
style preference:

- `aws1` is a Spot instance whose Tailscale IP is recorded in `common.yaml` and
  changes only on a deliberate replacement. Pinning the IP is fine.
- `gcp1` sits in a regional managed instance group. A MIG RECREATES on every
  preemption, so the node re-registers with Headscale and its address rotates as
  a matter of routine. `networking.gcp` therefore carries no `tailscale_ip` at
  all, on purpose.

A `gcp1` monitor pinned to an IP would go red during a recovery that SUCCEEDED --
reporting the hub down while it is up. A monitor that cries wolf on the
self-healing path is worse than no monitor: it trains the reader to ignore the
one alert that matters.
"""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
MONITORS = REPO / "infra/config/uptime-kuma/monitors.json"
COMMON = REPO / "infra/config/values/common.yaml"


def _monitors() -> list[dict]:
    data = json.loads(MONITORS.read_text())
    return data if isinstance(data, list) else data["monitors"]


def _networking() -> dict:
    return yaml.safe_load(COMMON.read_text())["networking"]


def _by_key(key: str) -> dict:
    found = [m for m in _monitors() if m.get("key") == key]
    assert found, f"no monitor with key {key!r}"
    return found[0]


class TestTheGcpHubIsWatched:
    def test_a_monitor_exists(self) -> None:
        """The hub must be born monitored. Adding it after bring-up leaves the
        node unwatched through exactly the window where it is least proven."""
        _by_key("infra-vpn-gcp1-tailscale")

    def test_it_is_addressed_by_magicdns_not_by_ip(self) -> None:
        """THE PROPERTY THIS FILE EXISTS FOR."""
        host = _by_key("infra-vpn-gcp1-tailscale")["hostname"]
        with pytest.raises(ValueError):
            ipaddress.ip_address(host)
        assert host == _networking()["gcp"]["tailscale_dns"]

    def test_the_ssot_still_declines_to_record_an_ip(self) -> None:
        """If `networking.gcp.tailscale_ip` ever appears, the reasoning above has
        changed and this guard should be reconsidered rather than silently kept."""
        assert "tailscale_ip" not in _networking()["gcp"], (
            "networking.gcp now records a tailscale_ip. A MIG rotates it on every "
            "preemption, so either the MIG is gone or this is a cached lie."
        )

    def test_it_notifies_the_same_channel_as_the_other_hub(self) -> None:
        gcp = _by_key("infra-vpn-gcp1-tailscale")
        aws = _by_key("infra-vpn-aws1-tailscale")
        assert gcp["notificationIDList"] == aws["notificationIDList"]


class TestTheAwsHubStaysWatchedUntilItIsGone:
    def test_its_monitor_is_still_present_and_active(self) -> None:
        """Retiring it early leaves prod's hub unwatched while it is still the
        one reconciling prod. It goes with AC6, not with the GCP bring-up."""
        aws = _by_key("infra-vpn-aws1-tailscale")
        assert aws["active"] is True

    def test_its_description_matches_the_machine_it_watches(self) -> None:
        """It said `t4g.micro` long after RELIAB-009 moved the hub to t4g.small,
        and quoted a MagicDNS IP that disagreed with its own hostname field. A
        description nothing compares is a description that drifts."""
        aws = _by_key("infra-vpn-aws1-tailscale")
        assert _networking()["aws"]["instance_type"] in aws["description"]

    def test_its_hostname_matches_the_ssot(self) -> None:
        assert _by_key("infra-vpn-aws1-tailscale")["hostname"] == _networking()["aws"]["tailscale_ip"]
