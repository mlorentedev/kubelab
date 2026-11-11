"""Every registered product has a tile in the platform manifest, at its contract's hostname (#2574).

`build_service_tables` writes the per-environment service rows of
`platform.json` by hand, one `_svc(...)` per service, so a product admitted to
`infra/config/products.yaml` gets no tile, and the web tile spells its own
hostnames. The rows stay hand-written: a tile's label, category and node are
not in the registry or the contract, so deriving them would mean inventing
fields there. These tests make the two sides fail when they part: a product the
registry names must have a tile in each environment it declares a lane for, and for
a product with a contract snapshot, the tile must link to the snapshot's hostname for
that env. A product with no `events.prod` (IDP-053 AC5) has no prod lane, so it has no
prod tile and its snapshot names no prod hostname.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml

from toolkit.features import platform_manifest
from toolkit.features.product_guards import ENVIRONMENTS, apps_declaring, declared_envs
from toolkit.features.product_registry import load_registry, platform_apps
from toolkit.features.product_render import SNAPSHOT_DIR

FIXTURE_REGISTRY = pathlib.Path(__file__).parent / "fixtures" / "product" / "registry.yaml"


def _tables() -> dict[str, list[dict[str, Any]]]:
    config = yaml.safe_load(platform_manifest.COMMON_YAML_PATH.read_text(encoding="utf-8"))
    staging, prod, _shared = platform_manifest.build_service_tables(config)
    return {"staging": staging, "prod": prod}


def _tile(rows: list[dict[str, Any]], app: str) -> dict[str, Any] | None:
    return next((row for row in rows if row["name"].lower() == app), None)


def _without_a_tile(env: str, rows: list[dict[str, Any]], registry: pathlib.Path | None = None) -> list[str]:
    """The products that declare a lane in ``env`` and have no tile there."""
    return [app for app in apps_declaring(env, registry) if _tile(rows, app) is None]


def _lanes(snapshot_dir: pathlib.Path, registry: pathlib.Path | None = None) -> list[tuple[pathlib.Path, str]]:
    """``(snapshot, env)`` for every env the snapshot's product declares a lane for."""
    products = load_registry(registry).products
    return [
        (snapshot, env)
        for snapshot in sorted(snapshot_dir.glob("*.yaml"))
        for env in (declared_envs(products[snapshot.stem]) if snapshot.stem in products else ENVIRONMENTS)
    ]


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_every_registered_product_has_a_tile(env: str) -> None:
    assert platform_apps(), "the product registry names no product: nothing was checked"
    assert apps_declaring(env), f"no registered product declares a {env} lane: nothing was checked"

    missing = _without_a_tile(env, _tables()[env])

    assert missing == [], (
        f"ERROR: {env} has no platform tile for {missing}\n"
        "WHY: the platform manifest lists its services by hand, so a product admitted to "
        "infra/config/products.yaml is missing from platform.json\n"
        "FIX: add an _svc(...) row for it in build_service_tables (toolkit/features/platform_manifest.py), "
        "then `make sync-platform-json`"
    )


def test_a_product_with_no_prod_lane_needs_no_prod_tile() -> None:
    """Fixture registry: `third` declares only `events.staging`, so only staging asks for its tile."""
    rows = [{"name": "API"}, {"name": "Web"}]

    assert _without_a_tile("prod", rows, FIXTURE_REGISTRY) == []
    assert _without_a_tile("staging", rows, FIXTURE_REGISTRY) == ["third"]


def test_a_lane_is_checked_for_exactly_the_envs_the_product_declares(tmp_path: pathlib.Path) -> None:
    for name in ("web", "third"):
        (tmp_path / f"{name}.yaml").write_text("schema_version: 1\n", encoding="utf-8")

    assert [(path.stem, env) for path, env in _lanes(tmp_path, FIXTURE_REGISTRY)] == [
        ("third", "staging"),
        ("web", "staging"),
        ("web", "prod"),
    ]


def test_there_is_a_contract_snapshot_to_compare() -> None:
    assert sorted(SNAPSHOT_DIR.glob("*.yaml")), f"no contract snapshot under {SNAPSHOT_DIR}"


@pytest.mark.parametrize(("snapshot", "env"), _lanes(SNAPSHOT_DIR), ids=lambda value: getattr(value, "stem", value))
def test_a_product_tile_links_to_its_contract_hostname(snapshot: pathlib.Path, env: str) -> None:
    host = (yaml.safe_load(snapshot.read_text(encoding="utf-8"))["hostnames"]).get(env)
    assert host, f"{env}: the registry declares a {env} lane for {snapshot.stem}, its contract names no hostname"
    tile = _tile(_tables()[env], snapshot.stem)

    assert tile is not None, f"{env}: no tile for {snapshot.stem}"
    assert tile["url"] == f"https://{host}", (
        f"{env}: the {snapshot.stem} tile links to {tile['url']}, its contract names {host}"
    )
