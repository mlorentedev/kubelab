"""The DNS root's node -> tailnet address map must match the SSOT.

`infra/terraform/dns/main.tf` keeps `node_tailscale_ips` as a literal map,
because a Terraform root cannot read `common.yaml`. A service record with a
`target` in `services.json` publishes that address, so a stale entry points a
public name at a host that no longer holds it (aws1 moved .4 -> .7 on
re-enrollment). This holds each entry to `networking.nodes.<name>.tailscale_ip`,
or `networking.vps.tailscale_ip` for `vps`, and every `target` to a key of the map.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MAIN_TF = REPO / "infra/terraform/dns/main.tf"
SERVICES = REPO / "infra/terraform/dns/services.json"
COMMON = REPO / "infra/config/values/common.yaml"


def _tf_map() -> dict[str, str]:
    block = re.search(r"node_tailscale_ips\s*=\s*\{(.*?)\}", MAIN_TF.read_text(encoding="utf-8"), re.S)
    assert block, "node_tailscale_ips not found in the DNS root; this test reads the wrong source"
    return dict(re.findall(r'^\s*(\w+)\s*=\s*"([^"]+)"', block.group(1), re.M))


def _ssot_ip(name: str) -> str | None:
    net = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["networking"]
    if name == "vps":
        return net["vps"].get("tailscale_ip")
    return (net["nodes"].get(name) or {}).get("tailscale_ip")


def test_every_map_entry_matches_common_yaml() -> None:
    mapping = _tf_map()
    assert mapping, "the map parsed empty"
    drift = {k: (v, _ssot_ip(k)) for k, v in mapping.items() if v != _ssot_ip(k)}
    assert not drift, f"node_tailscale_ips disagrees with common.yaml (tf, ssot): {drift}"


def test_every_service_target_is_in_the_map() -> None:
    mapping = _tf_map()
    targets = {s["target"] for s in json.loads(SERVICES.read_text(encoding="utf-8")) if "target" in s}
    assert targets <= mapping.keys(), f"targets with no address in the DNS root: {sorted(targets - mapping.keys())}"


def test_gitea_is_published_on_the_tailnet_only() -> None:
    """#3347: the forge's public name must not resolve to the VPS public IP."""
    gitea = next(s for s in json.loads(SERVICES.read_text(encoding="utf-8")) if s["name"] == "gitea")
    assert gitea.get("target") == "vps"
