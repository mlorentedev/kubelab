"""Every public apex the config names is a zone in the DNS root's map (#2460).

What this can and cannot see: it runs offline, so it cannot ask Cloudflare
which zones the account holds. A zone nothing in the repository names (the way
imagesensortool.com sat outside IaC) is invisible to it. It asserts the half
that is checkable: every apex the config does name, through a service's
`zone`, a staging split-DNS zone or a `domain`/`*_domain` value, is declared in
`zones.json`, so a new domain cannot ship pointing at a zone Terraform does not
manage. The apex is the last two labels; no domain in use sits under a
multi-label public suffix.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DNS = REPO_ROOT / "infra/terraform/dns"
VALUES = REPO_ROOT / "infra/config/values"

#: Reserved TLDs that never reach public DNS (RFC 6761 `.test`, mDNS `.local`,
#: ICANN's private-use `.internal`). dev.yaml lives entirely under `.test`.
NON_PUBLIC_TLDS = frozenset({"test", "local", "internal"})

ZONES: dict[str, Any] = json.loads((DNS / "zones.json").read_text(encoding="utf-8"))


ENVS = ("common", "staging", "prod")


def _configs() -> list[dict[str, Any]]:
    return [yaml.safe_load((VALUES / f"{env}.yaml").read_text(encoding="utf-8")) or {} for env in ENVS]


def _is_reference(value: str, configs: list[dict[str, Any]]) -> bool:
    """`argocd.domain` names another key in the config, not a host."""
    for config in configs:
        node: Any = config
        for part in value.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is not None:
            return True
    return False


def _domain_values(node: Any, found: list[str] | None = None) -> list[str]:
    found = [] if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            # `domain` and `*_domain`, not any suffix: `regdomain` is a radio's
            # regulatory domain (networking.edge.uplink), not a DNS name.
            if (key == "domain" or key.endswith("_domain")) and isinstance(value, str) and value:
                found.append(value)
            else:
                _domain_values(value, found)
    elif isinstance(node, list):
        for item in node:
            _domain_values(item, found)
    return found


def _apex(host: str) -> str:
    return ".".join(host.rstrip(".").split(".")[-2:])


def test_every_service_zone_is_in_the_map() -> None:
    keys = {zone["key"] for zone in ZONES.values()}
    services = json.loads((DNS / "services.json").read_text(encoding="utf-8"))
    unknown = sorted({s["zone"] for s in services} - keys)
    assert not unknown, f"services.json names zones absent from zones.json: {unknown}"


def _public_hosts(configs: list[dict[str, Any]]) -> set[str]:
    hosts = {h for config in configs for h in _domain_values(config)}
    hosts.update(z for config in configs for z in config.get("networking", {}).get("staging_zones", []))
    return {h for h in hosts if _apex(h).split(".")[-1] not in NON_PUBLIC_TLDS and not _is_reference(h, configs)}


def test_every_public_apex_in_the_config_is_in_the_map() -> None:
    missing = sorted(h for h in _public_hosts(_configs()) if _apex(h) not in ZONES)
    assert not missing, (
        "these hosts sit in a zone infra/terraform/dns/zones.json does not declare, so no "
        f"Terraform resource serves them: {missing}. Add the zone to zones.json "
        "(docs/runbooks/dns-terraform.md, 'Add a zone')."
    )


def test_the_guard_sees_the_zones_it_must() -> None:
    """A walk that finds nothing passes vacuously; pin what it must find."""
    assert {"kubelab.live", "mlorente.dev"} <= {_apex(h) for h in _public_hosts(_configs())}


def _serves(apex: str, zone: dict[str, Any]) -> bool:
    services = json.loads((DNS / "services.json").read_text(encoding="utf-8"))
    return bool(zone["records"]) or any(s["zone"] == zone["key"] for s in services)


def test_a_zone_that_serves_nothing_does_not_preload_hsts() -> None:
    """HSTS with `preload` reaches browser lists that keep it for a year; a zone
    with no records has made no decision about TLS to pin."""
    pinned = sorted(apex for apex, z in ZONES.items() if not _serves(apex, z) and z.get("hsts", True))
    assert not pinned, f'zones that serve nothing but send HSTS with preload (set "hsts": false): {pinned}'
