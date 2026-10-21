"""Every registered product has a tile in the platform manifest, at its contract's hostname (#2574).

`build_service_tables` writes the per-environment service rows of
`platform.json` by hand, one `_svc(...)` per service, so a product admitted to
`infra/config/products.yaml` gets no tile, and the web tile spells its own
hostnames. The rows stay hand-written: a tile's label, category and node are
not in the registry or the contract, so deriving them would mean inventing
fields there. These tests make the two sides fail when they part: a product the
registry names must have a tile in both environments, and for a product with a
contract snapshot, the tile must link to the snapshot's hostname for that env.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml

from toolkit.features import platform_manifest
from toolkit.features.product_registry import platform_apps
from toolkit.features.product_render import SNAPSHOT_DIR


def _tables() -> dict[str, list[dict[str, Any]]]:
    config = yaml.safe_load(platform_manifest.COMMON_YAML_PATH.read_text())
    staging, prod, _shared = platform_manifest.build_service_tables(config)
    return {"staging": staging, "prod": prod}


def _tile(rows: list[dict[str, Any]], app: str) -> dict[str, Any] | None:
    return next((row for row in rows if row["name"].lower() == app), None)


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_every_registered_product_has_a_tile(env: str) -> None:
    apps = platform_apps()
    assert apps, "the product registry names no product: nothing was checked"

    rows = _tables()[env]
    missing = [app for app in apps if _tile(rows, app) is None]

    assert missing == [], (
        f"ERROR: {env} has no platform tile for {missing}\n"
        "WHY: the platform manifest lists its services by hand, so a product admitted to "
        "infra/config/products.yaml is missing from platform.json\n"
        "FIX: add an _svc(...) row for it in build_service_tables (toolkit/features/platform_manifest.py), "
        "then `make sync-platform-json`"
    )


def test_there_is_a_contract_snapshot_to_compare() -> None:
    assert sorted(SNAPSHOT_DIR.glob("*.yaml")), f"no contract snapshot under {SNAPSHOT_DIR}"


@pytest.mark.parametrize("env", ["staging", "prod"])
@pytest.mark.parametrize("snapshot", sorted(SNAPSHOT_DIR.glob("*.yaml")), ids=lambda path: path.stem)
def test_a_product_tile_links_to_its_contract_hostname(snapshot: pathlib.Path, env: str) -> None:
    host = yaml.safe_load(snapshot.read_text())["hostnames"][env]
    tile = _tile(_tables()[env], snapshot.stem)

    assert tile is not None, f"{env}: no tile for {snapshot.stem}"
    assert tile["url"] == f"https://{host}", (
        f"{env}: the {snapshot.stem} tile links to {tile['url']}, its contract names {host}"
    )
