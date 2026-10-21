"""A product's prod hostname has a public DNS record (#2571).

A contract declares `hostnames.prod`, and the generic receiver renders it into
`apps.platform.<app>`, but nothing derives a Cloudflare record from it: public
records are hand-written in `infra/terraform/dns/zones.json` (a zone's own
records) and `services.json` (prod services). So the two may disagree, and a
new product would deploy to a name nobody can resolve.

This holds every committed snapshot's prod hostname to the record set the DNS
root declares, computed the way `main.tf` keys `local.records`: zone records by
`name`, or the apex when `name` is the apex, plus every `services.json` entry
whose `environments` include prod. Staging hostnames are left out on purpose:
staging DNS is VPN-only split DNS (CoreDNS), not Cloudflare.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import yaml

from toolkit.features.product_render import SNAPSHOT_DIR

DNS = pathlib.Path(__file__).resolve().parents[1] / "infra/terraform/dns"


def _public_records(zones: dict[str, Any], services: list[dict[str, Any]]) -> set[str]:
    """The FQDNs `main.tf` puts in `local.records`."""
    apex_of = {zone["key"]: apex for apex, zone in zones.items()}
    names = {(apex, r["name"]) for apex, zone in zones.items() for r in zone["records"]}
    names |= {(apex_of[s["zone"]], s["name"]) for s in services if "prod" in s["environments"]}
    return {apex if name == apex else f"{name}.{apex}" for apex, name in names}


def _unresolvable(snapshot_dir: pathlib.Path, records: set[str]) -> list[str]:
    """One ERROR / WHY / FIX message per snapshot whose prod hostname has no record."""
    messages = []
    for snapshot in sorted(snapshot_dir.glob("*.yaml")):
        host = (yaml.safe_load(snapshot.read_text()).get("hostnames") or {}).get("prod")
        if host and host not in records:
            messages.append(
                f"ERROR: {snapshot.stem}'s contract names prod hostname {host}, which has no public DNS record\n"
                "WHY: the receiver deploys to the contract's hostname, but Cloudflare records are hand-written "
                "in infra/terraform/dns, so the product would be served at a name nobody can resolve\n"
                f"FIX: add {host} to infra/terraform/dns/zones.json (a zone's own record) or services.json "
                "(a prod service), then `make tf-dns-plan` and `make tf-dns-apply`"
            )
    return messages


def _committed() -> set[str]:
    return _public_records(
        json.loads((DNS / "zones.json").read_text()),
        json.loads((DNS / "services.json").read_text()),
    )


def test_every_committed_prod_hostname_has_a_public_record() -> None:
    hosts = [(yaml.safe_load(p.read_text()).get("hostnames") or {}).get("prod") for p in SNAPSHOT_DIR.glob("*.yaml")]
    assert [host for host in hosts if host], (
        f"no snapshot under {SNAPSHOT_DIR} names a prod hostname: nothing was checked"
    )
    assert _unresolvable(SNAPSHOT_DIR, _committed()) == []


def test_a_prod_hostname_with_no_record_is_refused_naming_zones_json(tmp_path: pathlib.Path) -> None:
    contract = yaml.safe_load((SNAPSHOT_DIR / "web.yaml").read_text())
    contract["hostnames"]["prod"] = "shop.mlorente.dev"
    (tmp_path / "shop.yaml").write_text(yaml.safe_dump(contract))

    [message] = _unresolvable(tmp_path, _committed())

    assert [line.split(":", 1)[0] for line in message.splitlines()] == ["ERROR", "WHY", "FIX"]
    assert "shop.mlorente.dev" in message and "zones.json" in message


def test_a_staging_hostname_needs_no_public_record(tmp_path: pathlib.Path) -> None:
    contract = yaml.safe_load((SNAPSHOT_DIR / "web.yaml").read_text())
    contract["hostnames"]["staging"] = "shop.staging.mlorente.dev"
    (tmp_path / "web.yaml").write_text(yaml.safe_dump(contract))

    assert _unresolvable(tmp_path, _committed()) == []


def test_main_tf_still_keys_records_the_way_this_test_does() -> None:
    """`_public_records` re-implements two expressions of `main.tf`; if either changes, so must it."""
    main_tf = (DNS / "main.tf").read_text()

    assert '(r.name == r.apex ? r.apex : "${r.name}.${r.apex}") => r' in main_tf
    assert 'if contains(svc.environments, "prod")' in main_tf


def test_records_are_keyed_the_way_main_tf_keys_them() -> None:
    zones = {"example.dev": {"key": "example", "records": [{"name": "example.dev"}, {"name": "www"}]}}
    services = [
        {"name": "api", "zone": "example", "environments": ["prod"]},
        {"name": "lab", "zone": "example", "environments": ["staging"]},
    ]

    assert _public_records(zones, services) == {"example.dev", "www.example.dev", "api.example.dev"}
