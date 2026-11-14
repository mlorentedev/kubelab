"""IDP-053 D7: prod pulls only from registries that are always on.

``image_registry`` names a product's *source* registry, where CI pushed it. The forge
is on demand (ADR-028), so a prod pod pulling from it would fail to start whenever
the node is off. Forge-only images reach prod by a copy at promotion, which is the
instance's registry and is not built yet: until then no prod overlay image may name a
forge host. The test reads the committed overlays, so a hand edit or a product that
slipped into prod is caught where the manifests are, not where they were meant.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features import product_registry

REPO = Path(__file__).resolve().parents[1]
PROD_OVERLAY = REPO / "infra" / "k8s" / "overlays" / "prod"
COMMON = REPO / "infra" / "config" / "values" / "common.yaml"


def forge_hosts(common: dict[str, Any], products: dict[str, product_registry.Product]) -> set[str]:
    """The hosts of the forge: its own domain, and the registry host of every forge-hosted product."""
    hosts = {common["apps"]["services"]["core"]["gitea"]["domain"]}
    hosts |= {p.image_host for p in products.values() if p.forge == "gitea" and p.image_host}
    return hosts


def image_host(image: str) -> str | None:
    """The registry host of an image reference, or ``None`` for a Docker Hub shorthand (``gitea/gitea:1``)."""
    first, sep, _ = image.partition("/")
    return first if sep and ("." in first or ":" in first or first == "localhost") else None


def _images(node: Any) -> Iterator[str]:
    """Every image a manifest names: a container ``image:`` and a kustomize ``images:`` rename."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "image" and isinstance(value, str):
                yield value
            elif key == "images" and isinstance(value, list):
                yield from (item["newName"] for item in value if isinstance(item, dict) and "newName" in item)
            else:
                yield from _images(value)
    elif isinstance(node, list):
        for item in node:
            yield from _images(item)


def prod_overlay_images(root: Path = PROD_OVERLAY) -> dict[str, list[str]]:
    """Image references per file under the prod overlay, for every YAML document in it."""
    found = {}
    for path in sorted(root.rglob("*.y*ml")):
        images = [image for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")) for image in _images(doc)]
        if images:
            found[str(path.relative_to(root))] = images
    return found


def on_forge(images: dict[str, list[str]], hosts: set[str]) -> list[str]:
    return [f"{file}: {image}" for file, refs in images.items() for image in refs if image_host(image) in hosts]


@pytest.fixture(scope="module")
def hosts() -> set[str]:
    common = yaml.safe_load(COMMON.read_text(encoding="utf-8"))
    return forge_hosts(common, product_registry.load_registry().products)


def test_no_prod_overlay_image_points_at_a_forge_host(hosts: set[str]) -> None:
    assert on_forge(prod_overlay_images(), hosts) == []


@pytest.fixture(scope="module")
def forge() -> str:
    """The forge's host as ``common.yaml`` names it (``apps.services.core.gitea.domain``), never a copy of it."""
    return str(yaml.safe_load(COMMON.read_text(encoding="utf-8"))["apps"]["services"]["core"]["gitea"]["domain"])


def test_the_scan_reads_the_overlays_it_guards(hosts: set[str], forge: str) -> None:
    """A scan that found nothing would pass for any overlay: it has to see the images prod runs."""
    images = [image for refs in prod_overlay_images().values() for image in refs]
    assert "docker.io/mlorentedev/kubelab-web" in "".join(images)
    assert forge and forge in hosts, "the forge's own host (apps.services.core.gitea.domain) must be guarded"


class TestTheScanCatchesAForgeImage:
    def test_a_container_image_on_the_forge_is_found(self, tmp_path: Path, hosts: set[str], forge: str) -> None:
        image = f"{forge}/personal/beta:sha-0123456789ab"
        (tmp_path / "deploy.yaml").write_text(
            f"spec:\n  template:\n    spec:\n      containers:\n        - image: {image}\n",
            encoding="utf-8",
            newline="\n",
        )

        assert on_forge(prod_overlay_images(tmp_path), hosts) == [f"deploy.yaml: {image}"]

    def test_a_kustomize_rename_to_the_forge_is_found(self, tmp_path: Path, hosts: set[str], forge: str) -> None:
        (tmp_path / "kustomization.yaml").write_text(
            f"images:\n  - name: x\n    newName: {forge}/personal/x\n", encoding="utf-8", newline="\n"
        )

        assert on_forge(prod_overlay_images(tmp_path), hosts) == [f"kustomization.yaml: {forge}/personal/x"]

    def test_the_forge_host_of_a_registered_product_counts_too(self, tmp_path: Path) -> None:
        path = tmp_path / "products.yaml"
        path.write_text(
            "products:\n  beta:\n    repository: personal/beta\n    forge: gitea\n    receiver: generic\n"
            "    image_registry: registry.example.test/personal\n    events: {staging: beta-image-published}\n",
            encoding="utf-8",
            newline="\n",
        )
        common = {"apps": {"services": {"core": {"gitea": {"domain": "gitea.kubelab.live"}}}}}

        assert forge_hosts(common, product_registry.load_registry(path).products) == {
            "gitea.kubelab.live",
            "registry.example.test",
        }

    @pytest.mark.parametrize("image", ["gitea/gitea:1.27.3", "ghcr.io/mlorentedev/resume:1.0.0", "nginx"])
    def test_an_image_elsewhere_is_not(self, image: str, hosts: set[str]) -> None:
        assert on_forge({"f.yaml": [image]}, hosts) == []
