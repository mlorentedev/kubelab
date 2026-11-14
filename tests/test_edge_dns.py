"""The staging split-DNS zones are derived from the product registry (EDGE-001, #3495).

A zone used to be one hand-written line in ``networking.staging_zones``. Now the
platform declares only its own zones there; each registered product with a staging
lane contributes its contract snapshot's ``hostnames.staging``, on one condition:
its apex is a Cloudflare zone the platform declares in
``infra/terraform/dns/zones.json`` (owner ruling 2026-11-13). A contract chooses a
name inside a granted zone; it never grants one. Names here are fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features import edge_dns
from toolkit.features.edge_dns import EdgeDnsError

DECLARED = ["staging.kubelab.live", "staging.mlorente.dev"]
APEXES = ["kubelab.live", "mlorente.dev", "imagesensortool.com", "example-product.test"]


def _registry(tmp_path: Path, products: dict[str, Any], name: str = "products.yaml") -> Path:
    # A new file per version: load_registry caches by path.
    path = tmp_path / name
    path.write_text(yaml.safe_dump({"products": products}, sort_keys=False), encoding="utf-8")
    return path


def _snapshot(snapshots: Path, app: str, staging: str, prod: str | None = None) -> None:
    snapshots.mkdir(parents=True, exist_ok=True)
    hostnames = {"staging": staging} | ({"prod": prod} if prod else {})
    (snapshots / f"{app}.yaml").write_text(yaml.safe_dump({"hostnames": hostnames}), encoding="utf-8")


def _remote(app: str, *, prod: bool = False) -> dict[str, Any]:
    events = {"staging": f"{app}-image-published"} | ({"prod": f"{app}-release-published"} if prod else {})
    return {"repository": f"mlorentedev/{app}", "forge": "github", "receiver": "generic", "events": events}


@pytest.fixture
def world(tmp_path: Path) -> tuple[Path, Path]:
    """Today's shape: api in-tree, web (staging + prod), imagesensortool (staging only)."""
    snapshots = tmp_path / "contracts"
    _snapshot(snapshots, "web", "staging.mlorente.dev", "mlorente.dev")
    _snapshot(snapshots, "imagesensortool", "staging.imagesensortool.com")
    registry = _registry(
        tmp_path,
        {"api": {"forge": "in-tree"}, "web": _remote("web", prod=True), "imagesensortool": _remote("imagesensortool")},
    )
    return registry, snapshots


def _derive(world: tuple[Path, Path]) -> list[str]:
    registry, snapshots = world
    return edge_dns.derive_staging_zones(DECLARED, APEXES, registry=registry, snapshot_dir=snapshots)


def test_todays_registry_yields_todays_zones_in_todays_order(world: tuple[Path, Path]) -> None:
    assert _derive(world) == ["staging.kubelab.live", "staging.mlorente.dev", "staging.imagesensortool.com"]


def test_a_new_product_on_a_declared_apex_adds_its_zone_and_removing_it_drops_it(world: tuple[Path, Path]) -> None:
    registry, snapshots = world
    products = yaml.safe_load(registry.read_text(encoding="utf-8"))["products"]
    _snapshot(snapshots, "shop", "staging.example-product.test")
    _registry(registry.parent, products | {"shop": _remote("shop")})

    assert _derive(world)[-1] == "staging.example-product.test"

    removed = _registry(registry.parent, products, "removed.yaml")
    assert "staging.example-product.test" not in _derive((removed, snapshots))


def test_a_host_under_the_wildcard_zone_contributes_no_zone(world: tuple[Path, Path]) -> None:
    registry, snapshots = world
    products = yaml.safe_load(registry.read_text(encoding="utf-8"))["products"]
    _snapshot(snapshots, "shop", "shop.staging.kubelab.live")
    _registry(registry.parent, products | {"shop": _remote("shop")})

    assert _derive(world) == ["staging.kubelab.live", "staging.mlorente.dev", "staging.imagesensortool.com"]


def test_a_registered_product_without_a_snapshot_or_a_staging_lane_contributes_nothing(
    world: tuple[Path, Path],
) -> None:
    registry, snapshots = world
    products = yaml.safe_load(registry.read_text(encoding="utf-8"))["products"]
    _snapshot(snapshots, "idle", "staging.example-product.test")
    idle = _remote("idle") | {"events": {}}
    _registry(registry.parent, products | {"idle": idle, "fresh": _remote("fresh")})

    assert "staging.example-product.test" not in _derive(world)


def test_a_snapshot_no_registry_entry_claims_contributes_nothing(world: tuple[Path, Path]) -> None:
    _snapshot(world[1], "stray", "staging.example-product.test")

    assert "staging.example-product.test" not in _derive(world)


def test_a_host_whose_apex_is_not_a_declared_zone_is_refused_naming_zones_json(world: tuple[Path, Path]) -> None:
    registry, snapshots = world
    products = yaml.safe_load(registry.read_text(encoding="utf-8"))["products"]
    _snapshot(snapshots, "shop", "staging.ungranted.test")
    _registry(registry.parent, products | {"shop": _remote("shop")})

    with pytest.raises(EdgeDnsError) as excinfo:
        _derive(world)

    message = str(excinfo.value)
    assert [line.split(":", 1)[0] for line in message.splitlines()] == ["ERROR", "WHY", "FIX"]
    assert "staging.ungranted.test" in message and "zones.json" in message


@pytest.mark.parametrize("host", ["example-product.test", "shop.example-product.test", "staging.test"])
def test_a_granted_name_that_is_not_staging_dot_a_domain_never_becomes_a_zone(
    world: tuple[Path, Path], host: str
) -> None:
    """A bare apex as a split-DNS zone would send every VPN client's prod lookups for it to the edge."""
    registry, snapshots = world
    products = yaml.safe_load(registry.read_text(encoding="utf-8"))["products"]
    _snapshot(snapshots, "shop", host)
    _registry(registry.parent, products | {"shop": _remote("shop")})

    with pytest.raises(EdgeDnsError) as excinfo:
        edge_dns.derive_staging_zones(DECLARED, [*APEXES, "test"], registry=registry, snapshot_dir=snapshots)

    assert host in str(excinfo.value) and "staging." in str(excinfo.value)


@pytest.mark.parametrize(
    ("host", "apex"),
    [
        ("staging.imagesensortool.com", "imagesensortool.com"),
        ("imagesensortool.com", "imagesensortool.com"),
        ("shop.staging.kubelab.live", "kubelab.live"),
        ("staging.ungranted.test", None),
        ("notimagesensortool.com", None),
    ],
)
def test_the_apex_is_the_longest_declared_zone_suffix_on_a_label_boundary(host: str, apex: str | None) -> None:
    assert edge_dns.apex_of(host, APEXES) == apex


def test_the_longest_suffix_wins_when_zones_nest() -> None:
    assert edge_dns.apex_of("staging.shop.example.test", ["example.test", "shop.example.test"]) == "shop.example.test"


def test_the_committed_manifest_is_what_the_derivation_produces() -> None:
    """`make validate-sync` asserts the same; this keeps `make test` honest without the CLI."""
    committed = json.loads(edge_dns.MANIFEST.read_text(encoding="utf-8"))
    assert committed == edge_dns.build_manifest()
    assert "staging.imagesensortool.com" in committed["staging_zones"]


def test_the_platform_no_longer_hand_lists_a_product_zone() -> None:
    """The declared list is the platform's own; a product's zone there is the hand step EDGE-001 removed."""
    declared = edge_dns.declared_staging_zones()
    assert "staging.imagesensortool.com" not in declared
    assert declared[0] == "staging.kubelab.live"


def test_the_accessor_reads_the_committed_manifest() -> None:
    assert edge_dns.staging_zones() == json.loads(edge_dns.MANIFEST.read_text(encoding="utf-8"))["staging_zones"]


# --- ACME probe zones (#3482) -------------------------------------------------


def test_the_acme_probe_covers_each_registered_hostnames_apex_per_env(world: tuple[Path, Path]) -> None:
    registry, snapshots = world
    _snapshot(snapshots / "prod", "web", "staging.mlorente.dev", "mlorente.dev")
    mains = {"staging": ["kubelab.live"], "prod": ["kubelab.live"]}

    zones = edge_dns.acme_probe_zones(mains, APEXES, registry=registry, snapshot_dir=snapshots)

    # The acme_domains mains first, each once, then the product apexes in registry order.
    assert zones == ["kubelab.live", "mlorente.dev", "imagesensortool.com"]


def test_a_new_product_adds_its_probe_target_and_removing_it_drops_it(world: tuple[Path, Path]) -> None:
    registry, snapshots = world
    products = yaml.safe_load(registry.read_text(encoding="utf-8"))["products"]
    _snapshot(snapshots, "shop", "staging.example-product.test")
    added = _registry(registry.parent, products | {"shop": _remote("shop")}, "added.yaml")
    mains = {"staging": ["kubelab.live"], "prod": ["kubelab.live"]}

    assert "example-product.test" in edge_dns.acme_probe_zones(mains, APEXES, registry=added, snapshot_dir=snapshots)
    assert "example-product.test" not in edge_dns.acme_probe_zones(
        mains, APEXES, registry=registry, snapshot_dir=snapshots
    )


def test_every_committed_registered_hostname_has_its_apex_probed() -> None:
    """The guard #3482 asks for, on the committed registry: no registered hostname escapes the probe."""
    zones = set(edge_dns.acme_probe_zones({"staging": [], "prod": []}, edge_dns.granted_apexes()))
    for env in ("staging", "prod"):
        for host in edge_dns.registered_hostnames(env):
            assert edge_dns.apex_of(host, edge_dns.granted_apexes()) in zones, host
    assert "imagesensortool.com" in zones
